"""Mutation tests for the third audit round.

Each test corrupts one thing and requires the relevant check to reject it *for
that reason*: the expected diagnostic is asserted, and every mutation asserts
that it was applied. The four representations of a replay — summary JSON,
summary CSV, per-job JSON and the logs — are each attacked separately, because
a check that only reads one of them cannot notice the others disagreeing.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import (  # noqa: E402
    copy_repository,
    load_json,
    read_text,
    replace_once,
    run_script,
    shared_quick_replay,
    write_text,
)
from support import MINIMAL_CERTIFIER  # noqa: E402

from certificate_lib import METHODS, ROOT, certifier_relpath  # noqa: E402

#: Round 4: a status line without the proof behind it is no longer a
#: successful run, so the stand-in certifiers here are real ones.
FAKE_CERTIFIER = MINIMAL_CERTIFIER


class ReplayFixture(unittest.TestCase):
    """One real quick replay per class, copied per test (see R3-P2-B)."""

    fixture_repo: Path
    fixture_replay: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_repo, cls.fixture_replay = shared_quick_replay()

    def replay_copy(self, temporary: Path) -> Path:
        destination = temporary / "replay"
        shutil.copytree(self.fixture_replay, destination)
        return destination

    def validate(self, replay: Path) -> "tuple[int, str]":
        result = run_script(self.fixture_repo, "validate_replay_output.py", str(replay))
        return result.returncode, result.stdout + result.stderr

    def assert_rejected(self, replay: Path, fragment: str) -> None:
        code, output = self.validate(replay)
        self.assertEqual(code, 1, f"the corruption was not detected:\n{output}")
        self.assertIn(fragment, output)


class SummaryCsvIsJoinedToJson(ReplayFixture):
    """R3-P1-A: every CSV cell must equal the corresponding JSON value."""

    def mutate_first_row(self, replay: Path, field: str, value: str) -> str:
        path = replay / "summary.csv"
        lines = read_text(path).split("\r\n")
        header = lines[0].split(",")
        row = lines[1].split(",")
        index = header.index(field)
        before = row[index]
        if before == value:
            raise AssertionError(f"{field} is already {value!r}; the mutation would be a no-op")
        row[index] = value
        lines[1] = ",".join(row)
        write_text(path, "\r\n".join(lines))
        self.assertIn(value, read_text(path))
        return before

    def test_untouched_replay_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            code, output = self.validate(replay)
            self.assertEqual(code, 0, output)
            self.assertIn("problems=0", output)

    def test_changing_only_certified_in_the_csv_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_first_row(replay, "certified", "False")
            self.assert_rejected(replay, "certified: csv 'False' != json 'True'")

    def test_changing_only_the_script_sha_in_the_csv_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_first_row(replay, "script_sha256", "0" * 64)
            self.assert_rejected(replay, "script_sha256: csv")

    def test_changing_a_non_key_field_while_keeping_keys_and_row_count_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_first_row(replay, "elapsed_seconds", "0.0")
            code, output = self.validate(replay)
            self.assertEqual(code, 1, output)
            self.assertIn("elapsed_seconds: csv '0.0'", output)
            self.assertNotIn("duplicate (n, method)", output)

    def test_reordering_the_csv_rows_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            path = replay / "summary.csv"
            lines = read_text(path).split("\r\n")
            body = [line for line in lines[1:] if line]
            self.assertGreater(len(body), 2)
            body[0], body[1] = body[1], body[0]
            write_text(path, "\r\n".join([lines[0], *body]) + "\r\n")
            self.assert_rejected(replay, "not in the canonical (n, method) order")


class FreshReplaySchema(ReplayFixture):
    """R3-P2-A: the summary and its records have an exact shape."""

    def mutate_summary(self, replay: Path, transform) -> None:
        path = replay / "summary.json"
        summary = load_json(path)
        transform(summary)
        write_text(path, json.dumps(summary, indent=2))

    def test_extra_summary_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s.update({"extra": 1}))
            self.assert_rejected(replay, "field set mismatch")

    def test_duplicate_expected_key_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s["expected_keys"].append(list(s["expected_keys"][0])))
            self.assert_rejected(replay, "expected_keys contains duplicate pairs")

    def test_bool_in_an_integer_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s.update({"verifier_count": True}))
            self.assert_rejected(replay, "verifier_count is True")

    def test_worker_count_below_one_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s.update({"worker_count": 0}))
            self.assert_rejected(replay, "worker_count is 0")

    def test_non_utc_timestamp_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s.update({"generated_at_utc": "2026-08-06 12:00:00"}))
            self.assert_rejected(replay, "not a real UTC timestamp")

    def test_elapsed_seconds_as_a_string_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s["results"][0].update({"elapsed_seconds": "1.0"}))
            self.assert_rejected(replay, "elapsed_seconds is '1.0'")

    def test_short_or_non_hex_script_sha_is_rejected(self) -> None:
        for value in ("0" * 63, "g" * 64, "A" * 64):
            with self.subTest(value=value[:4]), tempfile.TemporaryDirectory() as temporary:
                replay = self.replay_copy(Path(temporary))
                self.mutate_summary(replay, lambda s, v=value: s["results"][0].update({"script_sha256": v}))
                self.assert_rejected(replay, "script_sha256 is not 64 lowercase hex characters")

    def test_selection_outside_the_allowed_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s.update({"selection": "partial"}))
            self.assert_rejected(replay, "selection is 'partial'")

    def test_non_canonical_log_name_in_a_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            self.mutate_summary(replay, lambda s: s["results"][0].update({"stdout_log": "../elsewhere.txt"}))
            self.assert_rejected(replay, "stdout_log is '../elsewhere.txt'")


class HistoricalReplayIsJoinedToItsLogs(unittest.TestCase):
    """R3-P1-B: a record must be bound to its own log and its measurements."""

    def semantic(self, repo: Path) -> "tuple[int, str]":
        result = run_script(repo, "check_semantic_consistency.py")
        return result.returncode, result.stdout + result.stderr

    def assert_rejected(self, repo: Path, fragment: str) -> None:
        code, output = self.semantic(repo)
        self.assertEqual(code, 1, f"the corruption was not detected:\n{output}")
        self.assertIn(fragment, output)

    def edit_record(self, repo: Path, n: int, method: str, changes: dict) -> None:
        """Apply the same change to the aggregate JSON, the per-job meta and the CSV."""
        import csv
        import io

        base = repo / "evidence" / "full-cleanroom-replay"
        payload = load_json(base / "PUBLIC_REPO_FULL_REPLAY.json")
        record = next(r for r in payload["results"] if r["n"] == n and r["method"] == method)
        for field, value in changes.items():
            if record[field] == value:
                raise AssertionError(f"{field} is already {value!r}; the mutation would be a no-op")
            record[field] = value
        write_text(base / "PUBLIC_REPO_FULL_REPLAY.json", json.dumps(payload, indent=2))

        meta_path = base / "logs" / f"n{n:02d}_{method}.meta.json"
        meta = load_json(meta_path)
        meta.update(changes)
        write_text(meta_path, json.dumps(meta, indent=2))

        csv_path = base / "PUBLIC_REPO_FULL_REPLAY.csv"
        rows = list(csv.DictReader(io.StringIO(read_text(csv_path))))
        for row in rows:
            if row["n"] == str(n) and row["method"] == method:
                row.update({field: str(value) for field, value in changes.items()})
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        write_text(csv_path, buffer.getvalue())

    def test_untouched_evidence_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            code, output = self.semantic(repo)
            self.assertEqual(code, 0, output)
            self.assertIn("problems=0", output)

    def test_log_reassignment_with_a_falsified_split_count_is_rejected(self) -> None:
        """The independently reproduced Round 3 mutation, made fully consistent."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            self.edit_record(repo, 7, "spectral",
                             {"stdout_log": "logs/n08_spectral.stdout.txt", "splits": "999999"})
            regenerated = run_script(repo, "regenerate_certified_results.py", "--write")
            self.assertEqual(regenerated.returncode, 0, regenerated.stdout + regenerated.stderr)
            manifest = run_script(repo, "regenerate_manifest.py")
            self.assertEqual(manifest.returncode, 0, manifest.stdout + manifest.stderr)
            self.assert_rejected(repo, "stdout_log is 'logs/n08_spectral.stdout.txt'")

    def test_relative_path_outside_the_logs_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            self.edit_record(repo, 7, "spectral", {"stdout_log": "../logs/n07_spectral.stdout.txt"})
            self.assert_rejected(repo, "stdout_log is '../logs/n07_spectral.stdout.txt'")

    def test_bare_file_name_without_the_logs_prefix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            self.edit_record(repo, 7, "spectral", {"stdout_log": "n07_spectral.stdout.txt"})
            self.assert_rejected(repo, "stdout_log is 'n07_spectral.stdout.txt'")

    def test_changing_only_the_split_count_in_the_log_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            log = repo / "evidence" / "full-cleanroom-replay" / "logs" / "n07_spectral.stdout.txt"
            replace_once(log, "splits: 499", "splits: 500")
            self.assert_rejected(repo, "stdout splits='500'")

    def test_changing_only_the_maximum_depth_in_the_log_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            log = repo / "evidence" / "full-cleanroom-replay" / "logs" / "n07_spectral.stdout.txt"
            replace_once(log, "maximum_depth: 23", "maximum_depth: 24")
            self.assert_rejected(repo, "stdout maximum_depth='24'")

    def test_duplicate_key_in_per_job_metadata_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            meta = repo / "evidence" / "full-cleanroom-replay" / "logs" / "n07_spectral.meta.json"
            replace_once(meta, '  "n": 7,', '  "n": 7,\n  "n": 7,')
            self.assert_rejected(repo, "duplicate object key")

    def test_falsified_target_decimal_in_the_log_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            log = repo / "evidence" / "full-cleanroom-replay" / "logs" / "n07_spectral.stdout.txt"
            replace_once(log, "target_decimal: 35.9098", "target_decimal: 35.9099")
            self.assert_rejected(repo, "is not the certifier TARGET")


class SourceGitStateIsCapturedBeforeTheRun(unittest.TestCase):
    """R3-P1-C: provenance must describe the source tree, not the output."""

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available; this check cannot be verified in this environment")

    def build_repo(self, root: Path) -> Path:
        """A minimal repository with fast stand-in certifiers for the quick set."""
        repo = root / "repo"
        (repo / "scripts").mkdir(parents=True)
        for name in ("certificate_lib.py", "verifier_runner.py", "verify_all.py", "validate_replay_output.py"):
            shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
        from verify_all import QUICK_NS

        for n in QUICK_NS:
            directory = repo / "certifiers" / f"n{n:02d}"
            directory.mkdir(parents=True)
            for method in METHODS:
                (directory / f"{method}.py").write_text(FAKE_CERTIFIER, encoding="utf-8")
        for command in (
            ["git", "init", "-q", "."],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
            ["git", "add", "-A"],
            ["git", "commit", "-q", "-m", "init"],
        ):
            subprocess.run(command, cwd=repo, check=True, capture_output=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
        self.assertEqual(status.stdout.strip(), "", "the fixture repository is not clean")
        return repo

    def run_replay(self, repo: Path, output: Path) -> dict:
        result = subprocess.run(
            [sys.executable, "-B", str(repo / "scripts" / "verify_all.py"),
             "--quick", "--jobs", "1", "--output-dir", str(output)],
            cwd=repo, capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((output / "summary.json").read_text(encoding="utf-8"))

    def test_output_written_inside_a_clean_repository_is_not_reported_as_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.build_repo(Path(temporary))
            summary = self.run_replay(repo, repo / "ci-output")

            after = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
            self.assertNotEqual(after.stdout.strip(), "", "the output directory should make the tree dirty afterwards")
            self.assertIs(summary["source_git_dirty"], False)
            self.assertIsInstance(summary["source_git_commit"], str)
            self.assertEqual(len(summary["source_git_commit"]), 40)

    def test_a_tree_modified_before_the_run_is_reported_as_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.build_repo(Path(temporary))
            tracked = repo / "certifiers" / "n14" / "spectral.py"
            tracked.write_text(FAKE_CERTIFIER + "# modified\n", encoding="utf-8")  # dirties the tree
            summary = self.run_replay(repo, repo / "ci-output")
            self.assertIs(summary["source_git_dirty"], True)

    def test_absent_git_metadata_gives_null_rather_than_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.build_repo(Path(temporary))
            shutil.rmtree(repo / ".git")
            summary = self.run_replay(repo, repo / "ci-output")
            self.assertIsNone(summary["source_git_commit"])
            self.assertIsNone(summary["source_git_dirty"])


if __name__ == "__main__":
    unittest.main()
