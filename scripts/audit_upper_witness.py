#!/usr/bin/env python3
"""Audit every published upper witness value against exact rational arithmetic.

For each certified configuration this recomputes

    sum_i 1 / ((px - xi)^2 + (py - yi)^2)

exactly, from the published finite-decimal coordinates in
``data/configurations/`` and the upper witness point recovered from the
certifier sources, and compares it with the decimal published in
``data/certified-results.csv``.

A published decimal that is strictly below the exact potential is not a valid
upper bound, so any BELOW_EXACT row makes this program exit non-zero.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys

sys.dont_write_bytecode = True

from certificate_lib import (  # noqa: E402  (path bootstrap above)
    EXPECTED_NS,
    METHODS,
    ROOT,
    certifier_relpath,
    configuration_relpath,
    decimal_places,
    exact_potential,
    format_exact_decimal,
    extract_certifier_facts,
    load_results_csv,
    parse_exact_decimal,
    read_coordinates_csv,
    round_up_to_places,
    validate_witness_point,
)

BELOW = "BELOW_EXACT"
EQUAL = "EQUAL_EXACT"
ABOVE = "ABOVE_EXACT"


def audit_one(n: int, row: dict[str, str]) -> dict[str, object]:
    coordinates = read_coordinates_csv(ROOT / configuration_relpath(n))

    witnesses = {}
    for method in METHODS:
        facts = extract_certifier_facts(ROOT / certifier_relpath(n, method))
        witnesses[method] = facts.witness
    if witnesses["spectral"] != witnesses["componentwise"]:
        raise SystemExit(f"n={n}: the two certifiers use different witness points")
    # An upper bound for the minimum over [0,1]^2 requires a point of [0,1]^2.
    witness = validate_witness_point(witnesses["spectral"], coordinates, f"n={n}")

    exact = exact_potential(coordinates, witness)
    published_text = row["rigorous_upper_witness"]
    published = parse_exact_decimal(published_text)
    places = decimal_places(published_text)

    if published < exact:
        comparison = BELOW
    elif published == exact:
        comparison = EQUAL
    else:
        comparison = ABOVE

    difference = exact - published
    corrected = round_up_to_places(exact, places)

    lower_text = row["certified_lower_bound"]
    lower = parse_exact_decimal(lower_text)
    width_places = max(places, decimal_places(lower_text))
    recomputed_width = format_exact_decimal(parse_exact_decimal(corrected) - lower, width_places)

    return {
        "n": n,
        "witness_point": [str(witness[0]), str(witness[1])],
        "exact_potential": f"{exact.numerator}/{exact.denominator}",
        "published_upper_witness": published_text,
        "comparison": comparison,
        "difference_exact_minus_published": f"{difference.numerator}/{difference.denominator}",
        "difference_approximate": f"{float(difference):.10e}",
        "decimal_places": places,
        "corrected_upper_witness": corrected,
        "changed": corrected != published_text,
        "interval_width_current": row["interval_width"],
        "interval_width_recomputed": recomputed_width,
        "interval_width_changed": recomputed_width != row["interval_width"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the full audit as JSON")
    parser.add_argument("--quiet", action="store_true", help="only print the summary line")
    arguments = parser.parse_args()

    rows = {int(row["n"]): row for row in load_results_csv()}
    missing = [n for n in EXPECTED_NS if n not in rows]
    unexpected = sorted(set(rows) - set(EXPECTED_NS))
    if missing or unexpected:
        print(f"configuration set mismatch: missing={missing} unexpected={unexpected}")
        return 1

    findings = [audit_one(n, rows[n]) for n in EXPECTED_NS]

    below = [f["n"] for f in findings if f["comparison"] == BELOW]
    equal = [f["n"] for f in findings if f["comparison"] == EQUAL]
    above = [f["n"] for f in findings if f["comparison"] == ABOVE]
    changed = [f["n"] for f in findings if f["changed"]]
    width_changed = [f["n"] for f in findings if f["interval_width_changed"]]

    summary = {
        "configurations": len(findings),
        "below_exact": below,
        "equal_exact": equal,
        "above_exact": above,
        "rows_needing_correction": changed,
        "interval_widths_needing_correction": width_changed,
    }

    if arguments.json:
        # Machine-readable mode emits one JSON document and nothing else on
        # stdout; a trailing human summary would make the output unparseable.
        print(json.dumps({**summary, "findings": findings}, indent=2))
        return 1 if below else 0

    if not arguments.quiet:
        header = f"{'n':>3} {'cmp':<11} {'digits':>6} {'exact-published':>18}  corrected"
        print(header)
        print("-" * len(header))
        for finding in findings:
            marker = "*" if finding["changed"] else " "
            print(
                f"{finding['n']:>3} {finding['comparison']:<11} {finding['decimal_places']:>6} "
                f"{finding['difference_approximate']:>18} {marker}{finding['corrected_upper_witness']}"
            )
        print()

    print(
        f"configurations={len(findings)} below_exact={len(below)} equal_exact={len(equal)} "
        f"above_exact={len(above)} rows_needing_correction={len(changed)} "
        f"interval_widths_needing_correction={len(width_changed)}"
    )
    if below:
        print(f"BELOW_EXACT (published decimal is not an upper bound): {below}")
    if changed:
        print(f"rows whose upper witness decimal changes: {changed}")
    return 1 if below else 0


if __name__ == "__main__":
    raise SystemExit(main())
