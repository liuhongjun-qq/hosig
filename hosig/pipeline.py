from dataclasses import dataclass
from time import perf_counter

import numpy as np
from scipy import sparse

from .config import Config
from ._01data import micro_batches
from ._02encoding import ContentEncoder, RandomFourierFeatures
from ._03forest import RandomPartitionForest
from ._04graph import fiedler_order, mutual_topk_graph
from ._05segmentation import Segmentation, contrastive_segment
from ._07signatures import HoSig, build_signatures


@dataclass
class BatchResult:
    embeddings: np.ndarray
    graph: sparse.csr_matrix
    order: np.ndarray
    segmentation: Segmentation
    signatures: list[HoSig]
    diagnostics: dict

    @property
    def labels(self):
        return self.segmentation.labels


# 程序专门创建了一个负责执行 HoSig-Align I 算法的工具。
class HoSigAlign:
    # 初始化模型:准备处理工具
    def __init__(self, config=None):
        self.config = config or Config()
        self.encoder = ContentEncoder(self.config)
        self.rff = RandomFourierFeatures(self.config)

    #处理一批网络安全事件	正式分析一批数据 
    def process_batch(self, events, batch_id="0"):
        if not events:
            raise ValueError("Cannot process an empty batch")
        if len(events) > self.config.batch_size:
            raise ValueError("Batch exceeds batch_size; use process_stream or increase the configured budget")
        start = perf_counter()
        timings = {}
        embeddings = self.encoder.transform(events)
        timings["encoding"] = perf_counter() - start
        stage_start = perf_counter()
        forest = RandomPartitionForest(
            self.config.trees, self.config.leaf_size, self.config.seed,
        ).fit(embeddings)
        timings["forest"] = perf_counter() - stage_start
        stage_start = perf_counter()
        timestamps = np.array([event.timestamp for event in events])
        graph, decay = mutual_topk_graph(forest, timestamps, self.config)
        timings["graph"] = perf_counter() - stage_start
        stage_start = perf_counter()
        order, components, warnings = fiedler_order(graph, self.config.seed)
        timings["spectral"] = perf_counter() - stage_start
        stage_start = perf_counter()
        rff = self.rff.transform(embeddings)
        segmentation = contrastive_segment(graph, order, components, rff, self.config)
        timings["segmentation"] = perf_counter() - stage_start
        stage_start = perf_counter()
        signatures = build_signatures(events, graph, segmentation.blocks, rff, self.config, batch_id)
        timings["signatures"] = perf_counter() - stage_start
        timings["total"] = perf_counter() - start
        graph_bytes = graph.data.nbytes + graph.indices.nbytes + graph.indptr.nbytes
        diagnostics = {
            "n_events": len(events), "n_blocks": len(signatures), "n_edges": graph.nnz // 2,
            "mean_degree": float(graph.nnz / len(events)),
            "n_components": int(len(np.unique(components))),
            "segmentation_penalty": segmentation.penalty,
            "positive_gain_candidates": int(np.count_nonzero(segmentation.costs[1:-1] > segmentation.penalty)),
            "warnings": warnings, "half_lives": decay, "timings_seconds": timings,
            "representation_bytes": embeddings.nbytes, "sparse_graph_bytes": int(graph_bytes),
            "signature_numeric_bytes": sum(signature.numeric_bytes for signature in signatures),
        }
        return BatchResult(embeddings, graph, order, segmentation, signatures, diagnostics)
    # 将连续事件分成多个批次处理:负责安排一批接一批地处理
    def process_stream(self, events):
        for batch_id, batch in enumerate(micro_batches(events, self.config.batch_size)):
            yield self.process_batch(batch, str(batch_id))



