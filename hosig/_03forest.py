#事件相似度：随机划分森林、计算共同叶相似度
import numpy as np

class RandomPartitionForest:
    def __init__(self, trees=64, leaf_size=16, seed=42):
        if trees < 1 or leaf_size < 1:
            raise ValueError("trees and leaf_size must be positive")
        self.trees = trees
        self.leaf_size = leaf_size
        self.seed = seed

    def fit(self, embeddings):
        embeddings = np.asarray(embeddings)
        if embeddings.ndim != 2 or embeddings.shape[1] < 1 or not np.isfinite(embeddings).all():
            raise ValueError("embeddings must be a finite matrix with at least one feature")
        generator = np.random.default_rng(self.seed)
        n_events = len(embeddings)
        self.leaf_ids_ = np.empty((n_events, self.trees), dtype=np.int32)
        self.members_ = []
        for tree_index in range(self.trees):
            leaves = []
            pending = [np.arange(n_events)] if n_events else []
            while pending:
                indices = pending.pop()
                if len(indices) > self.leaf_size:
                    values = embeddings[indices]
                    minima = values.min(axis=0)
                    maxima = values.max(axis=0)
                    dimensions = np.flatnonzero(maxima > minima)
                    if len(dimensions):
                        dimension = int(generator.choice(dimensions))
                        threshold = generator.uniform(minima[dimension], maxima[dimension])
                        threshold = min(threshold, np.nextafter(float(maxima[dimension]), -np.inf))
                        coordinate = values[:, dimension].astype(float)
                        left = indices[coordinate <= threshold]
                        right = indices[coordinate > threshold]
                        if len(left) and len(right):
                            pending.extend((right, left))
                            continue
                self.leaf_ids_[indices, tree_index] = len(leaves)
                leaves.append(indices)
            self.members_.append(leaves)
        return self

    def neighbors(self, index):
        members = [
            self.members_[tree][self.leaf_ids_[index, tree]] for tree in range(self.trees)
        ]
        candidates, counts = np.unique(np.concatenate(members), return_counts=True)
        keep = candidates != index
        return candidates[keep], counts[keep] / self.trees

    def pair_similarity(self, first, second):
        return float(np.mean(self.leaf_ids_[first] == self.leaf_ids_[second]))
