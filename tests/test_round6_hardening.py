"""Round 6: raw Git objects, file type and mode, and unique baseline headers.

Round 5 named the release commit as the anchor and read it with plain ``git``.
``git replace`` makes that insufficient: a repository can serve different bytes
under an unchanged object name. Round 5 also compared content only, so a frozen
file swapped for a symlink to an identical copy, or given the executable bit,
read as unchanged; and its baseline parser took the last value of a repeated
header.

Every test here failed against the Round 5 implementation. Mutations are applied
to copies and to temporary clones; nothing writes to this repository.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import (  # noqa: E402
    GIT_ENVIRONMENT,
    REPO_ROOT,
    copy_release_clone,
    git_available,
    replace_once,
)

import check_frozen_corpus as frozen  # noqa: E402

PROBE = "certifiers/n15/spectral.py"
BASELINE_NAME = "data/frozen-corpus-v1.0.1.sha256"
ANCHORED = (
    "--expect-base-version", frozen.BASE_VERSION,
    "--expect-base-commit", frozen.BASE_COMMIT,
    "--require-git-anchor",
)
UNANCHORED = ("--expect-base-version", frozen.BASE_VERSION, "--expect-base-commit", frozen.BASE_COMMIT)


class FrozenCorpusTestCase(unittest.TestCase):
    def setUp(self) -> None:
        if not git_available():
            self.skipTest("git is not available; the release objects cannot be read")

    def environment(self, tree: Path) -> dict[str, str]:
        return {**GIT_ENVIRONMENT, "HOME": str(tree)}

    def git(self, tree: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=tree, env=self.environment(tree),
            capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def run_check(self, tree: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "check_frozen_corpus.py"),
             "--root", str(tree), "--baseline", str(tree / BASELINE_NAME), *extra],
            cwd=tree, env=self.environment(tree), capture_output=True, text=True, timeout=900,
        )

    def set_baseline_digest(self, tree: Path, relative: str, digest: str) -> None:
        path = tree / BASELINE_NAME
        lines = path.read_text(encoding="utf-8").splitlines()
        replaced = False
        for index, line in enumerate(lines):
            if line.endswith(f"  {relative}"):
                lines[index] = f"{digest}  {relative}"
                replaced = True
        self.assertTrue(replaced, f"baseline does not list {relative}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ObjectReplacementIsIgnoredAndReported(FrozenCorpusTestCase):
    """R6-P1-A. ``git replace`` served different bytes under the same name."""

    def make_commit_replacement(self, tree: Path) -> str:
        target = tree / PROBE
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        self.git(tree, "add", "-A")
        self.git(tree, "commit", "-q", "-m", "B")
        replacement = self.git(tree, "rev-parse", "HEAD").strip()
        self.git(tree, "replace", frozen.BASE_COMMIT, replacement)
        self.set_baseline_digest(tree, PROBE, hashlib.sha256(target.read_bytes()).hexdigest())
        return replacement

    def make_blob_replacement(self, tree: Path) -> None:
        original = self.git(tree, "rev-parse", f"{frozen.BASE_COMMIT}:{PROBE}").strip()
        tampered = (tree / PROBE).read_bytes() + b"\n# tampered blob\n"
        scratch = tree / "tampered-source"
        scratch.write_bytes(tampered)
        new = self.git(tree, "hash-object", "-w", str(scratch)).strip()
        scratch.unlink()
        self.git(tree, "replace", original, new)
        (tree / PROBE).write_bytes(tampered)
        self.set_baseline_digest(tree, PROBE, hashlib.sha256(tampered).hexdigest())

    def test_commit_replacement_is_refused_when_anchored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            self.make_commit_replacement(tree)
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("object replacement is configured", result.stderr)

    def test_commit_replacement_still_reads_the_original_bytes(self) -> None:
        """The other half: even unanchored, the raw read sees the release."""
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            self.make_commit_replacement(tree)
            result = self.run_check(tree, *UNANCHORED)
            inventory, _ = frozen.release_inventory(tree, frozen.BASE_COMMIT, frozen.BASE_VERSION)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("release commit vs baseline", result.stderr)
        self.assertIn("release commit vs working tree", result.stderr)
        self.assertIn("refs/replace/ exists", result.stderr)
        untouched = hashlib.sha256((REPO_ROOT / PROBE).read_bytes()).hexdigest()
        self.assertEqual(inventory[PROBE].digest, untouched,
                         "the raw read must return the v1.0.1 bytes, not the replacement")

    def test_blob_replacement_is_refused_when_anchored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            self.make_blob_replacement(tree)
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("object replacement is configured", result.stderr)

    def test_blob_replacement_still_reads_the_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            self.make_blob_replacement(tree)
            result = self.run_check(tree, *UNANCHORED)
            inventory, _ = frozen.release_inventory(tree, frozen.BASE_COMMIT, frozen.BASE_VERSION)
        self.assertEqual(result.returncode, 1, result.stdout)
        untouched = hashlib.sha256((REPO_ROOT / PROBE).read_bytes()).hexdigest()
        self.assertEqual(inventory[PROBE].digest, untouched)

    def test_replacement_is_not_taken_from_the_environment(self) -> None:
        """GIT_REPLACE_REF_BASE must not survive into the Git invocations."""
        environment = frozen.git_environment()
        self.assertEqual(environment.get("GIT_NO_REPLACE_OBJECTS"), "1")
        self.assertNotIn("GIT_REPLACE_REF_BASE", environment)
        previous = os.environ.get("GIT_REPLACE_REF_BASE")
        os.environ["GIT_REPLACE_REF_BASE"] = "refs/elsewhere/"
        try:
            self.assertNotIn("GIT_REPLACE_REF_BASE", frozen.git_environment())
        finally:
            if previous is None:
                os.environ.pop("GIT_REPLACE_REF_BASE", None)
            else:
                os.environ["GIT_REPLACE_REF_BASE"] = previous

    def test_a_clean_clone_has_no_replacements_and_agrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            self.assertEqual(frozen.replacement_refs(tree), [])
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release_blobs=531", result.stdout)
        self.assertIn("agreeing_files=531", result.stdout)

    def test_missing_base_commit_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            shutil.rmtree(tree / ".git")
            for command in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "x"]):
                subprocess.run(command, cwd=tree, env=self.environment(tree),
                               capture_output=True, timeout=300)
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("git anchor unavailable", result.stderr)


class BatchResponsesAreChecked(FrozenCorpusTestCase):
    """R6-P1 §3.2. A response must be the one that was asked for."""

    def test_a_non_blob_object_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            tree_oid = self.git(tree, "rev-parse", f"{frozen.BASE_COMMIT}^{{tree}}").strip()
            with self.assertRaises(frozen.GitAnchorError) as caught:
                frozen._batch_digests(tree, [tree_oid])
        self.assertIn("came back as a tree", str(caught.exception))

    def test_a_missing_object_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            with self.assertRaises(frozen.GitAnchorError) as caught:
                frozen._batch_digests(tree, ["0" * 40])
        self.assertIn("missing", str(caught.exception))

    def test_a_real_batch_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            oid = self.git(tree, "rev-parse", f"{frozen.BASE_COMMIT}:{PROBE}").strip()
            digests = frozen._batch_digests(tree, [oid, oid])
        self.assertEqual(len(digests), 2)
        self.assertEqual(digests[0], digests[1])
        self.assertEqual(digests[0], hashlib.sha256((REPO_ROOT / PROBE).read_bytes()).hexdigest())


class FileTypeAndModeAreAnchored(FrozenCorpusTestCase):
    """R6-P2-B. Identical bytes are not the same file."""

    def test_same_byte_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            outside = tree / ".probe-copy"
            shutil.copy2(tree / PROBE, outside)
            (tree / PROBE).unlink()
            (tree / PROBE).symlink_to(os.path.relpath(outside, (tree / PROBE).parent))
            self.assertTrue((tree / PROBE).is_file(), "is_file() follows the link, which was the defect")
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("symbolic link", result.stderr)
        self.assertIn(PROBE, result.stderr)

    def test_a_frozen_root_that_is_a_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            elsewhere = tree / ".moved-certifiers"
            (tree / "certifiers").rename(elsewhere)
            (tree / "certifiers").symlink_to(elsewhere.name)
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("frozen root certifiers is a symbolic link", result.stderr)

    def test_executable_bit_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            path = tree / PROBE
            before = stat.S_IMODE(path.lstat().st_mode)
            path.chmod(before | 0o111)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                hashlib.sha256((REPO_ROOT / PROBE).read_bytes()).hexdigest(),
                "the bytes must be untouched, so only the mode can be the difference",
            )
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("mode changed", result.stderr)
        self.assertIn("expected 100644, found 100755", result.stderr)

    def test_a_byte_change_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            path = tree / PROBE
            path.write_bytes(path.read_bytes() + b"\n")
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("changed: " + PROBE, result.stderr)

    def test_a_fifo_under_a_frozen_root_is_reported(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo is not available on this platform")
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            os.mkfifo(tree / "certifiers" / "n15" / "pipe")
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FIFO, not a regular file", result.stderr)

    def test_the_release_mode_distribution(self) -> None:
        """The allow-list is only meaningful while this stays true."""
        inventory, notes = frozen.release_inventory(REPO_ROOT)
        self.assertEqual(len(inventory), 531)
        modes = {}
        for entry in inventory.values():
            modes[entry.mode] = modes.get(entry.mode, 0) + 1
        self.assertEqual(modes, {"100644": 531})
        self.assertEqual(notes["modes"], "531 x 100644, 0 x 100755")

    def test_the_working_tree_has_no_symlinks_or_special_files(self) -> None:
        inventory, problems = frozen.working_tree_inventory(REPO_ROOT)
        self.assertEqual(problems, [])
        self.assertEqual(len(inventory), 531)
        self.assertTrue(all(entry.mode == "100644" for entry in inventory.values()))


class BaselineHeadersAreUnique(FrozenCorpusTestCase):
    """R6-P2-C. A repeated header must not be resolved by last-one-wins."""

    def parse(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.sha256"
            path.write_text(text, encoding="utf-8")
            return frozen.parse_baseline(path)

    def setUp(self) -> None:
        super().setUp()
        self.original = (REPO_ROOT / BASELINE_NAME).read_text(encoding="utf-8")

    def test_the_real_baseline_parses(self) -> None:
        entries, header = self.parse(self.original)
        self.assertEqual(len(entries), 531)
        self.assertEqual(header["base-version"], frozen.BASE_VERSION)
        self.assertEqual(header["base-commit"], frozen.BASE_COMMIT)
        self.assertTrue(all(entry.mode is None for entry in entries.values()),
                        "the baseline carries digests only; modes come from the release objects")

    def test_duplicate_headers_are_refused(self) -> None:
        cases = {
            "base-version": ("# base-version: v1.0.1", "# base-version: v9.9.9\n# base-version: v1.0.1"),
            "base-commit": (f"# base-commit: {frozen.BASE_COMMIT}",
                            f"# base-commit: {'0' * 40}\n# base-commit: {frozen.BASE_COMMIT}"),
            "file-count": ("# file-count: 531", "# file-count: 1\n# file-count: 531"),
        }
        for name, (old, new) in cases.items():
            with self.subTest(header=name):
                self.assertEqual(self.original.count(old), 1)
                with self.assertRaises(frozen.BaselineError) as caught:
                    self.parse(self.original.replace(old, new, 1))
                self.assertIn("appears twice", str(caught.exception))

    def test_a_missing_header_is_refused(self) -> None:
        for old in ("# base-version: v1.0.1", f"# base-commit: {frozen.BASE_COMMIT}", "# file-count: 531"):
            with self.subTest(header=old):
                with self.assertRaises(frozen.BaselineError) as caught:
                    self.parse(self.original.replace(old + "\n", "", 1))
                self.assertIn("does not declare", str(caught.exception))

    def test_a_malformed_known_header_is_refused(self) -> None:
        cases = {
            "commit is not hex": (f"# base-commit: {frozen.BASE_COMMIT}", "# base-commit: not-a-commit"),
            "commit is upper case": (f"# base-commit: {frozen.BASE_COMMIT}",
                                     f"# base-commit: {frozen.BASE_COMMIT.upper()}"),
            "file-count is not a number": ("# file-count: 531", "# file-count: many"),
            "file-count disagrees": ("# file-count: 531", "# file-count: 530"),
        }
        for label, (old, new) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(frozen.BaselineError):
                    self.parse(self.original.replace(old, new, 1))

    def test_prose_comments_may_repeat(self) -> None:
        """Only the structured headers are constrained."""
        entries, _ = self.parse(self.original.replace("# base-version: v1.0.1",
                                                      "# note: one\n# note: two\n# base-version: v1.0.1", 1))
        self.assertEqual(len(entries), 531)


class TheRepositoryItselfIsAnchored(FrozenCorpusTestCase):
    def test_anchored_check_passes_here(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "check_frozen_corpus.py"), *ANCHORED],
            capture_output=True, text=True, timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("git_anchor=verified", result.stdout)
        self.assertIn("release_modes=531 x 100644, 0 x 100755", result.stdout)

    def test_no_replacement_is_configured_here(self) -> None:
        self.assertEqual(frozen.replacement_refs(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
