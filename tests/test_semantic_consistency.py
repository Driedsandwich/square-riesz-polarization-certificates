"""Mutation tests: every single-point corruption must be caught.

Each test copies the repository, corrupts exactly one thing, and requires
``check_semantic_consistency.py`` to exit non-zero. A check that cannot fail is
not a check, so each test also asserts which problem was reported.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import (  # noqa: E402
    copy_repository,
    dump_results_json,
    load_json,
    read_text,
    replace_once,
    run_script,
    witness_literal,
    write_text,
)

from certificate_lib import ROOT, certifier_relpath, extract_certifier_facts  # noqa: E402


class MutationTestCase(unittest.TestCase):
    def check(self, repo: Path) -> "tuple[int, str]":
        result = run_script(repo, "check_semantic_consistency.py")
        return result.returncode, result.stdout + result.stderr

    def assert_rejected(self, repo: Path, expected_fragment: str) -> None:
        returncode, output = self.check(repo)
        self.assertEqual(returncode, 1, f"the corruption was not detected:\n{output}")
        self.assertIn(expected_fragment, output)


class ConfigurationMutations(MutationTestCase):
    def test_single_digit_change_in_a_coordinate_file_is_rejected(self) -> None:
        """Requirement 3."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "data" / "configurations" / "n20" / "coordinates.csv"
            rows = list(csv.reader(io.StringIO(read_text(path))))
            original = rows[1][1]
            mutated = original[:-1] + ("1" if original[-1] != "1" else "2")
            replace_once(path, f",{original},", f",{mutated},")
            self.assert_rejected(repo, "differ from data/configurations")

    def test_removing_a_configuration_row_is_rejected(self) -> None:
        """Requirement 11."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            csv_path = repo / "data" / "certified-results.csv"
            lines = read_text(csv_path).split("\r\n")
            kept = [line for line in lines if not line.startswith("52,")]
            self.assertEqual(len(kept), len(lines) - 1)
            write_text(csv_path, "\r\n".join(kept))

            json_path = repo / "data" / "certified-results.json"
            records = [record for record in load_json(json_path) if record["n"] != "52"]
            dump_results_json(json_path, records)

            self.assert_rejected(repo, "missing configurations [52]")

    def test_adding_a_forty_fifth_configuration_is_rejected(self) -> None:
        """Requirement 10."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            csv_path = repo / "data" / "certified-results.csv"
            lines = read_text(csv_path).split("\r\n")
            last = next(line for line in lines if line.startswith("52,"))
            extra = "53," + last.split(",", 1)[1]
            write_text(csv_path, "\r\n".join(lines[:-1] + [extra, ""]))

            json_path = repo / "data" / "certified-results.json"
            records = load_json(json_path)
            duplicate = copy.deepcopy(records[-1])
            duplicate["n"] = "53"
            records.append(duplicate)
            dump_results_json(json_path, records)

            self.assert_rejected(repo, "unexpected configurations [53]")


class CertifierMutations(MutationTestCase):
    def test_changing_target_in_one_certifier_only_is_rejected(self) -> None:
        """Requirement 4."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            literal = extract_certifier_facts(ROOT / certifier_relpath(20, "spectral")).target_literal
            path = repo / "certifiers" / "n20" / "spectral.py"
            replace_once(path, f'Q("{literal}")', f'Q("{literal}1")')
            self.assert_rejected(repo, "TARGET literal differs")

    def test_changing_a_witness_point_in_one_certifier_only_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "certifiers" / "n21" / "spectral.py"
            literal = witness_literal(path)
            replace_once(path, f'Q("{literal}")', f'Q("{literal}1")')
            self.assert_rejected(repo, "different upper witness points")


class TableMutations(MutationTestCase):
    def test_changing_only_the_csv_is_rejected_by_the_json_comparison(self) -> None:
        """Requirement 5."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            replace_once(
                repo / "data" / "certified-results.csv",
                "CERTIFIED_FIXED_CONFIGURATION_EXCEEDS_DISPLAYED_FIGURE",
                "CERTIFIED_FIXED_CONFIGURATION_EXCEEDS_DISPLAYED_FIGURE_EDITED",
            )
            self.assert_rejected(repo, "csv 'CERTIFIED_FIXED_CONFIGURATION_EXCEEDS_DISPLAYED_FIGURE_EDITED'")

    def test_interval_width_must_follow_the_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            csv_path = repo / "data" / "certified-results.csv"
            width = next(
                row["interval_width"]
                for row in csv.DictReader(io.StringIO(read_text(csv_path)))
                if row["n"] == "7"
            )
            broken = width[:-1] + ("1" if width[-1] != "1" else "2")
            replace_once(csv_path, width, broken)
            replace_once(repo / "data" / "certified-results.json", width, broken)
            self.assert_rejected(repo, "interval_width")


class ReplayEvidenceMutations(MutationTestCase):
    def test_duplicated_replay_record_with_unchanged_aggregate_is_rejected(self) -> None:
        """Requirement 6: 88 records, still 88 certified, but one pair duplicated."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "evidence" / "full-cleanroom-replay" / "PUBLIC_REPO_FULL_REPLAY.json"
            replay = load_json(path)
            records = replay["results"]
            self.assertEqual(len(records), 88)
            records[1] = copy.deepcopy(records[0])  # duplicate the first pair, drop the second
            self.assertEqual(len(records), 88)
            self.assertEqual(replay["verifier_count"], 88)
            self.assertEqual(replay["certified_count"], 88)
            write_text(path, json.dumps(replay, indent=2))

            returncode, output = self.check(repo)
            self.assertEqual(returncode, 1, output)
            self.assertIn("duplicate record", output)

    def test_tampering_with_a_certifier_breaks_the_recorded_script_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "certifiers" / "n22" / "componentwise.py"
            path.write_text(read_text(path) + "\n# appended\n", encoding="utf-8")
            self.assert_rejected(repo, "recorded script hash does not match")


if __name__ == "__main__":
    unittest.main()
