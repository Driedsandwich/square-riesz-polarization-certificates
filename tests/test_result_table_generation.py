"""The result tables are build products: reproducible, and never hand-edited."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import copy_repository, read_text, replace_once, run_script  # noqa: E402

import regenerate_certified_results as generator  # noqa: E402
from certificate_lib import RESULT_FIELDS  # noqa: E402


class GeneratorIsDeterministic(unittest.TestCase):
    def test_two_runs_produce_identical_bytes(self) -> None:
        first = generator.build_records()
        second = generator.build_records()
        self.assertEqual(generator.render_csv(first), generator.render_csv(second))
        self.assertEqual(generator.render_json(first), generator.render_json(second))

    def test_generated_tables_match_the_files_on_disk(self) -> None:
        records = generator.build_records()
        self.assertEqual(generator.RESULTS_CSV.read_bytes(), generator.render_csv(records))
        self.assertEqual(generator.RESULTS_JSON.read_bytes(), generator.render_json(records))

    def test_csv_keeps_the_published_shape(self) -> None:
        payload = generator.render_csv(generator.build_records())
        self.assertTrue(payload.endswith(b"\r\n"))
        self.assertNotIn(b'"', payload)
        header = payload.split(b"\r\n", 1)[0].decode()
        self.assertEqual(header.split(","), list(RESULT_FIELDS))

    def test_json_keeps_the_published_shape(self) -> None:
        payload = generator.render_json(generator.build_records())
        self.assertFalse(payload.endswith(b"\n"))
        self.assertTrue(payload.startswith(b"[\n  {\n"))

    def test_every_row_has_every_field_as_a_string(self) -> None:
        for record in generator.build_records():
            self.assertEqual(list(record.keys()), list(RESULT_FIELDS))
            for field, value in record.items():
                self.assertIsInstance(value, str, field)


class CheckModeDetectsDrift(unittest.TestCase):
    def test_check_passes_on_an_untouched_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            result = run_script(repo, "regenerate_certified_results.py", "--check")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("differences=0", result.stdout)

    def test_check_rejects_a_hand_edited_derived_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            csv_path = repo / "data" / "certified-results.csv"
            row = next(line for line in read_text(csv_path).split("\r\n") if line.startswith("7,"))
            upper = row.split(",")[2]
            replace_once(csv_path, upper, upper[:-1] + ("1" if upper[-1] != "1" else "2"))
            result = run_script(repo, "regenerate_certified_results.py", "--check")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("line 2: n=7", result.stdout)

    def test_write_restores_the_generated_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            csv_path = repo / "data" / "certified-results.csv"
            original = csv_path.read_bytes()
            row = next(line for line in read_text(csv_path).split("\r\n") if line.startswith("7,"))
            upper = row.split(",")[2]
            replace_once(csv_path, upper, upper[:-1] + ("1" if upper[-1] != "1" else "2"))
            self.assertNotEqual(csv_path.read_bytes(), original)

            written = run_script(repo, "regenerate_certified_results.py", "--write")
            self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
            self.assertEqual(csv_path.read_bytes(), original)

    def test_changing_only_the_precision_metadata_changes_the_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            replace_once(
                repo / "data" / "results-metadata.json",
                '"upper_decimal_places": 68',
                '"upper_decimal_places": 40',
            )
            result = run_script(repo, "regenerate_certified_results.py", "--check")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("line 2: n=7", result.stdout)


if __name__ == "__main__":
    unittest.main()
