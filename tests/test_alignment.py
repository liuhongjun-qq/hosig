from dataclasses import replace

import numpy as np
import pytest

from hosig.alignment import PrototypeHypergraph, block_distance, dtw_distance
from hosig.signatures import HoSig


def signature(identifier, value=0.0):
    return HoSig(identifier, "shared", 2, np.array([value, 0], dtype=np.float32), np.array([1, 1], dtype=np.uint32), np.array([[2, 0]], dtype=np.uint32), np.zeros(16, dtype=np.uint8), 1.0, 0.0, [])


def test_multiview_identity_symmetry_and_feature_space_guard():
    first, second = signature("a"), signature("b", 0.3)
    assert block_distance(first, first) == 0
    assert block_distance(first, second) == pytest.approx(block_distance(second, first))
    assert block_distance(first, second, (1, 0, 0)) == pytest.approx(0.3)
    with pytest.raises(ValueError, match="feature spaces"):
        block_distance(first, replace(second, feature_space_id="different"))
    with pytest.raises(ValueError):
        block_distance(first, second, (0, 0, 0))


def test_dtw_uses_elastic_alignment():
    assert dtw_distance([0, 1, 1, 0], [0, 1, 0]) == 0
    assert dtw_distance([1], [3]) == 2


def test_hierarchical_hyperedges_and_incremental_merge():
    graph = PrototypeHypergraph(0.5, 0.5, 0.5, (1, 0, 0))
    graph.fit([signature("a"), signature("b", 0.1), signature("c", 3)])
    assert sorted(len(edge.members) for edge in graph.edges) == [1, 2]
    graph.add(signature("d", 0.2))
    assert sorted(len(edge.members) for edge in graph.edges) == [1, 3]
    graph.add(signature("e", 9))
    assert len(graph.edges) == 3


def test_incremental_cohesion_triggers_split():
    graph = PrototypeHypergraph(10, 10, 0.8, (1, 0, 0))
    graph.add(signature("a"))
    graph.add(signature("b", 5))
    assert len(graph.edges) == 2


@pytest.mark.parametrize("parameters", [{"weights": (0, 0, 0)}, {"cluster_threshold": float("nan")}, {"merge_threshold": -1}])
def test_invalid_hypergraph_parameters(parameters):
    with pytest.raises(ValueError):
        PrototypeHypergraph(**parameters)
