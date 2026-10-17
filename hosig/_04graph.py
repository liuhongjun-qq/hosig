#图构建与排序：时间衰减、稀疏图构建、Fiedler 谱排序

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components, laplacian
from scipy.sparse.linalg import ArpackNoConvergence, eigsh

from .config import Config


def calibrate_half_lives(timestamps, config: Config):
    times = np.sort(np.asarray(timestamps, dtype=float))
    gaps = np.diff(times)
    gaps = gaps[gaps > 0]
    median = float(np.median(gaps)) if len(gaps) else 1.0
    mad = float(np.median(np.abs(gaps - median))) if len(gaps) else 0.0
    short = config.short_half_life or median
    long = config.long_half_life or max(short, median + 3 * mad)
    return float(short), float(long)


def temporal_decay(delta, floor, alpha, short_half_life, long_half_life):
    if not 0 <= floor <= 1 or not 0 <= alpha <= 1:
        raise ValueError("floor and alpha must be in [0, 1]")
    if short_half_life <= 0 or long_half_life <= 0:
        raise ValueError("half lives must be positive")
    delta = np.abs(np.asarray(delta, dtype=float))
    return floor + (1 - floor) * (
        alpha * np.exp2(-delta / short_half_life)
        + (1 - alpha) * np.exp2(-delta / long_half_life)
    )


def mutual_topk_graph(forest, timestamps, config: Config):
    timestamps = np.asarray(timestamps, dtype=float)
    if not np.isfinite(timestamps).all() or len(timestamps) != len(forest.leaf_ids_):
        raise ValueError("timestamps must be finite and match the forest")
    short, long = calibrate_half_lives(timestamps, config)
    rows, columns, weights = [], [], []
    for index in range(len(timestamps)):
        candidates, similarities = forest.neighbors(index)
        scores = similarities * temporal_decay(
            timestamps[index] - timestamps[candidates], config.decay_floor, config.alpha, short, long,
        )
        positive = scores > 0
        candidates, scores = candidates[positive], scores[positive]
        selected = np.lexsort((candidates, -scores))[:config.top_k]
        rows.extend([index] * len(selected))
        columns.extend(candidates[selected].tolist())
        weights.extend(scores[selected].tolist())
    directed = sparse.csr_matrix((weights, (rows, columns)), shape=(len(timestamps), len(timestamps)))
    graph = directed.minimum(directed.T).tocsr()
    graph.eliminate_zeros()
    return graph, {"short_half_life": short, "long_half_life": long}


def fiedler_order(graph, seed=42):
    graph = sparse.csr_matrix(graph)
    n_events = graph.shape[0]
    if graph.shape[1] != n_events:
        raise ValueError("graph must be square")
    if not n_events:
        return np.empty(0, dtype=int), np.empty(0, dtype=int), []
    _, components = connected_components(graph, directed=False)
    groups = [np.flatnonzero(components == label) for label in np.unique(components)]
    groups.sort(key=lambda indices: int(indices[0]))
    order = []
    warnings = []
    for indices in groups:
        if len(indices) <= 2:
            order.extend(indices.tolist())
            continue
        operator = laplacian(graph[indices][:, indices], normed=True)
        if len(indices) <= 64:
            values, vectors = np.linalg.eigh(operator.toarray())
        else:
            try:
                values, vectors = eigsh(
                    operator, k=2, which="SM", tol=1e-6,
                    v0=np.random.default_rng(seed).normal(size=len(indices)),
                    maxiter=max(1000, len(indices) * 20),
                )
            except ArpackNoConvergence:
                warnings.append(f"Lanczos did not converge for component size {len(indices)}; index order used")
                order.extend(indices.tolist())
                continue
        vector = vectors[:, np.argsort(values)[1]]
        pivot = int(np.argmax(np.abs(vector)))
        if vector[pivot] < 0:
            vector = -vector
        order.extend(indices[np.lexsort((indices, vector))].tolist())
    return np.asarray(order, dtype=int), components, warnings
