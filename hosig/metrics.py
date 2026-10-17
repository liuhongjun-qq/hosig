# 计算聚类和块质量指标

import math
from collections import Counter

import networkx as nx
import numpy as np
from scipy.spatial.distance import cdist
from sklearn.metrics import (
    adjusted_rand_score, calinski_harabasz_score, normalized_mutual_info_score, silhouette_score,
)
from sklearn.preprocessing import StandardScaler


def boundary_clarity(entities, proportion=0.05):
    if not 0 < proportion <= 1:
        raise ValueError("proportion must be in (0, 1]")
    entities = np.asarray(entities, dtype=float)
    count = len(entities)
    if count < 2:
        return {"entity_count": count, "neighbor_rank": None, "iir_k": [], "iir_norm": []}
    standardized = StandardScaler().fit_transform(entities)
    distances = cdist(standardized, standardized)
    np.fill_diagonal(distances, np.inf)
    rank = min(count - 1, max(1, math.ceil(proportion * count)))
    nearest = np.partition(distances, rank - 1, axis=1)[:, rank - 1]
    median = float(np.median(nearest))
    reciprocal = [float(1 / value) if value > 0 else None for value in nearest]
    normalized = [float(median / value) if value > 0 and median > 0 else None for value in nearest]
    return {
        "entity_count": count, "neighbor_rank": rank, "iir_k": reciprocal,
        "iir_norm": normalized, "duplicate_entity_count": int(np.count_nonzero(nearest == 0)),
    }


def cluster_metrics(embeddings, labels, graph=None, entities=None, truth=None, seed=42):
    embeddings = np.asarray(embeddings)
    labels = np.asarray(labels)
    valid = labels >= 0
    cluster_ids = np.unique(labels[valid])
    scores = {
        "n_events": len(labels), "n_clusters": len(cluster_ids),
        "noise_rate": float(np.mean(~valid)) if len(labels) else 0.0,
        "ch": None, "silhouette": None, "modularity": None,
        "ari": None, "nmi": None,
        "truth_class_count": 0, "truth_label_counts": {},
    }
    if 1 < len(cluster_ids) < np.count_nonzero(valid):
        scores["ch"] = float(calinski_harabasz_score(embeddings[valid], labels[valid]))
        try:
            scores["silhouette"] = float(silhouette_score(
                embeddings[valid], labels[valid], sample_size=min(2000, int(valid.sum())), random_state=seed,
            ))
        except ValueError:
            scores["silhouette"] = None
    if graph is not None and np.count_nonzero(valid):
        network = nx.from_scipy_sparse_array(graph[valid][:, valid])
        valid_labels = labels[valid]
        communities = [set(np.flatnonzero(valid_labels == label).tolist()) for label in cluster_ids]
        if network.size(weight="weight") > 0:
            scores["modularity"] = float(nx.community.modularity(network, communities, weight="weight"))
    if truth is not None:
        known = np.array([value is not None for value in truth])
        scores["truth_label_counts"] = dict(sorted(Counter(str(value) for value in truth if value is not None).items()))
        scores["truth_class_count"] = len(scores["truth_label_counts"])
        if np.count_nonzero(known) >= 2:
            known_truth = np.array([str(value) if value is not None else "" for value in truth])
            scores["ari"] = float(adjusted_rand_score(known_truth[known], labels[known]))
            scores["nmi"] = float(normalized_mutual_info_score(known_truth[known], labels[known]))
    if entities is None:
        entities = np.array([embeddings[labels == label].mean(axis=0) for label in cluster_ids])
    scores["boundary_clarity"] = boundary_clarity(entities)
    return scores
