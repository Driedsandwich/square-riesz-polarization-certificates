#!/usr/bin/env python3
"""Check that every representation of the corpus says the same thing.

``scripts/check_release.py`` counts files and rows. This program compares
meaning: the two certifiers of a configuration against each other and against
the published coordinates, the CSV against the JSON field by field, the
published upper bounds against exact rational arithmetic, and the stored replay
evidence against the files it claims to describe.

Numbers are compared as exact rationals or as strings, never as floats: two
87-digit decimals that differ in the last place are the same float.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True

from certificate_lib import (  # noqa: E402  (path bootstrap above)
    EXPECTED_NS,
    HEX64,
    METHODS,
    REPLAY_RECORD_FIELDS,
    RESULT_FIELDS,
    ROOT,
    canonical_log_name,
    certifier_decimal_string,
    is_strict_int,
    is_strict_number,
    log_stem,
    parse_certifier_stdout,
    certifier_relpath,
    configuration_relpath,
    configuration_source_relpath,
    decimal_places,
    exact_potential,
    exact_square_symmetries,
    extract_certifier_facts,
    format_exact_decimal,
    load_full_replay,
    load_json_strict,
    load_results_csv,
    load_results_json,
    load_results_metadata,
    minimum_separation_squared,
    parse_canonical_integer,
    parse_exact_decimal,
    read_coordinates_csv,
    read_coordinates_source,
    validate_proof_output,
    validate_witness_point,
)
from verifier_runner import declared_statuses, forbidden_tokens_in  # noqa: E402

SAVED_REPLAYS = ROOT / "evidence" / "saved-replays"
FULL_REPLAY_DIR = ROOT / "evidence" / "full-cleanroom-replay"

#: Result-table columns that carry a proof measurement and must therefore be
#: canonical non-negative integers, not merely non-empty strings.
COUNT_FIELDS: tuple[str, ...] = (
    "spectral_splits",
    "spectral_maximum_depth",
    "componentwise_splits",
    "componentwise_maximum_depth",
)


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.counts: dict[str, int] = {}

    def fail(self, message: str) -> None:
        self.problems.append(message)

    def count(self, key: str, value: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + value


def strict_status(text: str) -> str | None:
    """Return the single declared status, or None if the output is not strict.

    Shares its notion of a status declaration and of a forbidden token with
    ``verifier_runner``, so a stored log and a live run are judged by the same
    contract.
    """
    statuses = declared_statuses(text)
    if len(statuses) != 1:
        return None
    tokens = forbidden_tokens_in(text)
    if tokens and statuses[0] not in tokens:
        return None  # a contradictory claim elsewhere in the output
    return statuses[0]


# --------------------------------------------------------------------------


def check_configuration_set(report: Report) -> None:
    expected = set(EXPECTED_NS)

    certifier_dirs = {int(path.name[1:]) for path in (ROOT / "certifiers").glob("n*") if path.is_dir()}
    config_dirs = {int(path.name[1:]) for path in (ROOT / "data" / "configurations").glob("n*") if path.is_dir()}
    csv_rows = load_results_csv(require_expected_set=False)
    json_rows = load_results_json()
    metadata = load_results_metadata()

    csv_ns = [int(row["n"]) for row in csv_rows]
    json_ns = [int(row["n"]) for row in json_rows]

    for label, observed in (
        ("certifiers/", certifier_dirs),
        ("data/configurations/", config_dirs),
        ("certified-results.csv", set(csv_ns)),
        ("certified-results.json", set(json_ns)),
        ("results-metadata.json", set(metadata)),
    ):
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        if missing:
            report.fail(f"{label}: missing configurations {missing}")
        if unexpected:
            report.fail(f"{label}: unexpected configurations {unexpected}")

    if len(csv_ns) != len(set(csv_ns)):
        report.fail("certified-results.csv: duplicate n values")
    if len(json_ns) != len(set(json_ns)):
        report.fail("certified-results.json: duplicate n values")
    if csv_ns != sorted(csv_ns):
        report.fail("certified-results.csv: rows are not in ascending n order")
    if json_ns != csv_ns:
        report.fail("certified-results.json: row order differs from the CSV")
    report.count("configurations", len(expected))


def check_csv_json_agreement(report: Report) -> None:
    csv_rows = load_results_csv(require_expected_set=False)
    json_rows = load_results_json()

    if len(csv_rows) != len(json_rows):
        report.fail(f"record count differs: csv={len(csv_rows)} json={len(json_rows)}")
        return

    for csv_row, json_row in zip(csv_rows, json_rows):
        if not isinstance(json_row, dict):
            report.fail(f"json record for n={csv_row['n']} is not an object")
            continue
        if list(json_row.keys()) != list(RESULT_FIELDS):
            report.fail(f"n={csv_row['n']}: json key order/set differs from the schema")
            continue
        for field in RESULT_FIELDS:
            json_value = json_row[field]
            if not isinstance(json_value, str):
                report.fail(f"n={csv_row['n']} {field}: json value is {type(json_value).__name__}, expected str")
                continue
            if csv_row[field] != json_value:
                report.fail(f"n={csv_row['n']} {field}: csv {csv_row[field]!r} != json {json_value!r}")
            else:
                report.count("field_comparisons")

        # The four measurement columns come from the replay logs and must stay
        # readable as counts. Agreement between the CSV and the JSON says
        # nothing about that: `nonsense` agrees with `nonsense`.
        for field in COUNT_FIELDS:
            try:
                parse_canonical_integer(csv_row[field], f"n={csv_row['n']}", field)
            except ValueError as error:
                report.fail(str(error))
            else:
                report.count("count_fields_verified")


def check_configurations(report: Report) -> None:
    for n in EXPECTED_NS:
        csv_path = ROOT / configuration_relpath(n)
        source_path = ROOT / configuration_source_relpath(n)
        try:
            points = read_coordinates_csv(csv_path)
        except (ValueError, OSError) as error:
            report.fail(f"n={n}: {error}")
            continue

        if len(points) != n:
            report.fail(f"n={n}: configuration has {len(points)} points")
        if len(set(points)) != len(points):
            report.fail(f"n={n}: configuration contains duplicate points")
        outside = [index for index, (x, y) in enumerate(points, start=1) if not (0 <= x <= 1 and 0 <= y <= 1)]
        if outside:
            report.fail(f"n={n}: coordinates outside [0,1] at positions {outside}")

        try:
            source_points = read_coordinates_source(source_path, len(points))
        except (ValueError, OSError) as error:
            report.fail(f"n={n}: {error}")
        else:
            if source_points != points:
                report.fail(f"n={n}: coordinates-source.txt differs from coordinates.csv")
            else:
                report.count("configuration_representations_matched")
        report.count("configurations_checked")


def check_certifier_constants(report: Report) -> dict[int, object]:
    rows = {int(row["n"]): row for row in load_results_csv(require_expected_set=False)}
    facts_by_n: dict[int, object] = {}

    for n in EXPECTED_NS:
        try:
            facts = {
                method: extract_certifier_facts(ROOT / certifier_relpath(n, method), verify_entry_point=True)
                for method in METHODS
            }
        except Exception as error:  # noqa: BLE001 - surfaced verbatim as a problem
            report.fail(f"n={n}: could not read certifier constants: {error}")
            continue
        report.count("certifier_entry_points_verified", len(METHODS))

        spectral, componentwise = facts["spectral"], facts["componentwise"]
        if spectral.target != componentwise.target:
            report.fail(f"n={n}: TARGET differs between the two certifiers")
        if spectral.target_literal != componentwise.target_literal:
            report.fail(f"n={n}: TARGET literal differs: {spectral.target_literal!r} vs {componentwise.target_literal!r}")
        if spectral.lights != componentwise.lights:
            report.fail(f"n={n}: the two certifiers use different coordinates")
        if spectral.witness != componentwise.witness:
            report.fail(f"n={n}: the two certifiers use different upper witness points")

        try:
            points = read_coordinates_csv(ROOT / configuration_relpath(n))
        except (ValueError, OSError) as error:
            report.fail(f"n={n}: {error}")
            continue
        for method in METHODS:
            if facts[method].lights != points:
                report.fail(f"n={n} {method}: certifier coordinates differ from data/configurations")

        row = rows.get(n)
        if row is None:
            continue
        if row["certified_lower_bound"] != spectral.target_literal:
            report.fail(
                f"n={n}: result table lower bound {row['certified_lower_bound']!r} "
                f"!= certifier TARGET {spectral.target_literal!r}"
            )
        if parse_exact_decimal(row["certified_lower_bound"]) != spectral.target:
            report.fail(f"n={n}: result table lower bound is not the certifier TARGET value")
        for method in METHODS:
            expected_path = certifier_relpath(n, method)
            if row[f"{method}_verifier_path"] != expected_path:
                report.fail(f"n={n}: result table {method} path is {row[f'{method}_verifier_path']!r}")
            if not (ROOT / expected_path).is_file():
                report.fail(f"n={n}: {expected_path} does not exist")
        if row["configuration_path"] != configuration_relpath(n):
            report.fail(f"n={n}: result table configuration path is {row['configuration_path']!r}")
        if row["source_count"] != str(len(points)):
            report.fail(f"n={n}: source_count {row['source_count']!r} != {len(points)}")

        for method in METHODS:
            try:
                validate_witness_point(facts[method].witness, points, f"n={n} {method}")
            except Exception as error:  # noqa: BLE001 - surfaced verbatim as a problem
                report.fail(str(error))
            else:
                report.count("witness_points_in_unit_square", 1)

        # Named for what it measures: the module-level and helper assertions the
        # AST evaluator actually evaluated. The final assertions inside main()
        # are checked structurally by the entry-point check, not evaluated here.
        report.count(
            "certifier_module_assertions_evaluated",
            spectral.checked_assertions + componentwise.checked_assertions,
        )
        report.count("certifier_pairs_checked")
        facts_by_n[n] = spectral
        # The two certifiers of a configuration agree on the mathematics but not
        # on how many digits they print, so a log can only be checked against
        # the certifier that wrote it.
        for method in METHODS:
            _FACTS_BY_KEY[(n, method)] = facts[method]

    return facts_by_n


def check_upper_witness(report: Report, facts_by_n: dict[int, object]) -> None:
    rows = {int(row["n"]): row for row in load_results_csv(require_expected_set=False)}
    metadata = load_results_metadata()

    for n in EXPECTED_NS:
        facts = facts_by_n.get(n)
        row = rows.get(n)
        if facts is None or row is None:
            continue
        points = read_coordinates_csv(ROOT / configuration_relpath(n))
        exact = exact_potential(points, facts.witness)  # type: ignore[attr-defined]

        published_text = row["rigorous_upper_witness"]
        published = parse_exact_decimal(published_text)
        if published < exact:
            report.fail(
                f"n={n}: published upper witness is below the exact potential "
                f"(difference {float(exact - published):.6e}), so it is not an upper bound"
            )
        else:
            report.count("upper_bounds_verified")

        entry = metadata.get(n, {})
        if "upper_decimal_places" in entry and decimal_places(published_text) != int(entry["upper_decimal_places"]):
            report.fail(f"n={n}: published upper witness has {decimal_places(published_text)} decimals, metadata says {entry['upper_decimal_places']}")

        lower_text = row["certified_lower_bound"]
        width_places = max(decimal_places(published_text), decimal_places(lower_text))
        expected_width = format_exact_decimal(published - parse_exact_decimal(lower_text), width_places)
        if row["interval_width"] != expected_width:
            report.fail(f"n={n}: interval_width {row['interval_width']!r} != upper - lower ({expected_width!r})")
        else:
            report.count("interval_widths_verified")

        separation_text = row["minimum_source_separation"]
        places = decimal_places(separation_text)
        separation = parse_exact_decimal(separation_text)
        half_ulp = Fraction(1, 2 * 10**places)
        exact_squared = minimum_separation_squared(points)
        if not (separation - half_ulp) ** 2 <= exact_squared <= (separation + half_ulp) ** 2:
            report.fail(f"n={n}: minimum_source_separation is not the exact separation rounded to {places} decimals")
        else:
            report.count("separations_verified")


def check_saved_replays(report: Report, facts_by_n: dict[int, object]) -> None:
    """The per-certifier stdout snapshots stored under evidence/saved-replays/."""
    files = sorted(SAVED_REPLAYS.glob("n*/*.txt"))
    expected_keys = {(n, method) for n in EXPECTED_NS for method in METHODS}
    seen: set[tuple[int, str]] = set()

    for path in files:
        key = (int(path.parent.name[1:]), path.stem)
        if key not in expected_keys:
            report.fail(f"evidence/saved-replays: unexpected snapshot {path.relative_to(ROOT).as_posix()}")
            continue
        if key in seen:
            report.fail(f"evidence/saved-replays: duplicate snapshot for {key}")
            continue
        seen.add(key)

        text = path.read_text(encoding="utf-8")
        status = strict_status(text)
        if status != "CERTIFIED":
            report.fail(f"evidence/saved-replays/{path.parent.name}/{path.name}: status is {status!r}")
            continue

        n = key[0]
        facts = _FACTS_BY_KEY.get(key)
        if facts is None:
            continue
        points = read_coordinates_csv(ROOT / configuration_relpath(n))
        where = f"evidence/saved-replays/{path.parent.name}/{path.name}"
        problems = validate_proof_output(text, facts, where, lights=points)  # type: ignore[arg-type]
        if problems:
            for problem in problems:
                report.fail(problem)
        else:
            report.count("saved_replay_values_verified")

    missing = sorted(expected_keys - seen)
    if missing:
        report.fail(f"evidence/saved-replays: missing snapshots {missing}")
    report.count("saved_replays_checked", len(seen))


#: Types of the stored clean-room replay records. `splits`, `maximum_depth` and
#: `minimum_leaf_lower_bound` are strings in the published historical schema.
REPLAY_FIELD_TYPES: dict[str, str] = {
    "n": "int",
    "method": "method",
    "repo_relative_script": "str",
    "script_sha256": "hex64",
    "return_code": "int",
    "timed_out": "bool",
    "elapsed_seconds": "number",
    "status": "str",
    "splits": "str",
    "maximum_depth": "str",
    "minimum_leaf_lower_bound": "str",
    "stdout_log": "str",
    "stderr_log": "str",
}


def _replay_types_ok(report: Report, key: tuple[int, str], record: dict) -> bool:
    ok = True
    for field, kind in REPLAY_FIELD_TYPES.items():
        value = record[field]
        good = {
            "int": is_strict_int(value),
            "bool": isinstance(value, bool),
            "number": is_strict_number(value) and value >= 0,
            "str": isinstance(value, str),
            "hex64": isinstance(value, str) and bool(HEX64.fullmatch(value)),
            "method": isinstance(value, str) and value in METHODS,
        }[kind]
        if not good:
            report.fail(f"full replay {key}: field {field} is {value!r}, expected {kind}")
            ok = False
    return ok


def _check_replay_stdout(report: Report, key: tuple[int, str], record: dict, text: str) -> None:
    """Bind the record's measurements to the log it names, and read the log strictly.

    Comparing only the status let a record carry any split count at all. Beyond
    that, the log itself was barely read: setting
    ``minimum_leaf_lower_bound_decimal`` to ``0`` and reconciling the manifest
    passed, and so did ``splits: nonsense`` with ``maximum_depth: -1`` once the
    same strings were written into the record, the aggregates and the result
    table. Both sides are now checked: the record against the log, and the log
    against the certifier through the shared proof-output contract.
    """
    n, method = key
    status = strict_status(text)
    if status != record["status"]:
        report.fail(f"full replay {key}: stdout says {status!r} but the record says {record['status']!r}")
        return

    try:
        fields = parse_certifier_stdout(text, f"full replay {key}")
    except ValueError as error:
        report.fail(str(error))
        return

    for field in ("splits", "maximum_depth"):
        if field not in fields:
            report.fail(f"full replay {key}: stdout has no {field!r} line")
            continue
        if fields[field] != record[field]:
            report.fail(
                f"full replay {key}: stdout {field}={fields[field]!r} "
                f"but the record says {record[field]!r} (log: {record['stdout_log']})"
            )
        try:
            parse_canonical_integer(record[field], f"full replay {key}", f"record {field}")
        except ValueError as error:
            report.fail(str(error))

    # The published historical schema stores an empty minimum_leaf_lower_bound
    # while the log carries the decimal. The frozen evidence is not rewritten to
    # match; instead the legacy shape is stated and each side checked on its own.
    # The record's field is required to be empty; the log's value is required to
    # be a real bound, by validate_proof_output below.
    if record["minimum_leaf_lower_bound"] != "":
        report.fail(
            f"full replay {key}: minimum_leaf_lower_bound is {record['minimum_leaf_lower_bound']!r}; "
            "the historical schema stores an empty string here"
        )

    facts = _FACTS_BY_KEY.get(key)
    if facts is None:
        return

    points = read_coordinates_csv(ROOT / configuration_relpath(n))
    problems = validate_proof_output(
        text, facts, f"full replay {key} (log: {record['stdout_log']})", lights=points  # type: ignore[arg-type]
    )
    if problems:
        for problem in problems:
            report.fail(problem)
    else:
        report.count("replay_measurements_verified")


#: Certifier facts, published by check_certifier_constants for the replay checks.
_FACTS_BY_N: dict[int, object] = {}
#: The same facts per (n, method): a log must be read with the precision of the
#: certifier that produced it, and the two methods differ.
_FACTS_BY_KEY: dict[tuple[int, str], object] = {}


def check_full_replay(report: Report) -> None:
    replay = load_full_replay()
    records = replay.get("results")
    if not isinstance(records, list):
        report.fail("full replay: results is not a list")
        return

    if len(records) != 88:
        report.fail(f"full replay: {len(records)} records, expected 88")

    expected_keys = {(n, method) for n in EXPECTED_NS for method in METHODS}
    seen: set[tuple[int, str]] = set()

    for record in records:
        key = (int(record["n"]), str(record["method"]))
        if key not in expected_keys:
            report.fail(f"full replay: unexpected record {key}")
            continue
        if key in seen:
            report.fail(f"full replay: duplicate record {key}")
            continue
        seen.add(key)

        n, method = key
        expected_script = certifier_relpath(n, method)
        if record["repo_relative_script"] != expected_script:
            report.fail(f"full replay {key}: script path {record['repo_relative_script']!r}")
            continue
        if record["return_code"] != 0:
            report.fail(f"full replay {key}: return_code {record['return_code']}")
        if record["timed_out"] is not False:
            report.fail(f"full replay {key}: timed_out {record['timed_out']!r}")
        if record["status"] != "CERTIFIED":
            report.fail(f"full replay {key}: status {record['status']!r}")

        script = ROOT / expected_script
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        if digest != record["script_sha256"]:
            report.fail(f"full replay {key}: recorded script hash does not match the current file")
        else:
            report.count("replay_script_hashes_verified")

        # A record must name *its own* log. Checking only that the file exists
        # let a record point at another configuration's stdout, which is how a
        # falsified splits count could be made to look consistent.
        canonical_paths = {
            "stdout_log": canonical_log_name(n, method, "stdout", prefix="logs/"),
            "stderr_log": canonical_log_name(n, method, "stderr", prefix="logs/"),
        }
        log_paths: dict[str, Path] = {}
        for log_field, canonical in canonical_paths.items():
            declared = record[log_field]
            if not isinstance(declared, str) or declared != canonical:
                report.fail(f"full replay {key}: {log_field} is {declared!r}, expected {canonical!r}")
                continue
            log_paths[log_field] = FULL_REPLAY_DIR / declared

        for log_field, log_path in log_paths.items():
            if not log_path.is_file():
                report.fail(f"full replay {key}: missing {log_field} {record[log_field]}")
                continue
            text = log_path.read_text(encoding="utf-8")
            if log_field == "stdout_log":
                _check_replay_stdout(report, key, record, text)
            else:
                # A run that printed a success on stdout and a failure on stderr
                # would otherwise be stored as a clean CERTIFIED record.
                stderr_statuses = declared_statuses(text)
                stderr_tokens = forbidden_tokens_in(text)
                if stderr_statuses:
                    report.fail(f"full replay {key}: stderr declares a status: {stderr_statuses}")
                elif stderr_tokens:
                    report.fail(f"full replay {key}: stderr contains failure tokens: {stderr_tokens}")
                else:
                    report.count("replay_stderr_verified")

        meta_path = FULL_REPLAY_DIR / "logs" / f"{log_stem(n, method)}.meta.json"
        if not meta_path.is_file():
            report.fail(f"full replay {key}: missing per-job metadata {meta_path.name}")
        else:
            try:
                meta = load_json_strict(meta_path, dict)
            except Exception as error:  # noqa: BLE001 - surfaced verbatim as a problem
                report.fail(f"full replay {key}: per-job metadata could not be read strictly: {error}")
            else:
                if set(meta) != set(REPLAY_RECORD_FIELDS):
                    missing_fields = sorted(set(REPLAY_RECORD_FIELDS) - set(meta))
                    extra_fields = sorted(set(meta) - set(REPLAY_RECORD_FIELDS))
                    report.fail(
                        f"full replay {key}: per-job metadata field set mismatch "
                        f"missing={missing_fields} unexpected={extra_fields}"
                    )
                elif not _replay_types_ok(report, key, meta):
                    pass  # already reported
                elif meta != record:
                    differing = sorted(f for f in REPLAY_RECORD_FIELDS if meta[f] != record[f])
                    report.fail(f"full replay {key}: per-job metadata differs from the aggregate record in {differing}")
                else:
                    report.count("replay_metadata_verified")

    missing = sorted(expected_keys - seen)
    if missing:
        report.fail(f"full replay: missing records {missing}")

    recomputed_certified = sum(1 for record in records if record.get("status") == "CERTIFIED")
    recomputed_failed = len(records) - recomputed_certified
    for field, recomputed in (
        ("verifier_count", len(records)),
        ("certified_count", recomputed_certified),
        ("failed_count", recomputed_failed),
    ):
        if replay.get(field) != recomputed:
            report.fail(f"full replay: {field} is {replay.get(field)!r} but the records give {recomputed}")
        else:
            report.count("replay_aggregates_verified")

    csv_path = FULL_REPLAY_DIR / "PUBLIC_REPO_FULL_REPLAY.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        csv_records = list(reader)

    if header != list(REPLAY_RECORD_FIELDS):
        report.fail(f"full replay CSV: header is {header}, expected {list(REPLAY_RECORD_FIELDS)}")
        return

    # Row count alone is not enough: duplicating one key and dropping another
    # keeps the count at 88 while silently losing a certifier.
    csv_keys = [(int(row["n"]), row["method"]) for row in csv_records]
    if len(csv_records) != len(expected_keys):
        report.fail(f"full replay CSV: {len(csv_records)} rows, expected {len(expected_keys)}")
    duplicates = sorted({key for key in csv_keys if csv_keys.count(key) > 1})
    if duplicates:
        report.fail(f"full replay CSV: duplicate (n, method) rows: {duplicates}")
    missing_csv = sorted(expected_keys - set(csv_keys))
    unexpected_csv = sorted(set(csv_keys) - expected_keys)
    if missing_csv:
        report.fail(f"full replay CSV: missing rows {missing_csv}")
    if unexpected_csv:
        report.fail(f"full replay CSV: unexpected rows {unexpected_csv}")

    by_key = {(int(r["n"]), str(r["method"])): r for r in records}
    for row, key in zip(csv_records, csv_keys):
        record = by_key.get(key)
        if record is None:
            continue  # already reported as unexpected
        mismatched = [field for field in REPLAY_RECORD_FIELDS if str(record[field]) != row[field]]
        if mismatched:
            report.fail(f"full replay CSV {key}: fields differ from the JSON: {mismatched}")
        else:
            report.count("replay_csv_rows_verified")


def check_evidence_directories(report: Report) -> None:
    """Nothing may sit in the evidence directories except the expected files."""
    expected_logs = set()
    for n in EXPECTED_NS:
        for method in METHODS:
            stem = f"n{n:02d}_{method}"
            expected_logs.update({f"{stem}.stdout.txt", f"{stem}.stderr.txt", f"{stem}.meta.json"})

    log_dir = FULL_REPLAY_DIR / "logs"
    actual_logs = {entry.name for entry in log_dir.iterdir() if entry.is_file()}
    for label, extra in (("unexpected", actual_logs - expected_logs), ("missing", expected_logs - actual_logs)):
        if extra:
            report.fail(f"evidence/full-cleanroom-replay/logs: {label} files {sorted(extra)[:10]} ({len(extra)} total)")
    if not (actual_logs ^ expected_logs):
        report.count("replay_log_inventory_verified", len(actual_logs))

    expected_top = {"PUBLIC_REPO_FULL_REPLAY.json", "PUBLIC_REPO_FULL_REPLAY.csv", "PUBLIC_REPO_FULL_REPLAY.md"}
    actual_top = {entry.name for entry in FULL_REPLAY_DIR.iterdir() if entry.is_file()}
    if actual_top != expected_top:
        report.fail(
            "evidence/full-cleanroom-replay: unexpected="
            f"{sorted(actual_top - expected_top)} missing={sorted(expected_top - actual_top)}"
        )
    else:
        report.count("replay_top_level_inventory_verified", len(actual_top))

    expected_saved = {(f"n{n:02d}", f"{method}.txt") for n in EXPECTED_NS for method in METHODS}
    actual_saved = {
        (path.parent.name, path.name) for path in SAVED_REPLAYS.rglob("*") if path.is_file()
    }
    if actual_saved != expected_saved:
        report.fail(
            "evidence/saved-replays: unexpected="
            f"{sorted(actual_saved - expected_saved)[:10]} missing={sorted(expected_saved - actual_saved)[:10]}"
        )
    else:
        report.count("saved_replay_inventory_verified", len(actual_saved))


def check_generated_tables_are_current(report: Report) -> None:
    """The published tables must equal what the generator would produce."""
    import regenerate_certified_results as generator

    try:
        records = generator.build_records()
    except generator.GenerationError as error:
        report.fail(f"the result tables cannot be regenerated: {error}")
        return

    for path, payload in (
        (generator.RESULTS_CSV, generator.render_csv(records)),
        (generator.RESULTS_JSON, generator.render_json(records)),
    ):
        if path.read_bytes() != payload:
            report.fail(f"{path.relative_to(ROOT).as_posix()} is not what the generator produces; run --write")
        else:
            report.count("generated_tables_verified")


def main() -> int:
    report = Report()

    facts_by_n: dict[int, object] = {}
    # Each section is isolated: one corrupt input must not stop the remaining
    # checks, or a single failure would hide everything reported after it.
    for name, run in (
        ("configuration set", lambda: check_configuration_set(report)),
        ("csv/json agreement", lambda: check_csv_json_agreement(report)),
        ("configurations", lambda: check_configurations(report)),
        ("certifier constants", lambda: (facts_by_n.update(check_certifier_constants(report)),
                                         _FACTS_BY_N.update(facts_by_n))),
        ("upper witness", lambda: check_upper_witness(report, facts_by_n)),
        ("saved replays", lambda: check_saved_replays(report, facts_by_n)),
        ("full replay", lambda: check_full_replay(report)),
        ("evidence inventory", lambda: check_evidence_directories(report)),
        ("generated tables", lambda: check_generated_tables_are_current(report)),
    ):
        try:
            run()
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            report.fail(f"{name}: check could not complete: {type(error).__name__}: {error}")

    print(" ".join(f"{key}={value}" for key, value in sorted(report.counts.items())))
    print(f"problems={len(report.problems)}")
    if report.problems:
        print("\n".join(f"  - {problem}" for problem in report.problems))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
