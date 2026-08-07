"""The published upper bounds must dominate the exact witness potential."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True

from support import REPO_ROOT, copy_repository, replace_once, run_script  # noqa: E402

from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    METHODS,
    ROOT,
    certifier_relpath,
    configuration_relpath,
    decimal_places,
    exact_potential,
    extract_certifier_facts,
    load_results_csv,
    parse_exact_decimal,
    read_coordinates_csv,
    round_up_to_places,
)

# The value published in v1.0.1 and the outward-rounded replacement.
N15_PUBLISHED_V101 = "115.163545738140865425310886989792958990774562099421856468660672334475379483037735242850051"
N15_CORRECTED = "115.163545738140865425310886989792958990774562099421856468660672334475379483037735242850052"


def n15_exact() -> Fraction:
    facts = extract_certifier_facts(ROOT / certifier_relpath(15, "spectral"))
    coordinates = read_coordinates_csv(ROOT / configuration_relpath(15))
    return exact_potential(coordinates, facts.witness)


class ExactWitnessArithmetic(unittest.TestCase):
    def test_v101_value_for_n15_is_not_an_upper_bound(self) -> None:
        """Requirement 1: the old n=15 decimal must be rejected."""
        exact = n15_exact()
        self.assertLess(
            parse_exact_decimal(N15_PUBLISHED_V101),
            exact,
            "the v1.0.1 decimal was expected to fall below the exact potential",
        )

    def test_corrected_value_for_n15_is_an_upper_bound(self) -> None:
        """Requirement 2: the corrected n=15 decimal must be accepted."""
        exact = n15_exact()
        self.assertGreaterEqual(parse_exact_decimal(N15_CORRECTED), exact)
        self.assertEqual(round_up_to_places(exact, decimal_places(N15_CORRECTED)), N15_CORRECTED)

    def test_correction_is_the_smallest_valid_decimal_at_that_precision(self) -> None:
        exact = n15_exact()
        places = decimal_places(N15_CORRECTED)
        one_ulp_below = parse_exact_decimal(N15_CORRECTED) - Fraction(1, 10**places)
        self.assertLess(one_ulp_below, exact)

    def test_all_configurations_satisfy_the_upper_witness_inequality(self) -> None:
        """Requirement 12: check the inequality for every configuration."""
        rows = {int(row["n"]): row for row in load_results_csv()}
        self.assertEqual(sorted(rows), list(EXPECTED_NS))
        checked = 0
        for n in EXPECTED_NS:
            with self.subTest(n=n):
                witnesses = {
                    method: extract_certifier_facts(ROOT / certifier_relpath(n, method)).witness
                    for method in METHODS
                }
                self.assertEqual(witnesses["spectral"], witnesses["componentwise"])
                coordinates = read_coordinates_csv(ROOT / configuration_relpath(n))
                exact = exact_potential(coordinates, witnesses["spectral"])
                published = parse_exact_decimal(rows[n]["rigorous_upper_witness"])
                self.assertGreaterEqual(published, exact, f"n={n} published value is below the exact potential")
                checked += 1
        self.assertEqual(checked, 44)

    def test_outward_rounding_never_rounds_down(self) -> None:
        for text, places in (("1.0000000001", 2), ("2.5", 0), ("0.999", 1)):
            value = parse_exact_decimal(text)
            rounded = parse_exact_decimal(round_up_to_places(value, places))
            self.assertGreaterEqual(rounded, value)
            self.assertLess(rounded - value, Fraction(1, 10**places))

    def test_outward_rounding_rejects_non_positive_values(self) -> None:
        with self.assertRaises(ValueError):
            round_up_to_places(Fraction(0), 3)
        with self.assertRaises(ValueError):
            round_up_to_places(Fraction(-1, 2), 3)


class RestoringTheOldValueFails(unittest.TestCase):
    def test_semantic_check_rejects_the_v101_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            replace_once(repo / "data" / "certified-results.csv", N15_CORRECTED, N15_PUBLISHED_V101)
            replace_once(repo / "data" / "certified-results.json", N15_CORRECTED, N15_PUBLISHED_V101)
            result = run_script(repo, "check_semantic_consistency.py")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("below the exact potential", result.stdout)

    def test_semantic_check_accepts_the_untouched_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            result = run_script(repo, "check_semantic_consistency.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("problems=0", result.stdout)

    def test_audit_json_output_is_a_single_parseable_document(self) -> None:
        """--json is a machine contract: no prose may share stdout with it."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            result = run_script(repo, "audit_upper_witness.py", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["configurations"], 44)
            self.assertEqual(payload["below_exact"], [])
            self.assertEqual(len(payload["findings"]), 44)
            self.assertEqual({finding["n"] for finding in payload["findings"]}, set(EXPECTED_NS))
            for finding in payload["findings"]:
                self.assertEqual(finding["interval_width_current"], finding["interval_width_recomputed"])

    def test_audit_script_flags_the_v101_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            replace_once(repo / "data" / "certified-results.csv", N15_CORRECTED, N15_PUBLISHED_V101)
            result = run_script(repo, "audit_upper_witness.py", "--quiet")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("BELOW_EXACT", result.stdout)


if __name__ == "__main__":
    unittest.main()
