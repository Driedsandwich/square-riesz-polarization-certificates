#!/usr/bin/env python3
"""Check a fresh replay directory against the sources it claims to have run.

``verify_all.py`` writes its own summary, so a summary that says 88/88 proves
nothing on its own. This program re-derives the same conclusion from the files.

Four representations of the same run exist — ``summary.json``, ``summary.csv``,
the per-job JSON files and the logs — and none of them is trusted to vouch for
another. Every one is compared against the others *and* against the certifier
sources:

* every certifier named by a record has its SHA-256 recomputed;
* every stdout/stderr pair is re-classified through the shared success
  contract, and the verdict must equal what the record claims;
* every stdout that claims a certification is checked against the certifier
  that produced it — target, split, leaf and depth counts, minimum leaf bound
  and upper witness value. A stdout file whose entire content is
  ``status: CERTIFIED`` passed every other check in this list;
* the declared ``selection`` must match the configuration set it names, and the
  recorded Git provenance must be a real commit — optionally the expected one;
* every CSV cell is compared with the corresponding JSON value through the
  shared ``csv_text`` renderer, field by field — checking only the key columns
  let a row claim ``certified=False`` with a zeroed script hash and still pass;
* the aggregates are recomputed from the individual records;
* the directory must hold exactly the files the run should have produced.

Usage:
    python scripts/validate_replay_output.py <replay-output-dir> [--expect-all]

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    HEX64,
    METHODS,
    ROOT,
    SELECTION_CONFIGURATIONS,
    UTC_TIMESTAMP,
    canonical_log_name,
    certifier_relpath,
    csv_text,
    is_strict_int,
    is_strict_number,
    load_json_strict,
    log_stem,
)
from verifier_runner import classify, proof_output_problems, sha256_file  # noqa: E402

#: A full Git object name, lowercase. Abbreviated or upper-case forms are
#: rejected: this field is meant to identify one commit unambiguously.
HEX40 = re.compile(r"^[0-9a-f]{40}$")

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SUMMARY_FIELDS: tuple[str, ...] = (
    "generated_at_utc",
    "selection",
    "expected_configurations",
    "expected_methods",
    "expected_keys",
    "verifier_count",
    "certified_count",
    "failed_count",
    "timed_out_count",
    "worker_count",
    "timeout_seconds",
    "python_version",
    "python_version_full",
    "python_implementation",
    "platform",
    "machine",
    "source_git_commit",
    "source_git_dirty",
    "results",
)

RECORD_FIELDS: tuple[str, ...] = (
    "n",
    "method",
    "repo_relative_script",
    "script_sha256",
    "return_code",
    "timed_out",
    "status",
    "certified",
    "failure_reason",
    "elapsed_seconds",
    "stdout_log",
    "stderr_log",
)

SELECTIONS = tuple(sorted(SELECTION_CONFIGURATIONS))


def parse_utc_timestamp(text: str) -> datetime | None:
    """Parse a UTC stamp and require the canonical spelling to round-trip.

    A regular expression accepts ``2026-99-99T99:99:99Z``. Parsing it as a real
    date does not, and re-rendering the parsed value catches any spelling that
    happens to parse but is not the form this repository writes.
    """
    try:
        parsed = datetime.strptime(text, UTC_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.strftime(UTC_FORMAT) == text else None


def repository_head(root: Path = ROOT) -> str | None:
    """The current commit of the source tree, or None when it cannot be read."""
    if not (root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    commit = completed.stdout.strip()
    return commit if HEX40.fullmatch(commit) else None


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.counts: dict[str, int] = {}

    def fail(self, message: str) -> None:
        self.problems.append(message)

    def count(self, key: str, value: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + value


def check_summary_schema(report: Report, summary: dict) -> bool:
    """Exact field set and exact types. Returns False if it cannot continue."""
    missing = sorted(set(SUMMARY_FIELDS) - set(summary))
    unexpected = sorted(set(summary) - set(SUMMARY_FIELDS))
    if missing or unexpected:
        report.fail(f"summary.json field set mismatch: missing={missing} unexpected={unexpected}")
        return False

    def require(condition: bool, message: str) -> None:
        if not condition:
            report.fail(f"summary.json {message}")

    stamp = summary["generated_at_utc"]
    require(isinstance(stamp, str) and bool(UTC_TIMESTAMP.fullmatch(stamp))
            and parse_utc_timestamp(stamp) is not None,
            f"generated_at_utc is not a real UTC timestamp: {stamp!r}")
    require(summary["selection"] in SELECTIONS, f"selection is {summary['selection']!r}, expected one of {SELECTIONS}")

    configurations = summary["expected_configurations"]
    require(isinstance(configurations, list) and all(is_strict_int(n) for n in configurations),
            "expected_configurations must be a list of integers (bool not allowed)")
    if isinstance(configurations, list) and all(is_strict_int(n) for n in configurations):
        require(len(set(configurations)) == len(configurations), "expected_configurations contains duplicates")
        require(configurations == sorted(configurations), "expected_configurations is not in ascending order")
        # The selection names a fixed configuration list. Without this, relabelling
        # a five-configuration quick run as "all" — or the reverse — was accepted.
        declared = SELECTION_CONFIGURATIONS.get(summary["selection"])
        if declared is not None:
            require(configurations == list(declared),
                    f"selection is {summary['selection']!r}, which means configurations {list(declared)}, "
                    f"but expected_configurations is {configurations}")

    require(summary["expected_methods"] == list(METHODS),
            f"expected_methods is {summary['expected_methods']!r}, expected {list(METHODS)}")

    keys = summary["expected_keys"]
    well_formed = isinstance(keys, list) and all(
        isinstance(k, list) and len(k) == 2 and is_strict_int(k[0]) and isinstance(k[1], str) for k in keys
    )
    require(well_formed, "expected_keys must be a list of [int, str] pairs")
    if well_formed:
        pairs = [(k[0], k[1]) for k in keys]
        require(len(set(pairs)) == len(pairs), "expected_keys contains duplicate pairs")
        if isinstance(configurations, list) and all(is_strict_int(n) for n in configurations):
            product = {(n, method) for n in configurations for method in METHODS}
            require(set(pairs) == product,
                    "expected_keys is not exactly expected_configurations x expected_methods: "
                    f"missing={sorted(product - set(pairs))} unexpected={sorted(set(pairs) - product)}")

    for field in ("verifier_count", "certified_count", "failed_count", "timed_out_count"):
        require(is_strict_int(summary[field]) and summary[field] >= 0,
                f"{field} is {summary[field]!r}, expected a non-negative integer (bool not allowed)")
    require(is_strict_int(summary["worker_count"]) and summary["worker_count"] >= 1,
            f"worker_count is {summary['worker_count']!r}, expected an integer >= 1")
    require(is_strict_int(summary["timeout_seconds"]) and summary["timeout_seconds"] > 0,
            f"timeout_seconds is {summary['timeout_seconds']!r}, expected an integer > 0")

    for field in ("python_version", "python_version_full", "python_implementation", "platform", "machine"):
        require(isinstance(summary[field], str) and summary[field] != "", f"{field} must be a non-empty string")

    commit = summary["source_git_commit"]
    require(commit is None or (isinstance(commit, str) and bool(HEX40.fullmatch(commit))),
            f"source_git_commit is {commit!r}, expected null or 40 lowercase hex characters")
    require(summary["source_git_dirty"] is None or isinstance(summary["source_git_dirty"], bool),
            "source_git_dirty must be a boolean or null")
    require(isinstance(summary["results"], list), "results must be a list")

    return isinstance(summary["results"], list)


def check_provenance(
    report: Report,
    summary: dict,
    *,
    expect_all: bool,
    expect_source_commit: str | None,
    expect_source_clean: bool,
) -> None:
    """Check what the run says about the source tree it ran against.

    Local evidence is produced from an uncommitted working tree, so a dirty
    source is normal and only CI is asked to prove otherwise. What is never
    acceptable is a commit that does not exist or a selection that does not
    match the work actually done.
    """
    if expect_all and summary.get("selection") != "all":
        report.fail(f"--expect-all requires selection 'all', found {summary.get('selection')!r}")

    commit = summary.get("source_git_commit")
    if expect_source_commit is not None:
        if not HEX40.fullmatch(expect_source_commit):
            report.fail(f"--expect-source-commit is not a full commit id: {expect_source_commit!r}")
        elif commit != expect_source_commit:
            report.fail(f"source_git_commit is {commit!r}, expected {expect_source_commit!r}")
        else:
            report.count("source_commit_verified")
    elif isinstance(commit, str):
        head = repository_head()
        if head is None:
            report.count("source_commit_unverifiable")
        elif head != commit:
            report.fail(
                f"source_git_commit is {commit!r} but this source tree is at {head!r}; "
                "the replay was produced from different sources"
            )
        else:
            report.count("source_commit_verified")

    if expect_source_clean:
        if summary.get("source_git_dirty") is not False:
            report.fail(
                f"--expect-source-clean requires source_git_dirty=false, "
                f"found {summary.get('source_git_dirty')!r}"
            )
        else:
            report.count("source_clean_verified")


def check_record_schema(report: Report, index: int, record) -> "tuple[int, str] | None":
    if not isinstance(record, dict):
        report.fail(f"results[{index}] is {type(record).__name__}, expected an object")
        return None
    missing = sorted(set(RECORD_FIELDS) - set(record))
    unexpected = sorted(set(record) - set(RECORD_FIELDS))
    if missing or unexpected:
        report.fail(f"results[{index}] field set mismatch: missing={missing} unexpected={unexpected}")
        return None

    problems_before = len(report.problems)

    def require(condition: bool, message: str) -> None:
        if not condition:
            report.fail(f"results[{index}] {message}")

    require(is_strict_int(record["n"]), f"n is {record['n']!r}, expected an integer (bool not allowed)")
    require(isinstance(record["method"], str) and record["method"] in METHODS,
            f"method is {record['method']!r}, expected one of {METHODS}")
    if len(report.problems) != problems_before:
        return None

    n, method = record["n"], record["method"]
    require(record["repo_relative_script"] == certifier_relpath(n, method),
            f"repo_relative_script is {record['repo_relative_script']!r}, expected {certifier_relpath(n, method)!r}")
    require(isinstance(record["script_sha256"], str) and bool(HEX64.fullmatch(record["script_sha256"])),
            f"script_sha256 is not 64 lowercase hex characters: {record['script_sha256']!r}")
    require(is_strict_int(record["return_code"]), f"return_code is {record['return_code']!r}, expected an integer")
    require(isinstance(record["timed_out"], bool), f"timed_out is {record['timed_out']!r}, expected a boolean")
    require(isinstance(record["certified"], bool), f"certified is {record['certified']!r}, expected a boolean")
    require(record["status"] is None or isinstance(record["status"], str), "status must be a string or null")
    require(record["failure_reason"] is None or isinstance(record["failure_reason"], str),
            "failure_reason must be a string or null")
    require(is_strict_number(record["elapsed_seconds"]) and record["elapsed_seconds"] >= 0,
            f"elapsed_seconds is {record['elapsed_seconds']!r}, expected a finite non-negative number")
    for field, stream in (("stdout_log", "stdout"), ("stderr_log", "stderr")):
        expected = canonical_log_name(n, method, stream)
        require(record[field] == expected, f"{field} is {record[field]!r}, expected {expected!r}")

    return (n, method)


def validate(
    directory: Path,
    expect_all: bool,
    *,
    expect_source_commit: str | None = None,
    expect_source_clean: bool = False,
) -> Report:
    report = Report()

    summary_path = directory / "summary.json"
    if not summary_path.is_file():
        report.fail(f"{directory}: no summary.json")
        return report

    summary = load_json_strict(summary_path, dict)
    if not check_summary_schema(report, summary):
        return report
    report.count("summary_schema_verified")
    check_provenance(
        report,
        summary,
        expect_all=expect_all,
        expect_source_commit=expect_source_commit,
        expect_source_clean=expect_source_clean,
    )

    records = summary["results"]
    expected_keys = {(int(n), str(method)) for n, method in summary["expected_keys"]}
    if expect_all:
        required = {(n, method) for n in EXPECTED_NS for method in METHODS}
        if expected_keys != required:
            report.fail(
                "summary.json expected_keys is not the full published set: "
                f"missing={sorted(required - expected_keys)} unexpected={sorted(expected_keys - required)}"
            )

    seen: dict[tuple[int, str], dict] = {}
    expected_files = {"summary.json", "summary.csv"}

    for index, record in enumerate(records):
        key = check_record_schema(report, index, record)
        if key is None:
            continue
        if key not in expected_keys:
            report.fail(f"results[{index}]: unexpected key {key}")
            continue
        if key in seen:
            report.fail(f"results[{index}]: duplicate key {key}")
            continue
        seen[key] = record
        report.count("record_schema_verified")

        n, method = key
        script = ROOT / record["repo_relative_script"]
        if not script.is_file():
            report.fail(f"{key}: recorded script does not exist: {record['repo_relative_script']}")
        elif sha256_file(script) != record["script_sha256"]:
            report.fail(f"{key}: recorded script_sha256 does not match {record['repo_relative_script']}")
        else:
            report.count("script_hashes_verified")

        stem = log_stem(n, method)
        expected_files.update({record["stdout_log"], record["stderr_log"], f"{stem}.json"})

        stdout_path = directory / record["stdout_log"]
        stderr_path = directory / record["stderr_log"]
        if not stdout_path.is_file() or not stderr_path.is_file():
            report.fail(f"{key}: missing log files")
            continue

        stdout_text = stdout_path.read_text(encoding="utf-8")
        status, certified, reason = classify(
            int(record["return_code"]),
            bool(record["timed_out"]),
            stdout_text,
            stderr_path.read_text(encoding="utf-8"),
        )
        if certified:
            problems = proof_output_problems(script, stdout_text, f"{key} {record['stdout_log']}")
            if problems:
                certified = False
                reason = "; ".join(problems)
        if status != record["status"] or certified != record["certified"]:
            report.fail(
                f"{key}: logs classify as status={status!r} certified={certified} "
                f"but the record says status={record['status']!r} certified={record['certified']}"
                + (f" ({reason})" if reason else "")
            )
        elif reason != record["failure_reason"]:
            report.fail(f"{key}: failure_reason {record['failure_reason']!r} does not match {reason!r}")
        else:
            report.count("logs_reclassified")
            if certified:
                report.count("proof_output_verified")

        per_job = directory / f"{stem}.json"
        if not per_job.is_file():
            report.fail(f"{key}: missing per-job metadata {stem}.json")
        else:
            payload = load_json_strict(per_job, dict)
            differing = sorted(field for field in RECORD_FIELDS if payload.get(field) != record.get(field))
            if set(payload) != set(RECORD_FIELDS):
                report.fail(f"{key}: per-job metadata field set mismatch")
            elif differing:
                report.fail(f"{key}: per-job metadata differs from the summary record in {differing}")
            else:
                report.count("per_job_metadata_verified")

    missing = sorted(expected_keys - set(seen))
    if missing:
        report.fail(f"missing records: {missing}")

    recomputed_certified = sum(1 for record in records if record.get("certified") is True)
    recomputed_timeouts = sum(1 for record in records if record.get("timed_out") is True)
    for field, recomputed in (
        ("verifier_count", len(records)),
        ("certified_count", recomputed_certified),
        ("failed_count", len(records) - recomputed_certified),
        ("timed_out_count", recomputed_timeouts),
    ):
        if summary[field] != recomputed:
            report.fail(f"summary {field} is {summary[field]!r} but the records give {recomputed}")
        else:
            report.count("aggregates_verified")

    check_summary_csv(report, directory, seen)

    actual_files = {entry.name for entry in directory.iterdir() if entry.is_file()}
    unexpected = sorted(actual_files - expected_files)
    absent = sorted(expected_files - actual_files)
    if unexpected:
        report.fail(f"unexpected files in the replay directory: {unexpected}")
    if absent:
        report.fail(f"missing files in the replay directory: {absent}")
    directories = sorted(entry.name for entry in directory.iterdir() if entry.is_dir())
    if directories:
        report.fail(f"unexpected subdirectories in the replay directory: {directories}")

    report.count("records_checked", len(seen))
    return report


def check_summary_csv(report: Report, directory: Path, records: dict[tuple[int, str], dict]) -> None:
    """Compare the CSV with the JSON records cell by cell.

    Rows must also be in the canonical ``(n, method)`` order that
    ``verify_all.py`` writes. Requiring the order rather than sorting here keeps
    a reordered file from being silently accepted as equivalent.
    """
    csv_path = directory / "summary.csv"
    if not csv_path.is_file():
        report.fail("no summary.csv")
        return

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        rows = list(reader)

    if header != list(RECORD_FIELDS):
        report.fail(f"summary.csv header is {header}, expected {list(RECORD_FIELDS)}")
        return

    csv_keys: list[tuple[int, str]] = []
    for position, row in enumerate(rows):
        try:
            csv_keys.append((int(row["n"]), row["method"]))
        except (TypeError, ValueError):
            report.fail(f"summary.csv row {position + 1}: n is not an integer: {row['n']!r}")
            return

    if len(rows) != len(records):
        report.fail(f"summary.csv has {len(rows)} rows, summary.json has {len(records)} records")
    duplicates = sorted({key for key in csv_keys if csv_keys.count(key) > 1})
    if duplicates:
        report.fail(f"summary.csv contains duplicate (n, method) keys: {duplicates}")
    unexpected = sorted(set(csv_keys) - set(records))
    absent = sorted(set(records) - set(csv_keys))
    if unexpected:
        report.fail(f"summary.csv has rows that are not in summary.json: {unexpected}")
    if absent:
        report.fail(f"summary.csv is missing rows present in summary.json: {absent}")
    if csv_keys != sorted(records):
        report.fail("summary.csv rows are not in the canonical (n, method) order")

    for row, key in zip(rows, csv_keys):
        record = records.get(key)
        if record is None:
            continue
        differing = [
            f"{field}: csv {row[field]!r} != json {csv_text(record[field])!r}"
            for field in RECORD_FIELDS
            if row[field] != csv_text(record[field])
        ]
        if differing:
            report.fail(f"summary.csv {key}: {differing}")
        else:
            report.count("csv_rows_verified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expect-all", action="store_true", help="require the full 44-configuration set")
    parser.add_argument(
        "--expect-source-commit",
        metavar="SHA",
        help="require the replay to name this 40-character source commit",
    )
    parser.add_argument(
        "--expect-source-clean",
        action="store_true",
        help="require the source tree to have been clean; for CI, not for local evidence",
    )
    arguments = parser.parse_args()

    if not arguments.directory.is_dir():
        print(f"not a directory: {arguments.directory}", file=sys.stderr)
        return 2

    report = validate(
        arguments.directory,
        arguments.expect_all,
        expect_source_commit=arguments.expect_source_commit,
        expect_source_clean=arguments.expect_source_clean,
    )
    print(" ".join(f"{key}={value}" for key, value in sorted(report.counts.items())))
    print(f"problems={len(report.problems)}")
    if report.problems:
        print("\n".join(f"  - {problem}" for problem in report.problems))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
