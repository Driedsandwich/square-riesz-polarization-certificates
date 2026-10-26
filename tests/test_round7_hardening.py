"""Round 7: per-record release checks, full-count replays, contained source errors.

Each test here exercises a defect found by the post-v1.0.2 audit. Mutations are
applied to throwaway copies; nothing writes to this repository.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import (  # noqa: E402
    MINIMAL_CERTIFIER,
    REPO_ROOT,
    copy_repository,
    load_json,
    run_script,
    shared_quick_replay,
    write_fake_certifier,
)

from certificate_lib import CertifierSourceError, extract_certifier_facts  # noqa: E402
from verifier_runner import proof_output_problems  # noqa: E402

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


class ExpectAllRequiresEveryVerifierCertified(unittest.TestCase):
    """``--expect-all`` accepted a summary with nine successes and one failure.

    The shared fixture is a quick replay, so ``--expect-all`` already rejects it
    for its selection and key set. These tests therefore look for the specific
    message of the count check, not just a non-zero exit: it must be absent for
    the untouched fixture and present once a failure is recorded.
    """

    MESSAGE = "--expect-all requires every verifier to be certified"

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.replay = shared_quick_replay()

    def validate(self, replay: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "validate_replay_output.py"), str(replay), "--expect-all"],
            capture_output=True,
            text=True,
            timeout=900,
        )

    def test_all_certified_fixture_does_not_trip_the_count_check(self) -> None:
        result = self.validate(self.replay)
        self.assertNotIn(self.MESSAGE, result.stdout)
        self.assertIn("all_certified_verified=1", result.stdout)

    def test_one_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "replay"
            shutil.copytree(self.replay, copy)
            summary = load_json(copy / "summary.json")
            summary["results"][0]["certified"] = False
            summary["certified_count"] = summary["verifier_count"] - 1
            summary["failed_count"] = 1
            (copy / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            result = self.validate(copy)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(self.MESSAGE, result.stdout)
        self.assertIn("certified_count=9 verifier_count=10 failed_count=1", result.stdout)


#: Shebang, a latin-1 coding cookie and a latin-1 byte. Python runs the file;
#: reading it as UTF-8 fails.
LATIN1_CERTIFIER = (
    b"#!/usr/bin/env python3\n# -*- coding: latin-1 -*-\n# caf\xe9\n"
    + MINIMAL_CERTIFIER.split("\n", 1)[1].encode("utf-8")
)


def _mutate(old: str, new: str) -> bytes:
    if old not in MINIMAL_CERTIFIER:
        raise AssertionError(f"pattern to mutate was not found: {old!r}")
    return MINIMAL_CERTIFIER.replace(old, new, 1).encode("utf-8")


class SourceReadingFailuresAreContained(unittest.TestCase):
    """Only ``CertifierSourceError`` used to be contained; the rest leaked."""

    MUTATIONS: dict[str, "bytes | None"] = {
        "SyntaxError": _mutate("def max_sq_1d(", "def max_sq_1d(("),
        "ValueError": _mutate('TARGET = Q("1.0")', 'TARGET = Q("x")'),
        "ZeroDivisionError": _mutate('TARGET = Q("1.0")', 'TARGET = Q("1.0")\nBROKEN = Q(1, 0)'),
        "TypeError": _mutate('TARGET = Q("1.0")', 'TARGET = Q("1.0") + "a"'),
        "UnicodeDecodeError": LATIN1_CERTIFIER,
        "FileNotFoundError": None,
    }

    def test_unmutated_fixture_reads(self) -> None:
        """Positive control: the mutations, not the fixture, cause the failures."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spectral.py"
            path.write_text(MINIMAL_CERTIFIER, encoding="utf-8")
            facts = extract_certifier_facts(path, verify_entry_point=True)
        self.assertEqual(len(facts.lights), 1)

    def test_each_failure_becomes_a_certifier_source_error(self) -> None:
        for name, payload in self.MUTATIONS.items():
            with self.subTest(exception=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "spectral.py"
                if payload is not None:
                    path.write_bytes(payload)
                with self.assertRaises(CertifierSourceError) as caught:
                    extract_certifier_facts(path, verify_entry_point=True)
                self.assertIn(str(path), str(caught.exception))
                self.assertIn(f"could not read certifier source: {name}", str(caught.exception))
                self.assertEqual(type(caught.exception.__cause__).__name__, name)

    def test_proof_output_problems_reports_instead_of_raising(self) -> None:
        for name, payload in self.MUTATIONS.items():
            with self.subTest(exception=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "spectral.py"
                if payload is not None:
                    path.write_bytes(payload)
                problems = proof_output_problems(path, "status: CERTIFIED\n", "probe")
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"could not read certifier source: {name}", problems[0])

    def test_verify_one_prints_a_problem_not_a_traceback(self) -> None:
        """The certifier itself runs and certifies; only reading its source fails."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            script = write_fake_certifier(repo, 7, "spectral", "")
            script.write_bytes(LATIN1_CERTIFIER)
            result = run_script(repo, "verify_one.py", "--n", "7", "--method", "spectral", "--timeout", "60")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("status: CERTIFIED", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("FAILED n=7 spectral", result.stderr)
        self.assertIn("could not read certifier source: UnicodeDecodeError", result.stderr)


if __name__ == "__main__":
    unittest.main()
