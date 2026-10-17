from dataclasses import replace
import itertools

import numpy as np
import pytest
from scipy import sparse

from hosig import Config, Event, HoSigAlign
from hosig.data import generate_synthetic, micro_batches, parse_timestamp, read_events, write_events
from hosig.encoding import ContentEncoder, RandomFourierFeatures
from hosig.forest import RandomPartitionForest
from hosig.graph import calibrate_half_lives, fiedler_order, mutual_topk_graph, temporal_decay
from hosig.metrics import boundary_clarity, cluster_metrics
from hosig.segmentation import _optimal_boundaries, contrastive_costs, contrastive_segment
from hosig.signatures import build_signatures, load_signatures, save_signatures
from hosig.sketches import CountMinSketch, HyperLogLog


@pytest.fixture
def small_config():
    return Config(embedding_dim=32, rff_dim=64, vocabulary_size=128, trees=12, leaf_size=4, top_k=5, left_window=4, right_window=4, min_block_size=3, batch_size=128, time_bins=8)


@pytest.mark.parametrize("field,value", [
    ("trees", 0), ("top_k", -1), ("alpha", 1.1), ("decay_floor", -0.1),
    ("short_half_life", 0), ("segmentation_beta", -1), ("hll_precision", 2),
    ("embedding_dim", 2.5), ("eta", float("nan")), ("batch_size", True),
])
def test_invalid_configuration(field, value):
    with pytest.raises(ValueError):
        Config(**{field: value})


def test_default_config_file_matches_code_and_rejects_unknown_keys(tmp_path):
    from pathlib import Path

    assert Config.load(Path(__file__).parents[1] / "configs" / "paper.json") == Config()
    path = tmp_path / "config.json"
    path.write_text('{"wrong_key": 123}')
    with pytest.raises(ValueError, match="Unknown"):
        Config.load(path)


def test_content_encoder_has_no_time_context_or_label_input(small_config):
    event = Event(0, "192.168.1.1", "10.1.2.3", "GET /device exploit", {"service": "web"}, "first")
    changed = replace(event, timestamp=10**9, label="second", context={"different": "metadata"})
    encoder = ContentEncoder(small_config)
    np.testing.assert_array_equal(encoder.transform([event]), encoder.transform([changed]))
    np.testing.assert_array_equal(encoder.transform([event]), ContentEncoder(small_config).transform([event]))


def test_rff_is_shared_between_batches(small_config):
    embeddings = ContentEncoder(small_config).transform(list(generate_synthetic(9)))
    rff = RandomFourierFeatures(small_config)
    np.testing.assert_allclose(rff.transform(embeddings), np.vstack([rff.transform(embeddings[:4]), rff.transform(embeddings[4:])]), atol=1e-6)


def test_forest_leaf_frequency_and_leaf_cap():
    embeddings = np.random.default_rng(9).normal(size=(45, 5))
    forest = RandomPartitionForest(12, 4, 2).fit(embeddings)
    assert all(len(leaf) <= 4 for leaves in forest.members_ for leaf in leaves)
    for index in range(len(embeddings)):
        candidates, similarity = forest.neighbors(index)
        actual = dict(zip(candidates, similarity))
        for other in range(len(embeddings)):
            if index != other:
                assert actual.get(other, 0) == pytest.approx(forest.pair_similarity(index, other))


def test_identical_points_terminate_and_remain_similar():
    forest = RandomPartitionForest(5, 2).fit(np.ones((20, 3)))
    assert forest.pair_similarity(0, 19) == 1
    assert all(len(leaves) == 1 for leaves in forest.members_)


def test_neighbor_graph_equals_brute_force_mutual_topk(small_config):
    embeddings = np.random.default_rng(3).normal(size=(17, 4))
    times = np.arange(17) * 3.0
    forest = RandomPartitionForest(12, 4).fit(embeddings)
    graph, half_lives = mutual_topk_graph(forest, times, small_config)
    scores = np.zeros((17, 17))
    selected = np.zeros_like(scores, dtype=bool)
    for first in range(17):
        for second in range(17):
            if first != second:
                scores[first, second] = forest.pair_similarity(first, second) * temporal_decay(
                    times[first] - times[second], small_config.decay_floor, small_config.alpha,
                    half_lives["short_half_life"], half_lives["long_half_life"],
                )
        candidates = np.flatnonzero(scores[first] > 0)
        order = np.lexsort((candidates, -scores[first, candidates]))[:small_config.top_k]
        selected[first, candidates[order]] = True
    expected = scores * (selected & selected.T)
    np.testing.assert_allclose(graph.toarray(), expected)
    assert max(graph.getnnz(axis=1)) <= small_config.top_k
    assert np.all(graph.diagonal() == 0)


def test_decay_half_life_and_floor():
    np.testing.assert_allclose(temporal_decay([0, 10, 10000], 0.1, 0.5, 10, 10), [1, 0.55, 0.1])
    short, long = calibrate_half_lives([0, 0, 0], Config())
    assert long >= short > 0


def test_fiedler_order_keeps_components_contiguous():
    graph = sparse.block_diag((sparse.csr_matrix(np.ones((4, 4)) - np.eye(4)), np.ones((3, 3)) - np.eye(3), np.zeros((1, 1))), format="csr")
    order, components, warnings = fiedler_order(graph)
    assert sorted(order.tolist()) == list(range(8))
    assert len(np.unique(components[order[:4]])) == 1
    assert len(np.unique(components[order[4:7]])) == 1
    assert not warnings


def test_contrastive_cost_matches_equation_seven():
    graph = sparse.csr_matrix([[0, 0.8, 0.1, 0], [0.8, 0, 0.1, 0], [0.1, 0.1, 0, 0.7], [0, 0, 0.7, 0]])
    rff = np.array([[1, 0], [1, 0], [0, 1], [0, 1]], dtype=float)
    costs = contrastive_costs(graph, np.arange(4), rff, 2, 2, 1)
    expected = 2 + 1.6 / 4 + 1.4 / 4 - 2 * 0.2 / 4
    assert costs[2] == pytest.approx(expected)


def test_dynamic_program_matches_exhaustive_objective():
    gains = np.array([0, -2, 1, 4, 0.5, 3, 2, 1, 5, 0, -1, 0], dtype=float)
    minimum, end = 3, 11
    selected = _optimal_boundaries(0, end, gains, minimum)
    legal_scores = [0.0]
    candidates = range(minimum, end - minimum + 1)
    for size in range(1, len(candidates) + 1):
        for subset in itertools.combinations(candidates, size):
            if all(right - left >= minimum for left, right in zip(subset[:-1], subset[1:])):
                legal_scores.append(float(gains[list(subset)].sum()))
    assert gains[selected].sum() == pytest.approx(max(legal_scores))


def test_boundary_detector_finds_planted_change_in_connected_graph():
    graph = sparse.block_diag([sparse.csr_matrix(np.ones((8, 8)) - np.eye(8))] * 2, format="lil")
    graph[7, 8] = graph[8, 7] = 0.0001
    rff = np.array([[1, 0]] * 8 + [[0, 1]] * 8, dtype=float)
    config = Config(left_window=2, right_window=2, min_block_size=4, segmentation_beta=0.01)
    result = contrastive_segment(graph.tocsr(), np.arange(16), np.zeros(16, dtype=int), rff, config)
    assert result.boundaries == [8]
    assert len(result.blocks) == 2


def test_sketches_count_and_cardinality():
    cms = CountMinSketch(256, 4, "secret")
    hll = HyperLogLog(10, "secret")
    for index in range(1000):
        cms.add(f"item{index}", 2)
        hll.add(f"item{index}")
        hll.add(f"item{index}")
    assert cms.estimate("item9") >= 2
    assert hll.estimate() == pytest.approx(1000, rel=0.15)
    assert HyperLogLog().estimate() == 0


def test_pipeline_coverage_serialization_and_reproducibility(small_config, tmp_path):
    events = list(generate_synthetic(48))
    first = HoSigAlign(small_config).process_batch(events)
    second = HoSigAlign(small_config).process_batch(events)
    np.testing.assert_array_equal(first.labels, second.labels)
    assert sorted(np.concatenate(first.segmentation.blocks).tolist()) == list(range(48))
    assert sum(signature.count for signature in first.signatures) == 48
    assert sum(int(signature.time_histogram.sum()) for signature in first.signatures) == 48
    path = tmp_path / "signatures.jsonl"
    save_signatures(path, first.signatures)
    decoded = load_signatures(path)
    np.testing.assert_array_equal(first.signatures[0].prototype, decoded[0].prototype)
    exported = path.read_text()
    assert events[0].src_ip not in exported
    assert events[0].payload not in exported


def test_changing_ground_truth_does_not_change_blocks(small_config):
    events = list(generate_synthetic(32))
    changed = [replace(event, label="arbitrary") for event in events]
    first = HoSigAlign(small_config).process_batch(events)
    second = HoSigAlign(small_config).process_batch(changed)
    np.testing.assert_array_equal(first.labels, second.labels)
    assert [signature.to_dict() for signature in first.signatures] == [signature.to_dict() for signature in second.signatures]


def test_single_event_and_batch_budget(small_config):
    model = HoSigAlign(small_config)
    result = model.process_batch(list(generate_synthetic(1)))
    assert result.labels.tolist() == [0]
    assert result.signatures[0].boundary_ratio is None
    with pytest.raises(ValueError):
        model.process_batch([])
    with pytest.raises(ValueError):
        model.process_batch(list(generate_synthetic(129)))
    assert [len(batch) for batch in micro_batches(generate_synthetic(17), 8)] == [8, 8, 1]


def test_time_histogram_handles_submicrosecond_epoch_intervals():
    origin = 1545403816.0
    events = [Event(timestamp, "10.0.0.1", "10.0.0.2") for timestamp in (origin, np.nextafter(origin, np.inf))]
    signatures = build_signatures(events, sparse.csr_matrix((2, 2)), [np.array([0, 1])], np.zeros((2, 512), dtype=np.float32), Config())
    histogram = signatures[0].time_histogram
    assert int(histogram.sum()) == 2
    assert histogram[0] == 1 and histogram[-1] == 1


def test_boundary_clarity_formula_and_undefined_cases():
    score = boundary_clarity([[0], [1], [3]], 0.05)
    assert score["neighbor_rank"] == 1
    np.testing.assert_allclose(score["iir_norm"], [1, 1, 0.5])
    assert boundary_clarity([[1]])["iir_k"] == []
    assert boundary_clarity([[1], [1]])["iir_k"] == [None, None]


def test_all_noise_and_single_cluster_scores():
    features = np.array([[0, 1], [1, 0], [0, 0]])
    assert cluster_metrics(features, [-1, -1, -1])["ch"] is None
    assert cluster_metrics(features, [0, 0, 0])["silhouette"] is None


def test_event_roundtrip_and_explicit_proxy_mode(tmp_path):
    events = list(generate_synthetic(5))
    path = tmp_path / "events.jsonl"
    write_events(path, events)
    assert list(read_events(path)) == events
    csv_path = tmp_path / "network.csv"
    csv_path.write_text("src_ip,dst_ip,proto,type,label,duration\n10.0.0.1,10.1.0.1,tcp,malware,1,99999\n", encoding="utf-8")
    with pytest.raises(ValueError, match="explicit"):
        list(read_events(csv_path, "network-csv"))
    event = list(read_events(csv_path, "network-csv", proxy_interval=5))[0]
    assert event.timestamp == 0
    assert "malware" not in event.payload
    assert "99999" not in event.payload
    assert event.label == "malware"


def test_timezone_and_finite_timestamps():
    assert parse_timestamp("2025-01-06T08:00:00+08:00") == parse_timestamp("2025-01-06T00:00:00Z")
    with pytest.raises(ValueError, match="timezone"):
        parse_timestamp("2025-01-06T00:00:00")
    with pytest.raises(ValueError):
        Event(float("nan"), "10.0.0.1", "10.0.0.2")
