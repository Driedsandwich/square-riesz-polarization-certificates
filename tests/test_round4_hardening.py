"""Round 4: the entry point, the proof output, the corpus baseline and provenance.

Each test states the defect it pins. All of them were measured against the
previous implementation first, and every one of them passed there — that is why
they exist. Mutations are applied to copies; nothing here writes to the
repository's certifiers, configurations or stored evidence.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import (  # noqa: E402
    REPO_ROOT,
    copy_repository,
    read_text,
    replace_once,
    run_script,
    shared_quick_replay,
    write_text,
)

from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    METHODS,
    QUICK_NS,
    ROOT,
    CertifierSourceError,
    EntryPointError,
    certifier_relpath,
    extract_certifier_facts,
    parse_canonical_integer,
    validate_proof_output,
)

N15_SPECTRAL = ROOT / "certifiers" / "n15" / "spectral.py"
CERTIFY_CALL = "    result = certify()\n"
FAKE_RESULT = "CertificateResult(True, 0, 1, 0, TARGET, None, None)"


def check_entry_point(source: str) -> "str | None":
    """Run the entry-point check over ``source``; return the diagnostic or None."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "spectral.py"
        path.write_text(source, encoding="utf-8")
        try:
            extract_certifier_facts(path, verify_entry_point=True)
        except (EntryPointError, CertifierSourceError) as error:
            return str(error)
    return None


def mutate(old: str, new: str) -> str:
    source = N15_SPECTRAL.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise AssertionError(f"pattern occurs {source.count(old)} times, expected 1: {old!r}")
    return source.replace(old, new, 1)


class EntryPointShape(unittest.TestCase):
    """P1-A. Counting certify() calls with ast.walk accepted all of these.

    Every mutation below was run: each exited 0 printing ``status: CERTIFIED``,
    four of them in under 0.03 seconds with ``splits: 0`` against the real
    certifier's 3645 splits, because no proof was performed.
    """

    def assert_rejected(self, source: str, expected_fragment: str) -> None:
        diagnostic = check_entry_point(source)
        self.assertIsNotNone(diagnostic, "the mutated entry point was accepted")
        self.assertIn(expected_fragment, diagnostic)

    def test_certify_parked_on_an_unexecuted_branch(self) -> None:
        self.assert_rejected(
            mutate(CERTIFY_CALL, f"    result = certify() if False else {FAKE_RESULT}\n"),
            "must call certify() directly, found IfExp",
        )

    def test_module_level_lambda_rebinds_certify(self) -> None:
        self.assert_rejected(
            mutate("def main() -> None:\n", f"certify = lambda: {FAKE_RESULT}\n\n\ndef main() -> None:\n"),
            "module level rebinds 'certify'",
        )

    def test_second_definition_shadows_certify(self) -> None:
        self.assert_rejected(
            mutate(
                "def main() -> None:\n",
                f"def certify(target=TARGET, max_splits=1):\n    return {FAKE_RESULT}\n\n\ndef main() -> None:\n",
            ),
            "defined more than once at module level",
        )

    def test_early_return_after_printing_the_status(self) -> None:
        self.assert_rejected(
            mutate(CERTIFY_CALL, '    print("status:", "CERTIFIED")\n    return\n' + CERTIFY_CALL),
            "first statement of main() must assign certify()'s result",
        )

    def test_return_before_certify_is_called(self) -> None:
        self.assert_rejected(
            mutate(CERTIFY_CALL, '    print("status:", "CERTIFIED")\n    return\n' + CERTIFY_CALL),
            "found Expr",
        )

    def test_result_rebound_after_the_proof_runs(self) -> None:
        self.assert_rejected(
            mutate(CERTIFY_CALL, CERTIFY_CALL + f"    result = {FAKE_RESULT}\n"),
            "the upper witness value must come from a single-argument call to a potential helper",
        )

    def test_exit_before_the_final_assertions(self) -> None:
        self.assert_rejected(
            mutate("    assert result.certified\n", "    exit(0)\n    assert result.certified\n"),
            "only print() may be called for effect in main(), found 'exit'",
        )

    def test_exit_after_the_final_assertions(self) -> None:
        self.assert_rejected(
            mutate(
                "    assert witness_upper_bound >= TARGET\n",
                "    assert witness_upper_bound >= TARGET\n    exit(0)\n",
            ),
            "nothing may run after them",
        )

    def test_certify_called_with_a_substituted_target(self) -> None:
        self.assert_rejected(
            mutate(CERTIFY_CALL, "    result = certify(Q(0))\n"),
            "certify() must be called with no arguments",
        )

    def test_witness_value_taken_at_a_different_point(self) -> None:
        self.assert_rejected(
            mutate(
                "    witness_upper_bound = potential_at(UPPER_WITNESS)\n",
                "    witness_upper_bound = potential_at((Q(1), Q(1)))\n",
            ),
            "not at this certifier's witness point",
        )

    def test_status_printed_without_consulting_the_result(self) -> None:
        self.assert_rejected(
            mutate(
                '    print("status:", "CERTIFIED" if result.certified else "NOT_CERTIFIED")\n',
                '    print("status:", "CERTIFIED")\n',
            ),
            "the status line must be",
        )

    def test_certify_reached_through_a_helper(self) -> None:
        self.assert_rejected(
            mutate(CERTIFY_CALL, "    result = (lambda f: f())(certify)\n"),
            # Round 5: the module-wide lambda ban now fires first.
            "lambda is not part of the audited certifier shape",
        )

    def test_every_published_certifier_is_accepted(self) -> None:
        rejected = []
        for n in EXPECTED_NS:
            for method in METHODS:
                path = ROOT / certifier_relpath(n, method)
                try:
                    extract_certifier_facts(path, verify_entry_point=True)
                except (EntryPointError, CertifierSourceError) as error:
                    rejected.append(f"{path.relative_to(ROOT)}: {error}")
        self.assertEqual(rejected, [], "the shape check must accept the corpus it was derived from")


class ProofOutputContract(unittest.TestCase):
    """P1-B. A stdout file containing only ``status: CERTIFIED`` passed every
    exit-code, status, hash and schema check in the replay pipeline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = extract_certifier_facts(N15_SPECTRAL, verify_entry_point=True)
        cls.good = (ROOT / "evidence" / "saved-replays" / "n15" / "spectral.txt").read_text(encoding="utf-8")

    def problems(self, text: str) -> list[str]:
        return validate_proof_output(text, self.facts, "test")

    def replace(self, prefix: str, replacement: str) -> str:
        lines = [line for line in self.good.splitlines() if line.startswith(prefix)]
        self.assertEqual(len(lines), 1, f"expected exactly one {prefix!r} line")
        return self.good.replace(lines[0], replacement)

    def test_a_real_log_is_accepted(self) -> None:
        self.assertEqual(self.problems(self.good), [])

    def test_status_alone_is_not_a_proof(self) -> None:
        problems = self.problems("status: CERTIFIED\n")
        self.assertEqual(len(problems), 6, problems)

    def test_target_must_be_the_certifier_target(self) -> None:
        problems = self.problems(self.replace("target_decimal:", "target_decimal: 1"))
        self.assertTrue(any("is not the certifier TARGET" in p for p in problems), problems)

    def test_leaf_bound_below_target(self) -> None:
        problems = self.problems(self.replace("minimum_leaf_lower_bound_decimal:", "minimum_leaf_lower_bound_decimal: 0"))
        self.assertTrue(any("below the certified target" in p for p in problems), problems)

    def test_splits_must_be_a_number(self) -> None:
        problems = self.problems(self.replace("splits:", "splits: nonsense"))
        self.assertTrue(any("not a canonical non-negative integer" in p for p in problems), problems)

    def test_maximum_depth_must_not_be_negative(self) -> None:
        problems = self.problems(self.replace("maximum_depth:", "maximum_depth: -1"))
        self.assertTrue(any("maximum_depth" in p for p in problems), problems)

    def test_leaf_count_must_be_at_least_one(self) -> None:
        problems = self.problems(self.replace("leaf_count:", "leaf_count: 0"))
        self.assertTrue(any("expected at least 1" in p for p in problems), problems)

    def test_upper_witness_value_must_reproduce_exactly(self) -> None:
        line = next(l for l in self.good.splitlines() if l.startswith("witness_value_upper_bound_decimal:"))
        altered = line[:-1] + ("8" if line[-1] != "8" else "7")
        problems = self.problems(self.good.replace(line, altered))
        self.assertTrue(any("does not reproduce the exact potential" in p for p in problems), problems)

    def test_a_truncated_upper_value_is_not_accepted(self) -> None:
        """Deriving the precision from the log itself would accept this."""
        line = next(l for l in self.good.splitlines() if l.startswith("witness_value_upper_bound_decimal:"))
        problems = self.problems(self.good.replace(line, line[:40]))
        self.assertTrue(any("does not reproduce the exact potential" in p for p in problems), problems)

    def test_duplicate_measurement_lines_are_rejected(self) -> None:
        problems = self.problems(self.good + "splits: 0\n")
        self.assertTrue(any("duplicate structured line" in p for p in problems), problems)

    def test_missing_upper_value_line(self) -> None:
        line = next(l for l in self.good.splitlines() if l.startswith("witness_value_upper_bound_decimal:"))
        problems = self.problems(self.good.replace(line + "\n", ""))
        self.assertTrue(any("exactly one upper witness value line" in p for p in problems), problems)

    def test_canonical_integer_spellings(self) -> None:
        for text in ("-1", "+1", "01", "1_0", "1e3", " 1", "1 ", "", "True", "nan", "1.0"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_canonical_integer(text, "test", "splits")
        self.assertEqual(parse_canonical_integer("0", "test", "splits"), 0)
        self.assertEqual(parse_canonical_integer("3645", "test", "splits"), 3645)


class LiveRunnerRejectsFakeOutput(unittest.TestCase):
    """P1-B, on the live path: a certifier that prints only a status must fail."""

    def test_status_only_certifier_is_not_certified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = copy_repository(Path(directory))
            script = repo / "certifiers" / "n15" / "spectral.py"
            write_text(script, 'if __name__ == "__main__":\n    print("status:", "CERTIFIED")\n')
            result = run_script(repo, "verify_one.py", "--n", "15", "--method", "spectral")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_replay_of_a_gutted_certifier_fails(self) -> None:
        """The proof is skipped but every printed line is kept, values included."""
        with tempfile.TemporaryDirectory() as directory:
            repo = copy_repository(Path(directory))
            script = repo / "certifiers" / "n15" / "spectral.py"
            replace_once(
                script,
                CERTIFY_CALL,
                f"    result = certify() if False else {FAKE_RESULT}\n",
            )
            result = run_script(repo, "verify_one.py", "--n", "15", "--method", "spectral")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


class FreshReplayValidatorRejectsFakeLogs(unittest.TestCase):
    """P1-B, on the validator path, using a real replay directory."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.replay = shared_quick_replay()

    def mutated_replay(self, directory: Path, prefix: str, replacement: str) -> Path:
        copy = directory / "replay"
        shutil.copytree(self.replay, copy)
        log = copy / "n15_spectral.stdout.txt"
        text = read_text(log)
        lines = [line for line in text.splitlines() if line.startswith(prefix)]
        self.assertEqual(len(lines), 1)
        write_text(log, text.replace(lines[0], replacement))
        return copy

    def validate(self, replay: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "validate_replay_output.py"), str(replay), *extra],
            capture_output=True,
            text=True,
            timeout=900,
        )

    def test_an_unmodified_replay_validates(self) -> None:
        result = self.validate(self.replay)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("proof_output_verified", result.stdout)

    def test_status_only_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "replay"
            shutil.copytree(self.replay, copy)
            write_text(copy / "n15_spectral.stdout.txt", "status: CERTIFIED\n")
            result = self.validate(copy)
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_leaf_bound_zeroed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = self.mutated_replay(Path(directory), "minimum_leaf_lower_bound_decimal:",
                                       "minimum_leaf_lower_bound_decimal: 0")
            result = self.validate(copy)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("below the certified target", result.stdout)

    def test_splits_not_a_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = self.mutated_replay(Path(directory), "splits:", "splits: nonsense")
            result = self.validate(copy)
        self.assertEqual(result.returncode, 1, result.stdout)


class HistoricalEvidenceIsReadStrictly(unittest.TestCase):
    """P1-C. The stored logs were checked for a status and little else."""

    def semantic_check(self, mutate) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            repo = copy_repository(Path(directory))
            mutate(repo)
            return run_script(repo, "check_semantic_consistency.py")

    def test_unmodified_evidence_passes(self) -> None:
        result = run_script(REPO_ROOT, "check_semantic_consistency.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("replay_measurements_verified=88", result.stdout)
        self.assertIn("saved_replay_values_verified=88", result.stdout)

    def test_leaf_bound_zeroed_in_a_historical_log(self) -> None:
        def mutate(repo: Path) -> None:
            log = repo / "evidence/full-cleanroom-replay/logs/n07_spectral.stdout.txt"
            text = read_text(log)
            line = next(l for l in text.splitlines() if l.startswith("minimum_leaf_lower_bound_decimal:"))
            write_text(log, text.replace(line, "minimum_leaf_lower_bound_decimal: 0"))

        result = self.semantic_check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("below the certified target", result.stdout)

    def test_result_table_split_count_must_be_an_integer(self) -> None:
        def mutate(repo: Path) -> None:
            for name in ("certified-results.csv", "certified-results.json"):
                path = repo / "data" / name
                replace_once(path, "3645", "nonsense")

        result = self.semantic_check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a canonical non-negative integer", result.stdout)

    def test_record_measurements_must_be_integers(self) -> None:
        def mutate(repo: Path) -> None:
            path = repo / "evidence/full-cleanroom-replay/PUBLIC_REPO_FULL_REPLAY.json"
            payload = json.loads(read_text(path))
            for record in payload["results"]:
                if record["n"] == 7 and record["method"] == "spectral":
                    record["maximum_depth"] = "-1"
            write_text(path, json.dumps(payload, indent=2) + "\n")

        result = self.semantic_check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("maximum_depth", result.stdout)

    def test_saved_replay_upper_value_must_reproduce(self) -> None:
        def mutate(repo: Path) -> None:
            path = repo / "evidence/saved-replays/n15/spectral.txt"
            text = read_text(path)
            line = next(l for l in text.splitlines() if l.startswith("witness_value_upper_bound_decimal:"))
            write_text(path, text.replace(line, line[:-1] + ("8" if line[-1] != "8" else "7")))

        result = self.semantic_check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not reproduce the exact potential", result.stdout)


class FrozenCorpusBaseline(unittest.TestCase):
    """P1-D. SHA256SUMS is regenerated with the repository; this list is not."""

    def check(self, mutate=None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            repo = copy_repository(Path(directory))
            if mutate is not None:
                mutate(repo)
            return subprocess.run(
                [sys.executable, "-B", str(REPO_ROOT / "scripts" / "check_frozen_corpus.py"),
                 "--root", str(repo), "--quiet"],
                capture_output=True, text=True, timeout=900,
            )

    def test_the_repository_matches_its_baseline(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "check_frozen_corpus.py")],
            capture_output=True, text=True, timeout=900,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("agreeing_files=531", result.stdout)
        self.assertIn("git_anchor=verified", result.stdout)

    def test_an_unmodified_copy_passes(self) -> None:
        self.assertEqual(self.check().returncode, 0)

    def test_certifier_byte_change(self) -> None:
        def mutate(repo: Path) -> None:
            path = repo / "certifiers/n15/spectral.py"
            path.write_bytes(path.read_bytes() + b"\n")

        result = self.check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("certifiers/n15/spectral.py", result.stderr)

    def test_configuration_byte_change(self) -> None:
        def mutate(repo: Path) -> None:
            path = repo / "data/configurations/n15/coordinates.csv"
            path.write_bytes(path.read_bytes() + b"\n")

        result = self.check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("data/configurations/n15/coordinates.csv", result.stderr)

    def test_historical_evidence_byte_change(self) -> None:
        def mutate(repo: Path) -> None:
            path = repo / "evidence/full-cleanroom-replay/logs/n07_spectral.stdout.txt"
            path.write_bytes(path.read_bytes() + b"\n")

        result = self.check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("changed: evidence/full-cleanroom-replay/logs/n07_spectral.stdout.txt", result.stderr)

    def test_extra_file_under_a_frozen_root(self) -> None:
        def mutate(repo: Path) -> None:
            (repo / "certifiers/n15/extra.py").write_text("print('hello')\n", encoding="utf-8")

        result = self.check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unlisted: certifiers/n15/extra.py", result.stderr)

    def test_deleted_frozen_file(self) -> None:
        def mutate(repo: Path) -> None:
            (repo / "certifiers/n15/spectral.py").unlink()

        result = self.check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing: certifiers/n15/spectral.py", result.stderr)

    def test_a_proof_skipping_certifier_with_reconciled_hashes(self) -> None:
        """The whole point: every other check accepted this."""
        def mutate(repo: Path) -> None:
            replace_once(repo / "certifiers/n15/spectral.py", CERTIFY_CALL,
                         f"    result = certify() if False else {FAKE_RESULT}\n")
            subprocess.run([sys.executable, "-B", "scripts/regenerate_manifest.py"],
                           cwd=repo, capture_output=True, text=True, timeout=900)

        result = self.check(mutate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("certifiers/n15/spectral.py", result.stderr)

    def test_baseline_rejects_an_unsafe_or_malformed_list(self) -> None:
        baseline = REPO_ROOT / "data" / "frozen-corpus-v1.0.1.sha256"
        original = baseline.read_text(encoding="utf-8")
        entry = next(line for line in original.splitlines() if not line.startswith("#"))
        digest, path = entry.split("  ", 1)
        cases = {
            "duplicate path": original + f"\n{digest}  {path}\n",
            "path traversal": original.replace(entry, f"{digest}  ../outside.txt", 1),
            "absolute path": original.replace(entry, f"{digest}  /etc/passwd", 1),
            "outside the frozen roots": original.replace(entry, f"{digest}  README.md", 1),
            "short digest": original.replace(entry, f"{digest[:-1]}  {path}", 1),
            "wrong file count": original.replace("# file-count: 531", "# file-count: 530", 1),
        }
        for label, text in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                candidate = Path(directory) / "baseline.sha256"
                candidate.write_text(text, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(REPO_ROOT / "scripts" / "check_frozen_corpus.py"),
                     "--baseline", str(candidate), "--quiet"],
                    capture_output=True, text=True, timeout=900,
                )
                self.assertEqual(result.returncode, 2, f"{label}: {result.stdout} {result.stderr}")


class ReplayProvenanceSchema(unittest.TestCase):
    """P2-A. The summary's own account of what it ran, and against what."""

    @classmethod
    def setUpClass(cls) -> None:
        _, cls.replay = shared_quick_replay()

    def validate(self, replay: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "validate_replay_output.py"), str(replay), *extra],
            capture_output=True, text=True, timeout=900,
        )

    def with_summary(self, directory: Path, **changes) -> Path:
        copy = directory / "replay"
        shutil.copytree(self.replay, copy)
        path = copy / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        summary.update(changes)
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return copy

    def assert_rejected(self, fragment: str, *extra: str, **changes) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = self.with_summary(Path(directory), **changes)
            result = self.validate(copy, *extra)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(fragment, result.stdout)

    def test_the_quick_replay_declares_the_quick_set(self) -> None:
        summary = json.loads((self.replay / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["selection"], "quick")
        self.assertEqual(summary["expected_configurations"], list(QUICK_NS))
        self.assertEqual(self.validate(self.replay).returncode, 0)

    def test_selection_relabelled_as_all(self) -> None:
        self.assert_rejected("which means configurations", selection="all")

    def test_quick_with_an_arbitrary_subset(self) -> None:
        self.assert_rejected(
            "which means configurations",
            expected_configurations=[14, 15],
            expected_keys=[[n, m] for n in (14, 15) for m in METHODS],
        )

    def test_expect_all_requires_selection_all(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = self.with_summary(Path(directory))
            result = self.validate(copy, "--expect-all")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--expect-all requires selection 'all'", result.stdout)

    def test_commit_must_be_a_full_lowercase_hex_id(self) -> None:
        # A literal with hex letters in it: the fixture repository is a copy
        # without .git, so its own source_git_commit is null and `.upper()` on
        # an all-digit id would not exercise the case rule at all.
        commit = "0123456789abcdef0123456789abcdef01234567"
        for label, value in (
            ("bogus", "bogus"),
            ("39 characters", commit[:39]),
            ("41 characters", commit + "0"),
            ("upper case", commit.upper()),
        ):
            with self.subTest(label=label):
                self.assert_rejected("expected null or 40 lowercase hex characters", source_git_commit=value)

    def test_timestamp_must_be_a_real_utc_instant(self) -> None:
        self.assert_rejected("is not a real UTC timestamp", generated_at_utc="2026-99-99T99:99:99Z")
        self.assert_rejected("is not a real UTC timestamp", generated_at_utc="2026-02-30T00:00:00Z")

    def test_expected_commit_must_match(self) -> None:
        self.assert_rejected("expected", "--expect-source-commit", "0" * 40)

    def test_expected_commit_is_checked_against_a_real_repository(self) -> None:
        """A clean temporary repository: the recorded commit must be its HEAD."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            (repo / "file.txt").write_text("content\n", encoding="utf-8")
            environment = {
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                "PATH": "/usr/bin:/bin:/usr/local/bin",
            }
            for command in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "x"]):
                if subprocess.run(command, cwd=repo, env=environment, capture_output=True).returncode != 0:
                    self.skipTest("git is not usable in this environment")
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, env=environment,
                                  capture_output=True, text=True).stdout.strip()

            copy = self.with_summary(base, source_git_commit=head, source_git_dirty=False)
            good = self.validate(copy, "--expect-source-commit", head, "--expect-source-clean")
            self.assertEqual(good.returncode, 0, good.stdout)
            self.assertIn("source_commit_verified", good.stdout)
            self.assertIn("source_clean_verified", good.stdout)

    def test_expect_source_clean_fails_on_a_dirty_source(self) -> None:
        self.assert_rejected("requires source_git_dirty=false", "--expect-source-clean", source_git_dirty=True)

    def test_local_evidence_may_be_dirty_without_the_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = self.with_summary(Path(directory), source_git_dirty=True)
            self.assertEqual(self.validate(copy).returncode, 0)


class SharedConstants(unittest.TestCase):
    """The writer and the validator must not keep separate copies."""

    def test_quick_selection_is_defined_once(self) -> None:
        source = (REPO_ROOT / "scripts" / "verify_all.py").read_text(encoding="utf-8")
        self.assertNotIn("QUICK_NS: tuple", source, "verify_all.py must import QUICK_NS, not redefine it")
        self.assertIn("QUICK_NS", source)


if __name__ == "__main__":
    unittest.main()
