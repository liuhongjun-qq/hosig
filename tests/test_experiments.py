from dataclasses import replace
import json

import numpy as np

from hosig import Config, HoSigAlign
from hosig.baselines import fit_baseline
from hosig.cli import main
from hosig.data import generate_synthetic
from hosig.experiments import benchmark


def fast_config():
    return Config(embedding_dim=16, vocabulary_size=64, rff_dim=32, trees=5, leaf_size=4, top_k=4, batch_size=128, time_bins=4, left_window=4, right_window=4, min_block_size=2)


def test_baselines_cover_every_event():
    result = HoSigAlign(fast_config()).process_batch(list(generate_synthetic(40)))
    for method in ("hdbscan", "spectral", "louvain"):
        labels, warnings = fit_baseline(method, result.embeddings, result.graph)
        assert labels.shape == (40,)
        assert labels.dtype.kind in "iu"


def test_held_out_benchmark_has_four_methods_and_no_label_tuning():
    events = list(generate_synthetic(48))
    first = benchmark(events, fast_config(), [4], [1])
    changed = [replace(event, label="not_used_for_selection") for event in events]
    second = benchmark(changed, fast_config(), [4], [1])
    assert {record["method"] for record in first["records"]} == {"hosig", "hdbscan", "spectral", "louvain"}
    assert [item["selected"] for item in first["baseline_selection"]] == [item["selected"] for item in second["baseline_selection"]]
    assert all(record["n_events"] == 39 for record in first["records"])


def test_cli_complete_demo(tmp_path):
    output = tmp_path / "demo"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(fast_config().to_dict()))
    assert main(["demo", "--output", str(output), "--events", "24", "--config", str(config_path)]) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["total_events"] == 24
    assert (output / "signatures.jsonl").is_file()
    assert (output / "first_batch_boundaries.png").is_file()
    assert main(["align", "--signatures", str(output / "signatures.jsonl"), "--output", str(output / "hypergraph.json")]) == 0
