# 同源块签名：生成、保存和加载 HoSig 签名

from collections import Counter
from dataclasses import dataclass
import json

import numpy as np

from .config import Config
from ._02encoding import payload_tokens, stable_hash
from ._06sketches import CountMinSketch, HyperLogLog, context_tokens


@dataclass
class HoSig:
    block_id: str
    feature_space_id: str
    count: int
    prototype: np.ndarray
    time_histogram: np.ndarray
    cms: np.ndarray
    hll_registers: np.ndarray
    distinct_context_estimate: float
    boundary_ratio: float | None
    top_features: list[dict]

    @property
    def numeric_bytes(self):
        return int(sum(array.nbytes for array in (
            self.prototype, self.time_histogram, self.cms, self.hll_registers,
        )))

    def to_dict(self):
        return {
            "block_id": self.block_id, "feature_space_id": self.feature_space_id,
            "count": self.count, "prototype": self.prototype.tolist(),
            "time_histogram": self.time_histogram.tolist(), "cms": self.cms.tolist(),
            "hll_registers": self.hll_registers.tolist(),
            "distinct_context_estimate": self.distinct_context_estimate,
            "boundary_ratio": self.boundary_ratio, "boundary_ratio_direction": "lower_is_clearer",
            "top_features": self.top_features, "numeric_bytes": self.numeric_bytes,
        }

    @classmethod
    def from_dict(cls, record):
        return cls(
            block_id=record["block_id"], feature_space_id=record["feature_space_id"],
            count=record["count"], prototype=np.asarray(record["prototype"], dtype=np.float32),
            time_histogram=np.asarray(record["time_histogram"], dtype=np.uint32),
            cms=np.asarray(record["cms"], dtype=np.uint32),
            hll_registers=np.asarray(record["hll_registers"], dtype=np.uint8),
            distinct_context_estimate=record["distinct_context_estimate"],
            boundary_ratio=record["boundary_ratio"], top_features=record["top_features"],
        )


def _information_gain(total, block_size, present, present_in_block):
    counts = np.array([
        [present_in_block, block_size - present_in_block],
        [present - present_in_block, total - block_size - present + present_in_block],
    ], dtype=float)
    joint = counts / total
    independent = np.outer(joint.sum(axis=1), joint.sum(axis=0))
    mask = joint > 0
    return max(0.0, float(np.sum(joint[mask] * np.log2(joint[mask] / independent[mask]))))


def build_signatures(events, graph, blocks, rff, config: Config, batch_id="0"):
    token_sets = [
        set(context_tokens(event.context)) | {f"payload:{token}" for token in payload_tokens(event.payload)}
        for event in events
    ]
    global_counts = Counter(token for tokens in token_sets for token in tokens)
    signatures = []
    n_events = len(events)
    for block_number, indices in enumerate(blocks):
        times = np.array([events[index].timestamp for index in indices])
        relative_times = times - times.min()
        span = float(relative_times.max())
        histogram = np.histogram(relative_times, bins=config.time_bins, range=(0.0, span if span > 0 else 1.0))[0].astype(np.uint32)
        cms = CountMinSketch(config.cms_width, config.cms_depth, config.context_salt)
        hll = HyperLogLog(config.hll_precision, config.context_salt)
        for index in indices:
            for token in context_tokens(events[index].context):
                cms.add(token)
                hll.add(token)
        within_weight = float(graph[indices][:, indices].sum())
        crossing_weight = float(graph[indices].sum()) - within_weight
        within_mean = within_weight / (len(indices) * max(len(indices) - 1, 1))
        cross_mean = crossing_weight / max(len(indices) * (n_events - len(indices)), 1)
        ratio = cross_mean / within_mean if within_mean > 0 else None
        block_counts = Counter(token for index in indices for token in token_sets[index])
        features = [
            {
                "token_hash": f"{stable_hash(token, config.context_salt):016x}",
                "information_gain": _information_gain(n_events, len(indices), global_counts[token], present),
                "presence_count": present,
            }
            for token, present in block_counts.items()
        ]
        features.sort(key=lambda item: (-item["information_gain"], item["token_hash"]))
        signatures.append(HoSig(
            block_id=f"{batch_id}:{block_number}", feature_space_id=config.feature_space_id,
            count=len(indices), prototype=rff[indices].mean(axis=0).astype(np.float32),
            time_histogram=histogram, cms=cms.table, hll_registers=hll.registers,
            distinct_context_estimate=hll.estimate(), boundary_ratio=ratio,
            top_features=features[:config.top_features],
        ))
    return signatures


def save_signatures(path, signatures):
    with open(path, "w", encoding="utf-8") as handle:
        for signature in signatures:
            handle.write(json.dumps(signature.to_dict(), ensure_ascii=False, allow_nan=False) + "\n")


def load_signatures(path):
    with open(path, encoding="utf-8") as handle:
        return [HoSig.from_dict(json.loads(line)) for line in handle if line.strip()]
