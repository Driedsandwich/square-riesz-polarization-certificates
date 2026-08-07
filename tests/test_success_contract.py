"""A certifier only passes when it says so, exactly once, and exits cleanly."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import MINIMAL_CERTIFIER, copy_repository, run_script, write_fake_certifier  # noqa: E402

from verifier_runner import classify, guard_optimized_mode, run_certifier  # noqa: E402

CERTIFIED_AND_EXIT_ZERO = 'print("status: CERTIFIED")\n'
NOT_CERTIFIED_AND_EXIT_ZERO = 'print("status: NOT_CERTIFIED")\n'
BOTH_STATUSES_AND_EXIT_ZERO = 'print("status: CERTIFIED")\nprint("status: NOT_CERTIFIED")\n'
CONTRADICTION_IN_PROSE = 'print("status: CERTIFIED")\nprint("note: NOT_CERTIFIED for one box")\n'
NO_STATUS_AND_EXIT_ZERO = 'print("splits: 3")\nprint("done")\n'
BARE_TOKEN_AND_EXIT_ZERO = 'print("CERTIFIED")\n'
STATUS_THEN_NONZERO_EXIT = 'import sys\nprint("status: CERTIFIED")\nsys.exit(3)\n'


class FakeCertifierEndToEnd(unittest.TestCase):
    """Run verify_one.py against a planted certifier in a throwaway copy."""

    def run_fake(self, body: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            write_fake_certifier(repo, 7, "spectral", body)
            return run_script(repo, "verify_one.py", "--n", "7", "--method", "spectral", "--timeout", "60")

    def test_not_certified_with_exit_zero_is_a_failure(self) -> None:
        """Requirement 7."""
        result = self.run_fake(NOT_CERTIFIED_AND_EXIT_ZERO)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("status is NOT_CERTIFIED", result.stderr)

    def test_both_statuses_with_exit_zero_is_a_failure(self) -> None:
        """Requirement 8."""
        result = self.run_fake(BOTH_STATUSES_AND_EXIT_ZERO)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("status lines", result.stderr)

    def test_missing_status_with_exit_zero_is_a_failure(self) -> None:
        """Requirement 9."""
        result = self.run_fake(NO_STATUS_AND_EXIT_ZERO)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no status line", result.stderr)

    def test_declared_certified_is_a_success(self) -> None:
        """A complete run is accepted.

        Round 4: CERTIFIED_AND_EXIT_ZERO no longer belongs here. A status line
        with no proof behind it satisfies the exit-code and status contract and
        is rejected anyway, by the proof-output contract, which is what the
        rejection test below now pins. The positive case needs a certifier that
        actually certifies something.
        """
        result = self.run_fake(MINIMAL_CERTIFIER)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("certified=1/1", result.stdout)

    def test_a_status_line_with_no_proof_behind_it_is_a_failure(self) -> None:
        """Rejected while reading the source: a bare print is not a certifier."""
        result = self.run_fake(CERTIFIED_AND_EXIT_ZERO)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAILED n=7 spectral", result.stderr)
        self.assertIn("certified=0/1", result.stderr)


class ClassificationContract(unittest.TestCase):
    def assert_rejected(self, stdout: str, return_code: int = 0, timed_out: bool = False, stderr: str = "") -> None:
        _, certified, reason = classify(return_code, timed_out, stdout, stderr)
        self.assertFalse(certified)
        self.assertIsNotNone(reason)

    def test_bare_token_is_not_a_status_declaration(self) -> None:
        self.assert_rejected("CERTIFIED\n")

    def test_contradiction_outside_the_status_line_is_rejected(self) -> None:
        self.assert_rejected("status: CERTIFIED\nnote: NOT_CERTIFIED for one box\n")

    def test_non_zero_exit_is_rejected_even_when_certified_is_printed(self) -> None:
        self.assert_rejected("status: CERTIFIED\n", return_code=3)

    def test_timeout_is_rejected_even_when_certified_is_printed(self) -> None:
        self.assert_rejected("status: CERTIFIED\n", return_code=124, timed_out=True)

    def test_the_only_accepted_shape(self) -> None:
        status, certified, reason = classify(0, False, "status: CERTIFIED\nsplits: 5\n", "")
        self.assertEqual(status, "CERTIFIED")
        self.assertTrue(certified)
        self.assertIsNone(reason)

    def test_a_substring_search_would_have_accepted_what_we_reject(self) -> None:
        """Guards the reason the contract exists, not just its current output."""
        for stdout in (
            "status: NOT_CERTIFIED\nCERTIFIED\n",
            "status: CERTIFIED\nstatus: CERTIFIED\n",
            "CERTIFIED\n",
        ):
            with self.subTest(stdout=stdout):
                self.assertIn("CERTIFIED", stdout)
                self.assert_rejected(stdout)


class OptimizationMode(unittest.TestCase):
    def test_guard_passes_in_a_normal_interpreter(self) -> None:
        guard_optimized_mode()  # must not raise under the test runner

    def test_runner_refuses_to_start_under_optimization(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "verify_all.py"
        result = subprocess.run(
            [sys.executable, "-O", "-B", str(script), "--quick", "--jobs", "1"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to run", result.stdout + result.stderr)

    def test_child_environment_drops_pythonoptimize(self) -> None:
        import os

        from verifier_runner import child_environment

        os.environ["PYTHONOPTIMIZE"] = "2"
        try:
            self.assertNotIn("PYTHONOPTIMIZE", child_environment())
        finally:
            os.environ.pop("PYTHONOPTIMIZE", None)

    def test_child_runs_with_assertions_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "probe.py"
            script.write_text(
                "import sys\n"
                "print('status: CERTIFIED' if sys.flags.optimize == 0 else 'status: NOT_CERTIFIED')\n",
                encoding="utf-8",
            )
            import os

            os.environ["PYTHONOPTIMIZE"] = "2"
            try:
                outcome = run_certifier(0, "spectral", script, timeout=60)
            finally:
                os.environ.pop("PYTHONOPTIMIZE", None)
            # The probe declares CERTIFIED exactly when it saw optimisation off,
            # which is the thing under test. It is not a certifier, so it cannot
            # satisfy the proof-output contract and `certified` would be False
            # for a reason that has nothing to do with PYTHONOPTIMIZE.
            self.assertEqual(outcome.status, "CERTIFIED", outcome.stdout)
            self.assertFalse(outcome.certified, "a non-certifier must not be certified")


class TimeoutHandling(unittest.TestCase):
    def test_a_hanging_certifier_is_not_certified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "hang.py"
            script.write_text("import time\nprint('status: CERTIFIED', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
            outcome = run_certifier(0, "spectral", script, timeout=2)
            self.assertTrue(outcome.timed_out)
            self.assertFalse(outcome.certified)
            self.assertEqual(outcome.failure_reason, "timed out")


if __name__ == "__main__":
    unittest.main()
