#!/usr/bin/env python3
"""Generate ``data/certified-results.csv`` and ``data/certified-results.json``.

Both files are build products of one pipeline, so they can never drift apart
and no derived quantity is ever typed in by hand. Every numeric field that has
a definition is computed here:

* ``certified_lower_bound``   the TARGET literal of the two certifiers
* ``rigorous_upper_witness``  the exact potential at the upper witness point,
                              rounded outward (up) to the row's decimal places
* ``interval_width``          upper minus lower, exactly
* ``source_count``            the number of published coordinates
* ``*_splits`` / ``*_maximum_depth`` / ``full_replay_status``
                              read from the stored clean-room replay evidence
* the three repository paths   derived from n

Only values with no definition — provenance prose, the externally submitted
figure, the local-minima count, the presentation precision and the descriptive
minimum source separation — come from ``data/results-metadata.json``.

Usage:
    python scripts/regenerate_certified_results.py --check
    python scripts/regenerate_certified_results.py --write

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys

sys.dont_write_bytecode = True

from certificate_lib import (  # noqa: E402  (path bootstrap above)
    EXPECTED_NS,
    METHODS,
    RESULTS_CSV,
    RESULTS_JSON,
    RESULT_FIELDS,
    ROOT,
    certifier_relpath,
    configuration_relpath,
    decimal_places,
    exact_potential,
    extract_certifier_facts,
    format_exact_decimal,
    load_full_replay,
    load_results_metadata,
    parse_exact_decimal,
    read_coordinates_csv,
    round_up_to_places,
    validate_witness_point,
    write_bytes_atomic,
)


class GenerationError(Exception):
    """The inputs are inconsistent, so no result table can be produced."""


def _replay_index() -> dict[tuple[int, str], dict[str, object]]:
    """Index the stored replay, requiring exactly the expected key set."""
    replay = load_full_replay()
    index: dict[tuple[int, str], dict[str, object]] = {}
    for record in replay["results"]:
        key = (int(record["n"]), str(record["method"]))
        if key in index:
            raise GenerationError(f"duplicate replay record for {key}")
        index[key] = record
    expected = {(n, method) for n in EXPECTED_NS for method in METHODS}
    missing = sorted(expected - set(index))
    unexpected = sorted(set(index) - expected)
    if missing or unexpected:
        raise GenerationError(f"stored replay key set mismatch: missing={missing} unexpected={unexpected}")
    return index


def build_records() -> list[dict[str, str]]:
    metadata = load_results_metadata()
    replay = _replay_index()
    records: list[dict[str, str]] = []

    for n in EXPECTED_NS:
        if n not in metadata:
            raise GenerationError(f"no metadata entry for n={n}")
        entry = metadata[n]

        coordinates = read_coordinates_csv(ROOT / configuration_relpath(n))
        if len(coordinates) != n:
            raise GenerationError(f"n={n}: configuration has {len(coordinates)} points")

        facts = {method: extract_certifier_facts(ROOT / certifier_relpath(n, method)) for method in METHODS}
        spectral, componentwise = facts["spectral"], facts["componentwise"]
        if spectral.target_literal != componentwise.target_literal:
            raise GenerationError(f"n={n}: the two certifiers declare different TARGET literals")
        if spectral.lights != componentwise.lights:
            raise GenerationError(f"n={n}: the two certifiers use different coordinates")
        if spectral.lights != coordinates:
            raise GenerationError(f"n={n}: certifier coordinates differ from data/configurations")
        if spectral.witness != componentwise.witness:
            raise GenerationError(f"n={n}: the two certifiers use different witness points")

        lower_text = spectral.target_literal
        lower = parse_exact_decimal(lower_text)

        # The potential at a point bounds the minimum over the unit square only
        # if the point is in the unit square.
        witness = validate_witness_point(spectral.witness, coordinates, f"n={n}")

        places = int(entry["upper_decimal_places"])
        exact = exact_potential(coordinates, witness)
        if exact < lower:
            raise GenerationError(f"n={n}: the witness value is below the certified lower bound")
        upper_text = round_up_to_places(exact, places)
        if parse_exact_decimal(upper_text) < exact:
            raise GenerationError(f"n={n}: outward rounding did not produce an upper bound")

        width_places = max(places, decimal_places(lower_text))
        width_text = format_exact_decimal(parse_exact_decimal(upper_text) - lower, width_places)

        statuses = set()
        for method in METHODS:
            record = replay.get((n, method))
            if record is None:
                raise GenerationError(f"n={n} {method}: missing from the stored full replay")
            if record["return_code"] != 0 or record["timed_out"] is not False:
                raise GenerationError(f"n={n} {method}: stored replay did not succeed")
            if record["repo_relative_script"] != certifier_relpath(n, method):
                raise GenerationError(f"n={n} {method}: stored replay points at another script")
            statuses.add(str(record["status"]))
        if statuses != {"CERTIFIED"}:
            raise GenerationError(f"n={n}: stored replay statuses are {sorted(statuses)}")

        records.append(
            {
                "n": str(n),
                "certified_lower_bound": lower_text,
                "rigorous_upper_witness": upper_text,
                "interval_width": width_text,
                "source_count": str(len(coordinates)),
                "minimum_source_separation": str(entry["minimum_source_separation"]),
                "symmetry_or_family": str(entry["symmetry_or_family"]),
                "all_local_minima_count": str(entry["all_local_minima_count"]),
                "spectral_splits": str(replay[(n, "spectral")]["splits"]),
                "spectral_maximum_depth": str(replay[(n, "spectral")]["maximum_depth"]),
                "componentwise_splits": str(replay[(n, "componentwise")]["splits"]),
                "componentwise_maximum_depth": str(replay[(n, "componentwise")]["maximum_depth"]),
                "submitted_lower_bound": str(entry["submitted_lower_bound"]),
                "external_status": str(entry["external_status"]),
                "configuration_path": configuration_relpath(n),
                "spectral_verifier_path": certifier_relpath(n, "spectral"),
                "componentwise_verifier_path": certifier_relpath(n, "componentwise"),
                "full_replay_status": "CERTIFIED",
                "notes": str(entry["notes"]),
            }
        )

    return records


def render_csv(records: list[dict[str, str]]) -> bytes:
    """Render the CSV exactly as published: CRLF endings, no optional quoting."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(RESULT_FIELDS), lineterminator="\r\n")
    writer.writeheader()
    for record in records:
        for field, value in record.items():
            if any(character in value for character in ',"\r\n'):
                raise GenerationError(f"field {field} would need quoting: {value!r}")
        writer.writerow(record)
    return buffer.getvalue().encode("utf-8")


def render_json(records: list[dict[str, str]]) -> bytes:
    """Render the JSON exactly as published: two-space indent, no final newline."""
    return json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="compare with the files on disk, changing nothing")
    group.add_argument("--write", action="store_true", help="write the generated files")
    arguments = parser.parse_args()

    records = build_records()
    rendered = {RESULTS_CSV: render_csv(records), RESULTS_JSON: render_json(records)}

    if arguments.write:
        # Both payloads are complete before either file is touched, and each
        # replacement is atomic. The pair still is not: an interruption between
        # them leaves the CSV new and the JSON old, which --check and the
        # semantic consistency check both detect.
        for path, payload in rendered.items():
            write_bytes_atomic(path, payload)
            print(f"wrote {path.relative_to(ROOT).as_posix()} bytes={len(payload)}")
        return 0

    differences: list[str] = []
    for path, payload in rendered.items():
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            differences.append(f"{relative}: missing")
            continue
        current = path.read_bytes()
        if current == payload:
            continue
        differences.append(f"{relative}: differs (on disk {len(current)} bytes, generated {len(payload)} bytes)")
        if path == RESULTS_CSV:
            current_rows = current.decode("utf-8").split("\r\n")
            generated_rows = payload.decode("utf-8").split("\r\n")
            for index, (before, after) in enumerate(zip(current_rows, generated_rows)):
                if before != after:
                    differences.append(f"  line {index + 1}: n={after.split(',')[0]}")
            if len(current_rows) != len(generated_rows):
                differences.append(f"  row count {len(current_rows)} -> {len(generated_rows)}")

    print(f"records={len(records)} differences={len(differences)}")
    if differences:
        print("\n".join(differences))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
