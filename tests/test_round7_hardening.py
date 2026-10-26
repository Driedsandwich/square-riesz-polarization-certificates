"""Round 7: per-record release checks, full-count replays, contained source errors.

Each test here exercises a defect found by the post-v1.0.2 audit. Mutations are
applied to throwaway copies; nothing writes to this repository.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import copy_repository, load_json, run_script  # noqa: E402

FULL_REPLAY = Path("evidence") / "full-cleanroom-replay" / "PUBLIC_REPO_FULL_REPLAY.json"


class CheckReleaseReadsEveryRecord(unittest.TestCase):
    """``check_release.py`` used to compare only the three declared counters."""

    def run_with_records(self, mutate) -> "tuple[int, str]":
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / FULL_REPLAY
            replay = load_json(path)
            mutate(replay["results"])
            path.write_text(json.dumps(replay, indent=2), encoding="utf-8")
            result = run_script(repo, "check_release.py")
            return result.returncode, result.stdout + result.stderr

    def test_untouched_copy_passes(self) -> None:
        """Positive control: the copy itself must pass, or nothing below means anything."""
        code, output = self.run_with_records(lambda records: None)
        self.assertEqual(code, 0, output)
        self.assertIn("issues=0", output)

    def test_every_record_failed_with_counters_left_at_88(self) -> None:
        def fail_all(records) -> None:
            for record in records:
                record["status"] = "FAILED"

        code, output = self.run_with_records(fail_all)
        self.assertEqual(code, 1, output)
        self.assertIn("status='FAILED', expected CERTIFIED", output)

    def test_nonzero_return_code(self) -> None:
        def nonzero(records) -> None:
            records[0]["return_code"] = 1

        code, output = self.run_with_records(nonzero)
        self.assertEqual(code, 1, output)
        self.assertIn("return_code=1, expected 0", output)

    def test_boolean_return_code_is_not_zero(self) -> None:
        def boolean(records) -> None:
            records[0]["return_code"] = False

        code, output = self.run_with_records(boolean)
        self.assertEqual(code, 1, output)
        self.assertIn("return_code=False, expected 0", output)

    def test_timed_out(self) -> None:
        def timed_out(records) -> None:
            records[0]["timed_out"] = True

        code, output = self.run_with_records(timed_out)
        self.assertEqual(code, 1, output)
        self.assertIn("timed_out=True, expected false", output)

    def test_duplicated_record_replacing_another(self) -> None:
        def duplicate(records) -> None:
            records[1] = dict(records[0])

        code, output = self.run_with_records(duplicate)
        self.assertEqual(code, 1, output)
        self.assertIn("duplicate replay record", output)
        self.assertIn("no replay record for", output)

    def test_missing_record(self) -> None:
        code, output = self.run_with_records(lambda records: records.pop())
        self.assertEqual(code, 1, output)
        self.assertIn("has 87 records, expected 88", output)
        self.assertIn("no replay record for", output)


if __name__ == "__main__":
    unittest.main()
