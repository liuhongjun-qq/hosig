# 计算签名距离、进行块对齐、构建或更新超图

from dataclasses import dataclass, field
import math

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import jensenshannon, squareform


def dtw_distance(first, second):
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if not len(first) or not len(second):
        raise ValueError("DTW sequences must be nonempty")
    previous = np.full(len(second) + 1, np.inf)
    previous[0] = 0
    for first_value in first:
        current = np.full(len(second) + 1, np.inf)
        for column, second_value in enumerate(second, 1):
            current[column] = (first_value - second_value)**2 + min(
                previous[column], current[column - 1], previous[column - 1],
            )
        previous = current
    return float(np.sqrt(previous[-1]))


def block_distance(first, second, weights=(1 / 3, 1 / 3, 1 / 3)):
    if first.feature_space_id != second.feature_space_id:
        raise ValueError("Incompatible feature spaces; all sites must share encoder, RFF and sketch configuration")
    if len(weights) != 3 or any(not math.isfinite(value) or value < 0 for value in weights) or sum(weights) <= 0:
        raise ValueError("weights must contain three finite nonnegative values with positive sum")
    prototype = float(np.linalg.norm(first.prototype - second.prototype))
    temporal = dtw_distance(first.time_histogram, second.time_histogram)
    first_counts, second_counts = first.cms.astype(float).ravel(), second.cms.astype(float).ravel()
    if first_counts.sum() == 0 and second_counts.sum() == 0:
        contextual = 0.0
    elif first_counts.sum() == 0 or second_counts.sum() == 0:
        contextual = float(np.sqrt(np.log(2)))
    else:
        contextual = float(jensenshannon(first_counts, second_counts))
    return float(np.dot(weights, (prototype, temporal, contextual)))


@dataclass
class Hyperedge:
    members: list = field(default_factory=list)
    representative: int = 0


class PrototypeHypergraph:
    def __init__(self, cluster_threshold=1.0, merge_threshold=1.0, split_threshold=0.5, weights=(1 / 3, 1 / 3, 1 / 3)):
        if not all(math.isfinite(value) for value in (cluster_threshold, merge_threshold, split_threshold)) or cluster_threshold < 0 or merge_threshold < 0 or not 0 <= split_threshold <= 1:
            raise ValueError("Invalid hypergraph thresholds")
        if len(weights) != 3 or any(not math.isfinite(value) or value < 0 for value in weights) or sum(weights) <= 0:
            raise ValueError("weights must contain three finite nonnegative values with positive sum")
        self.cluster_threshold = cluster_threshold
        self.merge_threshold = merge_threshold
        self.split_threshold = split_threshold
        self.weights = weights
        self.edges = []

    def _matrix(self, members):
        distances = np.zeros((len(members), len(members)))
        for first in range(len(members)):
            for second in range(first + 1, len(members)):
                distances[first, second] = distances[second, first] = block_distance(
                    members[first], members[second], self.weights,
                )
        return distances

    def _edge(self, members):
        distances = self._matrix(members)
        return Hyperedge(members, int(np.argmin(distances.sum(axis=1))))

    def _cluster(self, members, threshold):
        if len(members) <= 1:
            return [self._edge(members)] if members else []
        distances = self._matrix(members)
        labels = fcluster(linkage(squareform(distances), method="complete"), threshold, criterion="distance")
        return [self._edge([members[index] for index in np.flatnonzero(labels == label)]) for label in np.unique(labels)]

    def fit(self, signatures):
        self.edges = self._cluster(list(signatures), self.cluster_threshold)
        return self

    def cohesion(self, edge):
        if len(edge.members) < 2:
            return 1.0
        distances = self._matrix(edge.members)
        pair_distances = distances[np.triu_indices(len(edge.members), 1)]
        return float(np.exp(-pair_distances).mean())

    def add(self, signature):
        if not self.edges:
            self.edges.append(Hyperedge([signature]))
            return
        distances = [block_distance(signature, edge.members[edge.representative], self.weights) for edge in self.edges]
        closest = int(np.argmin(distances))
        if distances[closest] > self.merge_threshold:
            self.edges.append(Hyperedge([signature]))
            return
        edge = self._edge(self.edges[closest].members + [signature])
        if self.cohesion(edge) < self.split_threshold:
            threshold = min(self.cluster_threshold, -np.log(max(self.split_threshold, 1e-12)))
            self.edges[closest:closest + 1] = self._cluster(edge.members, threshold)
        else:
            self.edges[closest] = edge

    def to_dict(self):
        return {
            "cluster_threshold": self.cluster_threshold, "merge_threshold": self.merge_threshold,
            "split_threshold": self.split_threshold, "weights": list(self.weights),
            "hyperedges": [
                {
                    "members": [member.block_id for member in edge.members],
                    "representative": edge.members[edge.representative].block_id,
                    "cohesion": self.cohesion(edge),
                } for edge in self.edges
            ],
        }
