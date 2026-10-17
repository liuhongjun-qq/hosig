import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def metric_mean(records, metric):
    values = [record[metric] for record in records if record.get(metric) is not None and math.isfinite(record[metric])]
    return mean(values) if values else None


def stream_summary(report):
    batches = report["batches"]
    scores = [batch["metrics"] for batch in batches]
    mixed = [score for score in scores if score["truth_class_count"] > 1]
    return {
        "total_events": report["total_events"], "total_blocks": report["total_blocks"],
        "batches": len(batches), "mixed_label_batches": len(mixed),
        "graph_components": sum(batch["diagnostics"]["n_components"] for batch in batches),
        "positive_gain_candidates": sum(batch["diagnostics"]["positive_gain_candidates"] for batch in batches),
        "ari_mean_all_batches": metric_mean(scores, "ari"),
        "ari_mean_mixed_label_batches": metric_mean(mixed, "ari"),
        "algorithm_stage_seconds": sum(batch["diagnostics"]["timings_seconds"]["total"] for batch in batches),
        "warnings": [warning for batch in batches for warning in batch["diagnostics"]["warnings"]],
    }


def summarize(events_path, results_root):
    events_path, results_root = Path(events_path), Path(results_root)
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not events:
        raise ValueError("Events file is empty")
    with events_path.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    reports = {name: load_json(results_root / name / "report.json") for name in ("default", "exploratory")}
    benchmark = load_json(results_root / "benchmark" / "benchmark.json")
    for report in list(reports.values()) + [benchmark]:
        if report["input"]["sha256"] != checksum:
            raise ValueError("Reports do not match the events file SHA256")
    dataset = load_json(events_path.with_suffix(".metadata.json"))
    if dataset["output_sha256"] != checksum:
        raise ValueError("Dataset metadata does not match the events file SHA256")
    groups = []
    for top_k in sorted({record["top_k"] for record in benchmark["records"]}):
        for method in ("hosig", "hdbscan", "spectral", "louvain"):
            records = [record for record in benchmark["records"] if record["top_k"] == top_k and record["method"] == method]
            mixed = [record for record in records if record["truth_class_count"] > 1]
            groups.append({
                "top_k": top_k, "method": method, "test_batches": len(records),
                "test_events": sum(record["n_events"] for record in records),
                "mixed_label_batches": len(mixed), "ari_mean_all": metric_mean(records, "ari"),
                "ari_mean_mixed": metric_mean(mixed, "ari"), "nmi_mean_mixed": metric_mean(mixed, "nmi"),
                "ch_mean": metric_mean(records, "ch"), "silhouette_mean": metric_mean(records, "silhouette"),
                "modularity_mean": metric_mean(records, "modularity"), "noise_rate_mean": metric_mean(records, "noise_rate"),
                "undefined_ch_batches": sum(record["ch"] is None for record in records),
                "warning_batches": sum(bool(record["warnings"]) for record in records),
            })
    summary = {
        "dataset": dataset, "full_stream": {name: stream_summary(report) for name, report in reports.items()},
        "benchmark_records": len(benchmark["records"]), "baseline_selections": len(benchmark["baseline_selection"]),
        "validation_prefix_events": benchmark["baseline_selection"][0]["validation_prefix_events"],
        "validation_events_used": benchmark["baseline_selection"][0]["validation_events_used"],
        "entity_protocol": benchmark["entity_protocol"], "benchmark_by_top_k": groups,
        "interpretation": "Behavior-label evaluation only; metadata proxy, one capture, offline replay. Not campaign or paper-result reproduction. Means are unweighted per-batch; full-stream and held-out results are separate.",
    }
    results_root.mkdir(parents=True, exist_ok=True)
    (results_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with (results_root / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(groups[0]))
        writer.writeheader()
        writer.writerows(groups)
    hours = (np.array([event["timestamp"] for event in events]) - events[0]["timestamp"]) / 3600
    labels = sorted({event["label"] for event in events})
    label_ids = {label: index for index, label in enumerate(labels)}
    figure, axes = plt.subplots(2, 2, figsize=(14, 8))
    axes[0, 0].scatter(hours, [label_ids[event["label"]] for event in events], s=2, alpha=0.4)
    axes[0, 0].set_yticks(range(len(labels)), labels)
    axes[0, 0].set_title("Dataset behavior labels (evaluation only)")
    for name, report in reports.items():
        batches = report["batches"]
        offsets = np.cumsum([0] + [batch["diagnostics"]["n_events"] for batch in batches[:-1]])
        positions = hours[offsets]
        axes[0, 1].plot(positions, [batch["diagnostics"]["n_blocks"] for batch in batches], marker=".", label=name)
        if name == "default":
            axes[0, 1].plot(positions, [batch["diagnostics"]["n_components"] for batch in batches], linestyle="--", label="default components")
            max_costs = [max(load_json(results_root / name / "local" / f"batch_{batch['batch_id']:04d}" / "assignments.json")["costs"]) for batch in batches]
            axes[1, 0].plot(positions, max_costs, label="max C(b)")
            axes[1, 0].plot(positions, [batch["diagnostics"]["segmentation_penalty"] for batch in batches], label="penalty")
        mixed_indices = [index for index, batch in enumerate(batches) if batch["metrics"]["truth_class_count"] > 1]
        axes[1, 1].plot(positions[mixed_indices], [batches[index]["metrics"]["ari"] for index in mixed_indices], marker=".", label=name)
    axes[0, 1].set_title("Block count per micro-batch (not cumulative campaigns)")
    axes[1, 0].set_title("Default boundary costs vs penalty")
    axes[1, 1].set_title("ARI on mixed-label full-stream batches only")
    axes[1, 1].set_ylabel("ARI")
    for axis in axes.flat:
        axis.set_xlabel("Hours since first connection")
    for axis in (axes[0, 1], axes[1, 0], axes[1, 1]):
        axis.legend()
    figure.tight_layout()
    figure.savefig(results_root / "stream_overview.png", dpi=150)
    plt.close(figure)
    print(f"Summary: {results_root / 'summary.json'}")
    print(f"Overview: {results_root / 'stream_overview.png'}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Summarize verified IoT-23 full-stream and held-out runs")
    parser.add_argument("--events", required=True)
    parser.add_argument("--results-root", required=True)
    args = parser.parse_args()
    summarize(args.events, args.results_root)


if __name__ == "__main__":
    main()
