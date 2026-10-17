import json

import pytest

from hosig import Config, HoSigAlign
from hosig.cli import main
from hosig.data import read_events
from hosig.iot23 import convert_iot23, read_iot23_events, read_zeek_rows
from scripts.summarize_iot23 import summarize


FIELDS = [
    "ts", "uid", "id.orig_h", "id.orig_p", "id.resp_h", "id.resp_p", "proto", "service",
    "duration", "orig_bytes", "conn_state", "tunnel_parents", "label", "det_label",
]


def write_log(path, records=None, fields=None):
    fields = fields or FIELDS
    records = records or [
        ["30", "u0", "192.168.1.195", "12345", "10.0.0.1", "80", "tcp", "http", "999999", "111111", "SF", "-", "Benign", "-"],
        ["10", "u1", "192.168.1.195", "12346", "10.0.0.2", "23", "tcp", "-", "888888", "222222", "S0", "-", "Malicious", "C&C"],
        ["10", "u2", "192.168.1.195", "12347", "10.0.0.3", "23", "tcp", "-", "777777", "333333", "S0", "-", "Malicious", "DDoS"],
    ]
    path.write_text("#separator \\x09\n#unset_field\t-\n#empty_field\t(empty)\n#fields\t" + "\t".join(fields) + "\n#types\t" + "\t".join(["string"] * len(fields)) + "\n" + "\n".join("\t".join(record) for record in records) + "\n#close\t2026-01-01\n", encoding="utf-8")


def test_converter_stable_sorts_and_reports_all_labels(tmp_path):
    source, output = tmp_path / "conn.log.labeled", tmp_path / "events.jsonl"
    write_log(source)
    metadata = convert_iot23(source, output, scenario="capture")
    events = list(read_events(output))
    assert [event.timestamp for event in events] == [10, 10, 30]
    assert [event.event_id for event in events] == ["capture:u1", "capture:u2", "capture:u0"]
    assert [event.label for event in events] == ["C&C", "DDoS", "Benign"]
    assert metadata["source_timestamp_inversions"] == 1
    assert metadata["converted_label_counts"] == {"Benign": 1, "C&C": 1, "DDoS": 1}
    assert metadata["timestamps_real"] and not metadata["payload_real"]
    assert not metadata["alert_arrival_times_available"]
    assert output.with_suffix(".metadata.json").exists()


@pytest.mark.parametrize("label_field", ["det_label", "detailed-label", "detailed_label"])
def test_detailed_label_aliases_and_binary_mode(tmp_path, label_field):
    source = tmp_path / "conn.log.labeled"
    write_log(source, fields=FIELDS[:-1] + [label_field])
    assert [event.label for event in read_iot23_events(source)] == ["Benign", "C&C", "DDoS"]
    assert [event.label for event in read_iot23_events(source, "binary")] == ["Benign", "Malicious", "Malicious"]


def test_labels_and_temporal_fields_never_enter_proxy(tmp_path):
    source = tmp_path / "conn.log.labeled"
    write_log(source)
    first = list(read_iot23_events(source))
    text = source.read_text().replace("C&C", "secret_ground_truth").replace("DDoS", "different_truth").replace("999999", "987654321")
    source.write_text(text)
    second = list(read_iot23_events(source))
    for before, after in zip(first, second):
        assert before.payload == after.payload and before.context == after.context
        assert before.src_ip == after.src_ip
    config = Config(embedding_dim=16, vocabulary_size=64, rff_dim=32, trees=4, leaf_size=2)
    before = HoSigAlign(config).process_batch(first)
    after = HoSigAlign(config).process_batch(second)
    assert [signature.to_dict() for signature in before.signatures] == [signature.to_dict() for signature in after.signatures]


def test_space_joined_iot23_label_tail(tmp_path):
    source = tmp_path / "conn.log.labeled"
    write_log(source, fields=FIELDS[:-1] + ["detailed-label"])
    source.write_text(source.read_text().replace("\t-\tMalicious\tC&C", "\t-   Malicious   C&C"))
    assert list(read_iot23_events(source))[1].label == "C&C"


def test_limit_applied_after_chronological_sort_and_source_order_option(tmp_path):
    source, output = tmp_path / "conn.log.labeled", tmp_path / "events.jsonl"
    write_log(source)
    metadata = convert_iot23(source, output, limit=1)
    assert list(read_events(output))[0].timestamp == 10
    assert metadata["source_records"] == 3 and metadata["converted_records"] == 1
    convert_iot23(source, output, order="source")
    assert list(read_events(output))[0].timestamp == 30


def test_missing_header_and_bad_columns_fail_explicitly(tmp_path):
    source = tmp_path / "conn.log.labeled"
    source.write_text("10\tu1\n")
    with pytest.raises(ValueError, match="Missing #fields"):
        list(read_zeek_rows(source))
    write_log(source)
    source.write_text(source.read_text().replace("\tSF\t-\tBenign\t-", "\tSF\t-\tBenign"))
    with pytest.raises(ValueError, match="field count"):
        list(read_iot23_events(source))


def test_invalid_ip_and_input_output_collision(tmp_path):
    source = tmp_path / "conn.log.labeled"
    write_log(source)
    source.write_text(source.read_text().replace("192.168.1.195", "invalid-ip"))
    with pytest.raises(ValueError, match="Invalid IoT-23"):
        list(read_iot23_events(source))
    with pytest.raises(ValueError, match="different files"):
        convert_iot23(source, source)


def test_escaped_zeek_values_are_decoded(tmp_path):
    source = tmp_path / "conn.log.labeled"
    write_log(source)
    source.write_text(source.read_text().replace("\thttp\t", "\thttp\\x2fproxy\t"))
    assert list(read_iot23_events(source))[0].context["service"] == "http/proxy"


def test_cli_conversion_and_provenance_validation(tmp_path):
    source, output = tmp_path / "conn.log.labeled", tmp_path / "events.jsonl"
    write_log(source)
    assert main(["convert-iot23", "--input", str(source), "--output", str(output), "--scenario", "test"]) == 0
    results = tmp_path / "results"
    assert main(["run", "--input", str(output), "--output", str(results)]) == 0
    report = json.loads((results / "report.json").read_text())
    assert report["input"]["provenance"]["dataset"] == "IoT-23"
    assert report["input"]["payload_real"] is False
    assert report["input"]["temporal_claims_valid"] is False
    output.write_text(output.read_text() + "\n")
    assert main(["run", "--input", str(output), "--output", str(tmp_path / "invalid")]) == 1
    assert not (tmp_path / "invalid").exists()


def test_experiment_summary_checks_hashes_and_creates_outputs(tmp_path):
    source, output = tmp_path / "conn.log.labeled", tmp_path / "events.jsonl"
    template = ["10", "u0", "192.168.1.195", "12345", "10.0.0.1", "80", "tcp", "http", "1", "100", "SF", "-", "Benign", "-"]
    rows = []
    for index in range(12):
        row = list(template)
        row[0], row[1] = str(index), f"u{index}"
        if index % 2:
            row[-2:], row[5] = ["Malicious", "C&C"], "23"
        rows.append(row)
    write_log(source, records=rows)
    convert_iot23(source, output)
    config = Config(embedding_dim=16, vocabulary_size=64, rff_dim=32, trees=4, leaf_size=2, batch_size=128)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config.to_dict()))
    root = tmp_path / "results"
    for name in ("default", "exploratory"):
        assert main(["run", "--input", str(output), "--config", str(config_path), "--output", str(root / name)]) == 0
    assert main(["benchmark", "--input", str(output), "--config", str(config_path), "--top-k-grid", "4", "--clients", "1", "--output", str(root / "benchmark")]) == 0
    summary = summarize(output, root)
    assert summary["benchmark_records"] == 4
    assert summary["full_stream"]["default"]["total_events"] == 12
    assert (root / "summary.csv").exists() and (root / "stream_overview.png").exists()
    report_path = root / "default" / "report.json"
    report = json.loads(report_path.read_text())
    report["input"]["sha256"] = "invalid"
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="SHA256"):
        summarize(output, root)
