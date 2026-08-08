"""Tests for the canonical release-asset builder and the release documents.

Every test builds its own throwaway Git repository in a temporary directory, so
nothing here can touch the real corpus, and no test needs the network or a
GitHub token. The fixture carries the real manifest machinery -- the policy
loader, the generator and the verifier -- because the point of the archive
self-check is that the archive verifies itself with the same code the repository
ships.

The determinism tests assert what they measure: repeated builds of the same
commit, with the same ``git`` binary, on this machine, under three different
``TZ`` values. Cross-platform and cross-git-version reproducibility is not
asserted anywhere.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from support import REPO_ROOT, SCRIPTS  # noqa: E402

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_release_assets as builder  # noqa: E402

BUILDER = SCRIPTS / "build_release_assets.py"
VERSION = "1.0.2"
NAME = f"{builder.PROJECT}-v{VERSION}"
ASSET = f"{NAME}.zip"
SIDECAR = f"{ASSET}.sha256"
RECORD = builder.RECORD_NAME
EXPECTED_OUTPUT = sorted([ASSET, SIDECAR, RECORD])

FIXTURE_POLICY = {
    "schema_version": 1,
    "manifest_path": "SHA256SUMS",
    "purpose": "fixture policy for the release-asset builder tests",
    "include_roots": ["scripts"],
    "include_files": ["MANIFEST_POLICY.json", "VERSION"],
    "exclude_files": ["SHA256SUMS"],
    "exclude_globs": ["**/__pycache__/**", "**/*.pyc", "**/.DS_Store"],
    "path_order": "lexicographic-posix",
}

# The archive runs its own self-checks, and the real repository ships two of
# them. A fixture that omitted `check_release.py` produced a record the
# attestation used to accept, so the fixture carries a stand-in rather than the
# production CLI growing a test-only mode. It checks something real and cheap.
CHECK_RELEASE_STANDIN = '''#!/usr/bin/env python3
"""Stand-in for the repository's release check, sized for a fixture archive."""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"[0-9]+\\.[0-9]+\\.[0-9]+", version):
    print(f"VERSION is not a release version: {version!r}")
    sys.exit(1)
if not (root / "scripts" / "verify_manifest.py").is_file():
    print("scripts/verify_manifest.py is missing")
    sys.exit(1)
scripts = sorted(p.name for p in (root / "scripts").glob("*.py"))
print(f"version={version} scripts={len(scripts)} issues=0")
'''

FAILING_CHECK_RELEASE = '''#!/usr/bin/env python3
print("issues=1")
raise SystemExit(1)
'''


def git(*arguments: str, cwd: Path, environment: dict | None = None) -> str:
    env = dict(environment or builder.git_environment())
    env.setdefault("GIT_AUTHOR_NAME", "fixture")
    env.setdefault("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "fixture")
    env.setdefault("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
    completed = subprocess.run(["git", "-C", str(cwd), *arguments],
                               capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        raise AssertionError(f"git {' '.join(arguments)} failed: {completed.stderr}")
    return completed.stdout.strip()


def build_fixture_repository(root: Path, version: str = VERSION,
                             extra: dict[str, str] | None = None,
                             builder_source: bytes | None = None,
                             check_release: str | None = CHECK_RELEASE_STANDIN) -> str:
    """Create a small but genuine repository and return its commit id.

    The fixture carries the *actual* builder bytes at
    ``scripts/build_release_assets.py``, because the builder now refuses to
    archive a commit whose builder blob is not the script that is running.
    ``builder_source=None`` means "the real one"; pass bytes to make them differ.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir()
    for script in ("manifest_policy.py", "verify_manifest.py", "regenerate_manifest.py"):
        shutil.copy2(REPO_ROOT / "scripts" / script, root / "scripts" / script)
    (root / "scripts" / "build_release_assets.py").write_bytes(
        BUILDER.read_bytes() if builder_source is None else builder_source)
    if check_release is not None:
        (root / "scripts" / "check_release.py").write_text(check_release, encoding="utf-8")
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (root / "MANIFEST_POLICY.json").write_text(json.dumps(FIXTURE_POLICY, indent=2) + "\n",
                                               encoding="utf-8")
    for name, body in (extra or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    subprocess.run([sys.executable, "-B", "scripts/regenerate_manifest.py"],
                   cwd=root, check=True, capture_output=True)
    git("init", "-q", "-b", "main", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "fixture", cwd=root)
    return git("rev-parse", "HEAD", cwd=root)


def run_builder(repository: Path, output_dir: Path, environment: dict | None = None,
                script: Path | None = None, **overrides) -> subprocess.CompletedProcess[str]:
    arguments = {
        "--version": VERSION,
        "--target": overrides.pop("target", None) or git("rev-parse", "HEAD", cwd=repository),
        "--output-dir": str(output_dir),
        "--repository": str(repository),
    }
    for key, value in list(overrides.items()):
        arguments[f"--{key.replace('_', '-')}"] = str(value)
    argv: list[str] = []
    for key, value in arguments.items():
        argv += [key, str(value)]
    env = dict(os.environ)
    if environment:
        env.update(environment)
    return subprocess.run([sys.executable, "-B", str(script or BUILDER), *argv],
                          capture_output=True, text=True, env=env)


def record_of(output_dir: Path) -> dict:
    return json.loads((output_dir / RECORD).read_text(encoding="utf-8"))


class BuilderRefusals(unittest.TestCase):
    """Every precondition must refuse, and refuse without creating the destination."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-test-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)
        self.out = self.scratch / "out"

    def assert_refused(self, completed: subprocess.CompletedProcess[str], fragment: str) -> None:
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn(fragment, completed.stderr)
        self.assertFalse(self.out.exists(), "a refusal must not create the output directory")

    def assert_no_staging_left(self) -> None:
        leftovers = [p.name for p in self.scratch.iterdir() if p.name.startswith(".out.staging-")]
        self.assertEqual(leftovers, [], f"staging directories left behind: {leftovers}")

    def test_malformed_target_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, target="not-a-sha"),
                            "40-character lowercase hex")

    def test_short_target_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, target=self.commit[:12]),
                            "40-character lowercase hex")

    def test_uppercase_target_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, target=self.commit.upper()),
                            "40-character lowercase hex")

    def test_target_that_is_not_a_commit_is_refused(self) -> None:
        tree = git("rev-parse", "HEAD^{tree}", cwd=self.repo)
        self.assert_refused(run_builder(self.repo, self.out, target=tree), "not a commit")

    def test_version_mismatch_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, version="9.9.9"),
                            "does not match VERSION")

    def test_bad_semver_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, version="1.0"), "look like")

    def test_tag_name_not_matching_the_version_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, require_tag="v9.9.9",
                                        expect_asset_sha256="a" * 64), "must be 'v1.0.2'")

    def test_missing_tag_is_refused(self) -> None:
        self.assert_refused(run_builder(self.repo, self.out, require_tag=f"v{VERSION}",
                                        expect_asset_sha256="a" * 64), "does not exist")

    def test_a_branch_of_the_same_name_is_not_a_tag(self) -> None:
        """Measured on an earlier builder: exit 0, assets written, no tag in existence."""
        git("branch", f"v{VERSION}", self.commit, cwd=self.repo)
        completed = run_builder(self.repo, self.out, require_tag=f"v{VERSION}",
                                expect_asset_sha256="a" * 64)
        self.assert_refused(completed, "does not exist")
        self.assertIn("branch or other revision", completed.stderr)

    def test_dirty_tree_is_refused(self) -> None:
        (self.repo / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        self.assert_refused(run_builder(self.repo, self.out), "working tree is not clean")

    def test_untracked_file_counts_as_dirty(self) -> None:
        (self.repo / "stray.txt").write_text("stray\n", encoding="utf-8")
        self.assert_refused(run_builder(self.repo, self.out), "working tree is not clean")

    def test_local_git_attributes_are_refused(self) -> None:
        info = self.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text("VERSION export-ignore\n", encoding="utf-8")
        self.assert_refused(run_builder(self.repo, self.out), ".git/info/attributes has content")

    def test_comment_only_git_attributes_are_allowed(self) -> None:
        """Control: the refusal is about content, not about the file existing."""
        info = self.repo / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text("# nothing here\n\n", encoding="utf-8")
        self.assertEqual(run_builder(self.repo, self.out).returncode, builder.EXIT_OK)

    def test_replace_ref_is_refused(self) -> None:
        (self.repo / "scripts" / "extra.py").write_text("# other\n", encoding="utf-8")
        subprocess.run([sys.executable, "-B", "scripts/regenerate_manifest.py"],
                       cwd=self.repo, check=True, capture_output=True)
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "other", cwd=self.repo)
        other = git("rev-parse", "HEAD", cwd=self.repo)
        git("replace", other, self.commit, cwd=self.repo)
        self.assert_refused(run_builder(self.repo, self.out, target=other), "refs/replace")

    def test_output_inside_repository_is_refused(self) -> None:
        completed = run_builder(self.repo, self.repo / "dist")
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("inside the repository", completed.stderr)
        self.assertFalse((self.repo / "dist").exists())

    def test_existing_output_directory_is_refused(self) -> None:
        """The directory is published by one rename, so it must not exist first."""
        self.out.mkdir()
        completed = run_builder(self.repo, self.out)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("already exists", completed.stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [])

    def test_existing_empty_output_directory_is_still_refused(self) -> None:
        self.out.mkdir()
        (self.out / "leftover.txt").write_text("x\n", encoding="utf-8")
        completed = run_builder(self.repo, self.out)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertEqual((self.out / "leftover.txt").read_text(), "x\n")

    def test_missing_output_parent_is_refused(self) -> None:
        completed = run_builder(self.repo, self.scratch / "absent" / "out")
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("parent directory does not exist", completed.stderr)

    def test_bad_expected_digest_is_refused(self) -> None:
        completed = run_builder(self.repo, self.out, expect_asset_sha256="nope")
        self.assert_refused(completed, "64 lowercase hex")

    def test_wrong_expected_digest_is_refused(self) -> None:
        completed = run_builder(self.repo, self.out, expect_asset_sha256="a" * 64)
        self.assert_refused(completed, "does not match --expect-asset-sha256")
        self.assert_no_staging_left()

    def test_refusals_leave_no_staging_directory(self) -> None:
        run_builder(self.repo, self.out, expect_asset_sha256="b" * 64)
        self.assert_no_staging_left()


class DeterministicEnvironment(unittest.TestCase):
    """The environment is part of the output, so it is constructed, not inherited."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-env-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)

    def digest_under(self, timezone_name: str) -> str:
        out = self.scratch / f"out-{timezone_name.replace('/', '_')}"
        completed = run_builder(self.repo, out, environment={"TZ": timezone_name},
                                target=self.commit)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        return hashlib.sha256((out / ASSET).read_bytes()).hexdigest()

    def test_three_timezones_produce_one_digest(self) -> None:
        """Measured on an earlier builder: UTC and Kiritimati differed."""
        digests = {tz: self.digest_under(tz)
                   for tz in ("UTC", "Pacific/Kiritimati", "America/Los_Angeles")}
        self.assertEqual(len(set(digests.values())), 1, digests)

    def test_the_timezone_genuinely_affects_git_archive(self) -> None:
        """Control: without the fix there would be nothing to fix.

        If this ever starts passing with equal digests, `git archive` has
        changed and the pinning below is no longer load-bearing.
        """
        raw = {}
        for timezone_name in ("UTC", "Pacific/Kiritimati"):
            environment = dict(os.environ)
            environment["TZ"] = timezone_name
            archive = self.scratch / f"raw-{timezone_name.replace('/', '_')}.zip"
            subprocess.run(["git", "-C", str(self.repo), "archive", "--format=zip", "-9",
                            "--prefix=x/", f"--output={archive}", self.commit],
                           check=True, capture_output=True, env=environment)
            raw[timezone_name] = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertNotEqual(raw["UTC"], raw["Pacific/Kiritimati"])

    def test_environment_is_an_allow_list(self) -> None:
        environment = builder.git_environment()
        self.assertEqual(environment["TZ"], "UTC")
        self.assertEqual(environment["LC_ALL"], "C")
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
                     "GIT_REPLACE_REF_BASE", "GIT_ATTR_SOURCE"):
            with self.subTest(variable=name):
                self.assertNotIn(name, environment)

    def test_injected_git_routing_is_ignored(self) -> None:
        """GIT_DIR pointing elsewhere must not change which repository is archived."""
        other = self.scratch / "other"
        build_fixture_repository(other, extra={"OTHER.md": "# other\n"})
        clean = self.scratch / "out-clean"
        self.assertEqual(run_builder(self.repo, clean, target=self.commit).returncode,
                         builder.EXIT_OK)
        injected = self.scratch / "out-injected"
        completed = run_builder(self.repo, injected, target=self.commit,
                                environment={"GIT_DIR": str(other / ".git"),
                                             "GIT_WORK_TREE": str(other),
                                             "GIT_NAMESPACE": "decoy"})
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        self.assertEqual((clean / ASSET).read_bytes(), (injected / ASSET).read_bytes())

    def test_record_states_the_environment(self) -> None:
        out = self.scratch / "out-record"
        self.assertEqual(run_builder(self.repo, out, target=self.commit).returncode,
                         builder.EXIT_OK)
        environment = record_of(out)["environment"]
        self.assertEqual(environment["timezone"], "UTC")
        self.assertEqual(environment["locale"], "C")
        self.assertIn("GIT_DIR", environment["dropped"])

    def test_record_does_not_claim_cross_platform_determinism(self) -> None:
        out = self.scratch / "out-claim"
        run_builder(self.repo, out, target=self.commit)
        self.assertIn("not claimed", record_of(out)["determinism_note"])


class AtomicPublication(unittest.TestCase):
    """The destination is created by one rename, so it is never half-delivered.

    Measured on an earlier builder: moving the three files one at a time left a
    canonical-named ZIP behind when the second move failed.
    """

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-atomic-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.out = self.scratch / "out"

    def staging_directories(self) -> list[str]:
        return [p.name for p in self.scratch.iterdir() if p.name.startswith(".out.staging-")]

    def test_successful_build_publishes_exactly_three_files(self) -> None:
        commit = build_fixture_repository(self.repo)
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)
        self.assertEqual(self.staging_directories(), [])

    def test_stale_manifest_leaves_no_destination(self) -> None:
        build_fixture_repository(self.repo)
        manifest = self.repo / "SHA256SUMS"
        lines = manifest.read_text().splitlines()
        lines[0] = "0" * 64 + "  " + lines[0].split("  ", 1)[1]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "stale manifest", cwd=self.repo)
        completed = run_builder(self.repo, self.out,
                                target=git("rev-parse", "HEAD", cwd=self.repo))
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.staging_directories(), [])

    def test_export_ignore_failure_leaves_no_destination(self) -> None:
        commit = build_fixture_repository(
            self.repo, extra={"EXTRA.md": "# extra\n", ".gitattributes": "EXTRA.md export-ignore\n"})
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.staging_directories(), [])

    def test_final_rename_failure_leaves_no_destination(self) -> None:
        commit = build_fixture_repository(self.repo)
        import argparse
        real_rename = builder.os.rename

        def failing(src, dst, *a, **k):
            raise OSError("simulated rename failure")

        builder.os.rename = failing
        try:
            arguments = argparse.Namespace(version=VERSION, target=commit,
                                           output_dir=str(self.out), require_tag=None,
                                           expect_asset_sha256=None, repository=str(self.repo))
            with self.assertRaises(builder.Refused):
                builder.build(arguments)
        finally:
            builder.os.rename = real_rename
        self.assertFalse(self.out.exists())
        self.assertEqual(self.staging_directories(), [])

    def test_unexpected_exception_leaves_no_destination(self) -> None:
        commit = build_fixture_repository(self.repo)
        import argparse
        real = builder.inspect_archive

        def explode(*a, **k):
            raise RuntimeError("simulated unexpected failure")

        builder.inspect_archive = explode
        try:
            arguments = argparse.Namespace(version=VERSION, target=commit,
                                           output_dir=str(self.out), require_tag=None,
                                           expect_asset_sha256=None, repository=str(self.repo))
            with self.assertRaises(RuntimeError):
                builder.build(arguments)
        finally:
            builder.inspect_archive = real
        self.assertFalse(self.out.exists())
        self.assertEqual(self.staging_directories(), [])

    def test_main_converts_an_unexpected_exception_into_a_refusal(self) -> None:
        commit = build_fixture_repository(self.repo)
        real = builder.inspect_archive

        def explode(*a, **k):
            raise RuntimeError("simulated unexpected failure")

        builder.inspect_archive = explode
        try:
            code = builder.main(["--version", VERSION, "--target", commit,
                                 "--output-dir", str(self.out), "--repository", str(self.repo)])
        finally:
            builder.inspect_archive = real
        self.assertEqual(code, builder.EXIT_REFUSED)
        self.assertFalse(self.out.exists())

    def test_staging_is_a_sibling_of_the_destination(self) -> None:
        """A cross-filesystem staging directory would make the rename non-atomic."""
        commit = build_fixture_repository(self.repo)
        seen: list[str] = []
        real_mkdtemp = builder.tempfile.mkdtemp

        def watching(*a, **k):
            path = real_mkdtemp(*a, **k)
            seen.append(k.get("dir") or (a[2] if len(a) > 2 else None))
            return path

        builder.tempfile.mkdtemp = watching
        try:
            run_builder(self.repo, self.out, target=commit)
        finally:
            builder.tempfile.mkdtemp = real_mkdtemp
        # The in-process call is the verification scratch; assert the published
        # directory landed beside the destination instead.
        self.assertTrue(self.out.exists())
        self.assertEqual(self.out.parent, self.scratch)


class ExpectedDigestGate(unittest.TestCase):
    """The tagged build must reproduce the digest measured before the tag existed."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-digest-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)

    def test_pre_tag_digest_is_reproduced_by_the_tagged_build(self) -> None:
        first = self.scratch / "pre-tag"
        self.assertEqual(run_builder(self.repo, first, target=self.commit).returncode,
                         builder.EXIT_OK)
        expected = record_of(first)["asset"]["sha256"]
        git("tag", "-a", f"v{VERSION}", "-m", "release", self.commit, cwd=self.repo)
        final = self.scratch / "tagged"
        completed = run_builder(self.repo, final, target=self.commit,
                                require_tag=f"v{VERSION}", expect_asset_sha256=expected)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        self.assertEqual(record_of(final)["asset"]["sha256"], expected)
        self.assertEqual(record_of(final)["expected_asset_sha256"], expected)

    def test_a_different_target_fails_the_expected_digest(self) -> None:
        """Control: the gate is not vacuous."""
        first = self.scratch / "one"
        run_builder(self.repo, first, target=self.commit)
        expected = record_of(first)["asset"]["sha256"]
        git("commit", "-q", "--allow-empty", "-m", "same tree, new commit", cwd=self.repo)
        twin = git("rev-parse", "HEAD", cwd=self.repo)
        other = self.scratch / "two"
        completed = run_builder(self.repo, other, target=twin, expect_asset_sha256=expected)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("does not match --expect-asset-sha256", completed.stderr)
        self.assertFalse(other.exists())


class ArchiveInspection(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-inspect-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.prefix = f"{NAME}/"

    def make_archive(self, entries, comment: bytes = b"0" * 40) -> Path:
        archive = self.scratch / "probe.zip"
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, payload in entries:
                bundle.writestr(name, payload)
            bundle.comment = comment
        return archive

    def refuse(self, archive: Path, fragment: str) -> None:
        with self.assertRaises(builder.Refused) as caught:
            builder.inspect_archive(archive, self.prefix, VERSION)
        self.assertIn(fragment, str(caught.exception))

    def test_traversal_entry_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}../escape.txt", b"x")]), "unsafe component")

    def test_backslash_traversal_entry_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}..\\escape.txt", b"x")]), "backslash")

    def test_drive_letter_entry_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}C:\\escape", b"x")]), "backslash")

    def test_absolute_entry_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       ("/etc/passwd", b"x")]), "absolute path")

    def test_newline_in_path_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}a\nb.txt", b"x")]), "control character")

    def test_carriage_return_in_path_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}a\rb.txt", b"x")]), "control character")

    def test_tab_in_path_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}a\tb.txt", b"x")]), "control character")

    def test_duplicate_entry_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}dup.txt", b"a"),
                                       (f"{self.prefix}dup.txt", b"b")]), "duplicate")

    def test_second_root_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       ("other-root/file.txt", b"x")]), "exactly one root")

    def test_file_directory_collision_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n"),
                                       (f"{self.prefix}a", b"file"),
                                       (f"{self.prefix}a/b.txt", b"x")]),
                    "both a file and a parent")

    def test_symlink_entry_is_rejected(self) -> None:
        archive = self.scratch / "symlink.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(f"{self.prefix}VERSION", b"1.0.2\n")
            info = zipfile.ZipInfo(f"{self.prefix}link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, b"../../outside")
            bundle.comment = b"0" * 40
        self.refuse(archive, "symlink")

    def test_version_mismatch_inside_archive_is_rejected(self) -> None:
        self.refuse(self.make_archive([(f"{self.prefix}VERSION", b"9.9.9\n")]), "archive VERSION")

    def test_clean_archive_is_accepted(self) -> None:
        """Control: the checker is not simply refusing everything."""
        facts = builder.inspect_archive(self.make_archive([(f"{self.prefix}VERSION", b"1.0.2\n")]),
                                        self.prefix, VERSION)
        self.assertEqual(facts["archive_comment"], "0" * 40)
        self.assertEqual(facts["file_count"], 1)


class ArchiveMatchesTheTree(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-tree-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.out = self.scratch / "out"

    def test_in_tree_export_ignore_is_caught_by_comparison(self) -> None:
        commit = build_fixture_repository(
            self.repo, extra={"EXTRA.md": "# extra\n", ".gitattributes": "EXTRA.md export-ignore\n"})
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("not in the archive", completed.stderr)

    def test_in_tree_export_subst_is_caught_by_comparison(self) -> None:
        commit = build_fixture_repository(
            self.repo, extra={"STAMP.md": "commit $Format:%H$\n",
                              ".gitattributes": "STAMP.md export-subst\n"})
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("differs from the target tree blob", completed.stderr)

    def test_a_clean_tree_with_an_executable_file_round_trips(self) -> None:
        build_fixture_repository(self.repo, extra={"tool.sh": "#!/bin/sh\necho hi\n"})
        (self.repo / "tool.sh").chmod(0o755)
        git("update-index", "--chmod=+x", "tool.sh", cwd=self.repo)
        git("commit", "-q", "-m", "executable", cwd=self.repo)
        commit = git("rev-parse", "HEAD", cwd=self.repo)
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        comparison = record_of(self.out)["raw_tree_comparison"]
        self.assertEqual(comparison["compared_paths"], comparison["tree_paths"])
        self.assertGreaterEqual(comparison["executable_paths"], 1)


class PublicBuildRecordPrivacy(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-privacy-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)
        self.out = self.scratch / "out"
        completed = run_builder(self.repo, self.out, target=self.commit)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        self.raw = (self.out / RECORD).read_text(encoding="utf-8")

    def test_record_contains_no_absolute_paths(self) -> None:
        self.assertEqual(builder.find_absolute_paths(json.loads(self.raw)), [])

    def test_record_contains_no_home_or_temp_path(self) -> None:
        for fragment in ("/Users/", "/home/", "/private/var", "/tmp/"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, self.raw)

    def test_archive_command_is_redacted_but_complete(self) -> None:
        command = json.loads(self.raw)["archive_command"]
        self.assertIn("<REPOSITORY>", command)
        self.assertIn("--output=<OUTPUT_ZIP>", command)
        self.assertEqual(command[-1], self.commit)
        self.assertIn("-9", command)

    def test_record_declares_schema_v4_and_its_own_digest_inputs(self) -> None:
        record = json.loads(self.raw)
        self.assertEqual(record["schema"], "square-riesz-release-asset-build.v4")
        self.assertEqual(record["schema"], builder.RECORD_SCHEMA)
        self.assertEqual(record["builder_script"], "scripts/build_release_assets.py")
        for field in ("builder_script_target_sha256", "builder_script_executed_sha256"):
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", record[field]))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", record["builder_script_blob_oid"]))
        self.assertEqual(record["github_writes"], 0)
        self.assertEqual(record["output_inventory"], EXPECTED_OUTPUT)
        for key in ("python_version", "platform", "git_version"):
            self.assertTrue(record[key])

    def test_record_file_is_written_in_its_canonical_spelling(self) -> None:
        """The attestation embeds the record and republishes this digest."""
        record = json.loads(self.raw)
        self.assertEqual(builder.canonical_record_bytes(record),
                         (self.out / RECORD).read_bytes())

    def test_the_path_detector_is_not_vacuous(self) -> None:
        self.assertTrue(builder.find_absolute_paths({"repository": "/private/tmp/x"}))


class ReleaseDocumentWording(unittest.TestCase):
    """The release documents ship inside the tag, so their wording is release engineering."""

    WITHDRAWN = {
        "RELEASE_NOTES_v1.0.2.md": [
            "It does not change the mathematics",
            "were already rounded outward",
            "A run that prints a status line without having performed the proof",
            # The withdrawn claim is the positive assertion. The current text
            # says digests are *not* recorded there, so matching the bare
            # "recorded in `PUBLICATION_STATUS.md`" would flag the correction
            # itself.
            "digests and sizes are recorded in `PUBLICATION_STATUS.md`",
        ],
    }
    TIME_DEPENDENT = ("not yet published", "not yet canonical", "release-preparation candidate")
    TAGGED_STATUS_DOCUMENTS = ("PUBLICATION_STATUS.md", "release-assets/README.md",
                               "docs/errata-v1.0.1.md", "RELEASE_NOTES_v1.0.2.md")

    def read(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def flat(self, relative: str) -> str:
        lines = [re.sub(r"^\s*>\s?", "", line) for line in self.read(relative).splitlines()]
        return " ".join(" ".join(lines).split())

    def test_withdrawn_release_note_claims_are_absent(self) -> None:
        for relative, phrases in self.WITHDRAWN.items():
            text = " ".join(self.read(relative).split())
            for phrase in phrases:
                with self.subTest(document=relative, phrase=phrase):
                    self.assertNotIn(" ".join(phrase.split()), text)

    def test_the_withdrawn_phrase_detector_can_fail(self) -> None:
        self.assertIn("It does not change the mathematics",
                      " ".join("A draft saying It does not change the mathematics.".split()))

    def test_tagged_documents_carry_no_time_dependent_status(self) -> None:
        for relative in self.TAGGED_STATUS_DOCUMENTS:
            text = " ".join(self.read(relative).split())
            for phrase in self.TIME_DEPENDENT:
                with self.subTest(document=relative, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_publication_status_states_the_conditional_rule(self) -> None:
        text = self.flat("PUBLICATION_STATUS.md")
        self.assertIn("published and immutable", text)
        self.assertIn("Otherwise `v1.0.1` remains the latest canonical Release", text)
        self.assertIn("does not attest to its own publication", text)

    def test_the_blockquote_normaliser_is_what_makes_that_match(self) -> None:
        raw = " ".join(self.read("PUBLICATION_STATUS.md").split())
        self.assertNotIn("Otherwise `v1.0.1` remains the latest canonical Release", raw)

    def test_documents_do_not_call_the_release_body_immutable(self) -> None:
        for relative in ("PUBLICATION_STATUS.md", "release-assets/README.md",
                         "RELEASE_NOTES_v1.0.2.md", "PUBLICATION_AUDIT.json", "CHANGELOG.md"):
            text = self.read(relative)
            with self.subTest(document=relative):
                self.assertNotIn("immutable GitHub Release body", text)
                self.assertNotIn("immutable Release body", text)

    def test_documents_name_the_three_assets(self) -> None:
        for relative in ("PUBLICATION_STATUS.md", "release-assets/README.md",
                         "RELEASE_NOTES_v1.0.2.md", "PUBLICATION_AUDIT.json"):
            with self.subTest(document=relative):
                self.assertIn("publication-attestation.json", self.read(relative))

    def test_publication_audit_is_a_static_candidate_audit(self) -> None:
        audit = json.loads((REPO_ROOT / "PUBLICATION_AUDIT.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["audit_type"], "static_release_candidate")
        self.assertEqual(audit["release_version"], VERSION)
        self.assertFalse(audit["dynamic_publication_attestation"]["embedded_in_source_tree"])
        for absent in ("merge_commit", "tag_target", "release_id", "asset_sha256", "audit_run_id"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, audit)

    def test_publication_audit_labels_its_replay_as_local_and_dirty(self) -> None:
        audit = json.loads((REPO_ROOT / "PUBLICATION_AUDIT.json").read_text(encoding="utf-8"))
        replay = audit["local_candidate_replay"]
        self.assertTrue(replay["source_git_dirty"])
        self.assertEqual(replay["verifiers"], 88)
        self.assertNotIn("source_git_clean", replay)
        self.assertIn("must not be presented as the release replay", replay["note"])

    def test_publication_audit_states_the_determinism_boundary_includes_the_timezone(self) -> None:
        audit = json.loads((REPO_ROOT / "PUBLICATION_AUDIT.json").read_text(encoding="utf-8"))
        boundary = audit["canonical_asset_builder"]["determinism_boundary"]
        self.assertIn("TZ=UTC", boundary)

    def test_release_record_for_this_version_is_not_in_the_tree(self) -> None:
        self.assertFalse((REPO_ROOT / "docs" / "release-record-v1.0.2.md").exists())


class BuilderSourceBinding(unittest.TestCase):
    """The script that runs must be the builder blob inside the target commit.

    Measured on an earlier builder: a target commit carrying different
    ``scripts/build_release_assets.py`` bytes than the script that executed
    produced exit 0 for the pre-tag build, the tagged build and the publication
    attestation. The record held a 40-hex blob id and a 64-hex file digest,
    which cannot be pasted into each other's slot -- a type rule, not a binding.
    """

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-bind-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.out = self.scratch / "out"

    def test_a_target_whose_builder_blob_differs_is_refused(self) -> None:
        commit = build_fixture_repository(
            self.repo, builder_source=b'#!/usr/bin/env python3\nprint("not the builder")\n')
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("does not match scripts/build_release_assets.py", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_a_target_without_the_builder_is_refused(self) -> None:
        build_fixture_repository(self.repo)
        (self.repo / "scripts" / "build_release_assets.py").unlink()
        subprocess.run([sys.executable, "-B", "scripts/regenerate_manifest.py"],
                       cwd=self.repo, check=True, capture_output=True)
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "no builder", cwd=self.repo)
        completed = run_builder(self.repo, self.out)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("has no scripts/build_release_assets.py", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_a_modified_external_copy_is_refused(self) -> None:
        commit = build_fixture_repository(self.repo)
        copy = self.scratch / "elsewhere.py"
        copy.write_bytes(BUILDER.read_bytes() + b"\n# one extra byte of history\n")
        completed = run_builder(self.repo, self.out, target=commit, script=copy)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("does not match scripts/build_release_assets.py", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_an_identical_external_copy_is_accepted(self) -> None:
        """Control: the binding is on bytes, not on where the file sits."""
        commit = build_fixture_repository(self.repo)
        copy = self.scratch / "same.py"
        copy.write_bytes(BUILDER.read_bytes())
        completed = run_builder(self.repo, self.out, target=commit, script=copy)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        record = record_of(self.out)
        self.assertTrue(record["builder_script_matches_target"])
        self.assertEqual(record["builder_script_target_sha256"],
                         record["builder_script_executed_sha256"])

    def test_the_recorded_blob_oid_is_the_git_object_id(self) -> None:
        commit = build_fixture_repository(self.repo)
        self.assertEqual(run_builder(self.repo, self.out, target=commit).returncode,
                         builder.EXIT_OK)
        measured = git("rev-parse", f"{commit}:scripts/build_release_assets.py", cwd=self.repo)
        self.assertEqual(record_of(self.out)["builder_script_blob_oid"], measured)

    def test_the_recorded_digest_is_the_digest_of_the_running_file(self) -> None:
        commit = build_fixture_repository(self.repo)
        self.assertEqual(run_builder(self.repo, self.out, target=commit).returncode,
                         builder.EXIT_OK)
        self.assertEqual(record_of(self.out)["builder_script_executed_sha256"],
                         hashlib.sha256(BUILDER.read_bytes()).hexdigest())

    def test_a_change_to_the_script_during_the_build_is_refused(self) -> None:
        """Fault injection: the binding is measured again before the record is written."""
        commit = build_fixture_repository(self.repo)
        real = builder.executing_script_digest
        calls = {"n": 0}

        def drifting():
            calls["n"] += 1
            script, value = real()
            return (script, value) if calls["n"] == 1 else (script, "c" * 64)

        builder.executing_script_digest = drifting
        try:
            code = builder.main(["--version", VERSION, "--target", commit,
                                 "--output-dir", str(self.out), "--repository", str(self.repo)])
        finally:
            builder.executing_script_digest = real
        self.assertEqual(code, builder.EXIT_REFUSED)
        self.assertGreaterEqual(calls["n"], 2)
        self.assertFalse(self.out.exists())

    def test_without_the_injection_the_same_build_succeeds(self) -> None:
        """Control: the refusal above is the drift, not the fixture."""
        commit = build_fixture_repository(self.repo)
        self.assertEqual(
            builder.main(["--version", VERSION, "--target", commit,
                          "--output-dir", str(self.out), "--repository", str(self.repo)]),
            builder.EXIT_OK)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)


class HeadIsTheTarget(unittest.TestCase):
    """The checkout supplies the executing builder, so it must be the target."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-head-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.first = build_fixture_repository(self.repo)
        self.out = self.scratch / "out"

    def test_an_older_commit_than_head_is_refused(self) -> None:
        git("commit", "-q", "--allow-empty", "-m", "second", cwd=self.repo)
        completed = run_builder(self.repo, self.out, target=self.first)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("HEAD is", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_head_itself_is_accepted(self) -> None:
        """Control: the refusal is about the mismatch, not about the check existing."""
        git("commit", "-q", "--allow-empty", "-m", "second", cwd=self.repo)
        head = git("rev-parse", "HEAD", cwd=self.repo)
        self.assertEqual(run_builder(self.repo, self.out, target=head).returncode,
                         builder.EXIT_OK)
        self.assertEqual(record_of(self.out)["head_commit"], head)


class TaggedBuildRequiresTheExpectedDigest(unittest.TestCase):
    """A tag cannot be moved, so its digest has to be agreed before it exists.

    Measured on an earlier builder: a build with ``--require-tag v1.0.2`` and no
    ``--expect-asset-sha256`` produced a record with
    ``expected_asset_sha256: null`` and the attestation accepted it, so the
    final asset never showed that the pre-tag gate had been used.
    """

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-gate-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)
        git("tag", "-a", f"v{VERSION}", "-m", "release", self.commit, cwd=self.repo)

    def test_a_tagged_build_without_an_expected_digest_is_refused(self) -> None:
        out = self.scratch / "tagged-no-expected"
        completed = run_builder(self.repo, out, target=self.commit, require_tag=f"v{VERSION}")
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("--require-tag needs --expect-asset-sha256", completed.stderr)
        self.assertFalse(out.exists())

    def test_a_pre_tag_build_without_an_expected_digest_is_allowed(self) -> None:
        out = self.scratch / "pre-tag"
        self.assertEqual(run_builder(self.repo, out, target=self.commit).returncode,
                         builder.EXIT_OK)
        self.assertIsNone(record_of(out)["expected_asset_sha256"])

    def test_a_tagged_build_with_the_pre_tag_digest_succeeds(self) -> None:
        first = self.scratch / "one"
        run_builder(self.repo, first, target=self.commit)
        expected = record_of(first)["asset"]["sha256"]
        final = self.scratch / "two"
        completed = run_builder(self.repo, final, target=self.commit,
                                require_tag=f"v{VERSION}", expect_asset_sha256=expected)
        self.assertEqual(completed.returncode, builder.EXIT_OK, completed.stderr)
        record = record_of(final)
        self.assertEqual(record["expected_asset_sha256"], record["asset"]["sha256"])

    def test_a_tagged_build_with_a_wrong_expected_digest_is_refused(self) -> None:
        out = self.scratch / "three"
        completed = run_builder(self.repo, out, target=self.commit,
                                require_tag=f"v{VERSION}", expect_asset_sha256="d" * 64)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("does not match --expect-asset-sha256", completed.stderr)
        self.assertFalse(out.exists())


class PublicationCommitPoint(unittest.TestCase):
    """After the rename the output exists, whatever else goes wrong.

    Measured on an earlier builder: failing the parent-directory ``fsync`` that
    follows the rename produced exit 2 and the message ``nothing published``
    while a complete three-file directory sat on disk.
    """

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-commit-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)
        self.out = self.scratch / "out"

    def run_with_failing_directory_fsync(self, fail_from: int) -> tuple[int, str]:
        real = builder.fsync_directory
        state = {"calls": 0}

        def injected(path):
            state["calls"] += 1
            if state["calls"] < fail_from:
                return real(path)
            raise OSError(5, "injected directory fsync failure")

        builder.fsync_directory = injected
        try:
            code = builder.main(["--version", VERSION, "--target", self.commit,
                                 "--output-dir", str(self.out), "--repository", str(self.repo)])
        finally:
            builder.fsync_directory = real
        return code, str(state["calls"])

    def test_a_failure_after_the_rename_reports_a_published_output(self) -> None:
        code, _ = self.run_with_failing_directory_fsync(fail_from=2)
        self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertEqual(code, 3)
        self.assertTrue(self.out.is_dir())
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)

    def test_the_published_output_after_that_failure_is_intact(self) -> None:
        self.run_with_failing_directory_fsync(fail_from=2)
        record = record_of(self.out)
        asset = self.out / ASSET
        self.assertEqual(hashlib.sha256(asset.read_bytes()).hexdigest(), record["asset"]["sha256"])
        self.assertEqual((self.out / SIDECAR).read_text(encoding="utf-8"),
                         f"{record['asset']['sha256']}  {ASSET}\n")
        with zipfile.ZipFile(asset) as bundle:
            self.assertIsNone(bundle.testzip())
        self.assertEqual(record["output_inventory"], EXPECTED_OUTPUT)

    def test_that_failure_leaves_no_staging_directory(self) -> None:
        self.run_with_failing_directory_fsync(fail_from=2)
        leftovers = [p.name for p in self.scratch.iterdir() if p.name.startswith(".out.staging-")]
        self.assertEqual(leftovers, [])

    def test_rerunning_after_that_failure_is_refused(self) -> None:
        self.run_with_failing_directory_fsync(fail_from=2)
        completed = run_builder(self.repo, self.out, target=self.commit)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("already exists", completed.stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)

    def test_a_failure_before_the_rename_is_still_exit_two_with_no_output(self) -> None:
        """The staging fsync is the first call, so failing from 1 fails early."""
        code, _ = self.run_with_failing_directory_fsync(fail_from=1)
        self.assertEqual(code, builder.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())

    def run_with_failing_fsync_and_inspection(self) -> int:
        """Both the durability step and the inspection that describes it fail.

        Measured on an earlier builder: the inspection raised out of the very
        handler that was classifying the state, so a complete three-file
        directory was reported as exit 2 and `nothing published`.
        """
        real_fsync = builder.fsync_directory
        real_inspect = builder.inspect_published_output
        state = {"calls": 0}

        def injected(path):
            state["calls"] += 1
            if state["calls"] < 2:
                return real_fsync(path)
            raise OSError(5, "injected directory fsync failure")

        def exploding(*a, **k):
            raise RuntimeError("injected inspection failure")

        builder.fsync_directory = injected
        builder.inspect_published_output = exploding
        try:
            return builder.main(["--version", VERSION, "--target", self.commit,
                                 "--output-dir", str(self.out), "--repository", str(self.repo)])
        finally:
            builder.fsync_directory = real_fsync
            builder.inspect_published_output = real_inspect

    def test_a_failing_inspection_after_the_rename_is_still_exit_three(self) -> None:
        code = self.run_with_failing_fsync_and_inspection()
        self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertEqual(code, 3)
        self.assertTrue(self.out.is_dir())
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)

    def test_the_output_survives_that_nested_failure(self) -> None:
        self.run_with_failing_fsync_and_inspection()
        record = record_of(self.out)
        self.assertEqual(hashlib.sha256((self.out / ASSET).read_bytes()).hexdigest(),
                         record["asset"]["sha256"])

    def test_the_nested_failure_says_verification_was_unavailable(self) -> None:
        real_inspect = builder.inspect_published_output

        def exploding(*a, **k):
            raise RuntimeError("injected inspection failure")

        builder.inspect_published_output = exploding
        try:
            message = builder.describe_published_output(
                self.out, {"output_inventory": EXPECTED_OUTPUT}, OSError(5, "injected fsync"))
        finally:
            builder.inspect_published_output = real_inspect
        self.assertNotIn("nothing published", message)
        self.assertIn("EXISTS", message)
        self.assertIn("could NOT be verified", message)
        self.assertIn("Do NOT", message)

    def test_the_inspection_never_raises(self) -> None:
        """A record with the wrong shape must produce unknowns, not an exception."""
        findings = builder.inspect_published_output(self.scratch / "absent", {})
        self.assertIsNone(findings["complete_and_valid"])
        self.assertTrue(findings["inspection_errors"])

    def test_an_unknown_check_does_not_collapse_into_false(self) -> None:
        """`None` means 'not determined'; reporting it as False would be a claim."""
        findings = builder.inspect_published_output(self.scratch / "absent", {})
        self.assertIsNot(findings["complete_and_valid"], False)

    def test_the_description_helper_never_raises(self) -> None:
        class Hostile(Exception):
            def __str__(self):
                raise RuntimeError("this exception cannot describe itself")

        message = builder.describe_published_output(self.scratch / "absent", {}, Hostile())
        self.assertIn("EXISTS", message)
        self.assertIn("Do NOT", message)

    def run_with_interrupted_rename(self, raiser, after_real_rename: bool) -> int:
        """A signal delivered inside the rename call itself.

        Measured on an earlier builder: `os.rename` completed and a
        `KeyboardInterrupt` arrived before `published = True` ran, so the
        exception escaped every handler and the process died with a traceback
        while a complete three-file directory sat on disk. BaseException is not
        Exception, which is why none of the existing handlers saw it.
        """
        real_rename = builder.os.rename

        def interrupting(src, dst, *a, **k):
            if after_real_rename:
                real_rename(src, dst, *a, **k)
            raise raiser()

        builder.os.rename = interrupting
        try:
            return builder.main(["--version", VERSION, "--target", self.commit,
                                 "--output-dir", str(self.out), "--repository", str(self.repo)])
        finally:
            builder.os.rename = real_rename

    def test_a_keyboard_interrupt_after_the_rename_is_exit_three(self) -> None:
        code = self.run_with_interrupted_rename(
            lambda: KeyboardInterrupt("after rename signal"), after_real_rename=True)
        self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertTrue(self.out.is_dir())
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)

    def test_a_system_exit_after_the_rename_is_exit_three(self) -> None:
        code = self.run_with_interrupted_rename(
            lambda: SystemExit("after rename exit"), after_real_rename=True)
        self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertTrue(self.out.is_dir())

    def test_a_custom_base_exception_after_the_rename_is_exit_three(self) -> None:
        class Signal(BaseException):
            pass

        code = self.run_with_interrupted_rename(lambda: Signal("after rename"),
                                                after_real_rename=True)
        self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)

    def test_an_interrupt_before_the_rename_is_exit_two_with_no_output(self) -> None:
        """Control: the classification is what the filesystem says, not the code path."""
        code = self.run_with_interrupted_rename(
            lambda: KeyboardInterrupt("before rename signal"), after_real_rename=False)
        self.assertEqual(code, builder.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertFalse(self.out.exists())

    def test_no_base_exception_escapes_main(self) -> None:
        for raiser, after in ((lambda: KeyboardInterrupt("x"), True),
                              (lambda: KeyboardInterrupt("x"), False),
                              (lambda: SystemExit("x"), True),
                              (lambda: SystemExit("x"), False)):
            with self.subTest(after_real_rename=after):
                if self.out.exists():
                    shutil.rmtree(self.out)
                code = self.run_with_interrupted_rename(raiser, after_real_rename=after)
                self.assertIn(code, (builder.EXIT_REFUSED_BEFORE_PUBLISH,
                                     builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN))

    def test_the_interrupted_publication_message_does_not_claim_an_absence(self) -> None:
        state = {"output_exists": True, "present_files": EXPECTED_OUTPUT,
                 "output_is_the_renamed_staging": True, "observation_errors": []}
        message = builder.describe_interrupted_publication(
            self.out, {"output_inventory": EXPECTED_OUTPUT},
            state, KeyboardInterrupt("after rename signal"))
        self.assertNotIn("nothing published", message)
        self.assertIn("EXISTS", message)
        self.assertIn("Do NOT", message)

    def test_the_observation_helper_never_raises(self) -> None:
        state = builder.observe_publication(self.scratch / "absent-staging",
                                            self.scratch / "absent-output", None)
        self.assertIs(state["output_exists"], False)
        self.assertIsNone(state["output_is_the_renamed_staging"])

    def test_the_renamed_directory_is_identified_by_inode(self) -> None:
        """The published directory should be the staging directory, moved."""
        staging = self.scratch / "stage-probe"
        staging.mkdir()
        identity = builder.directory_identity(staging)
        moved = self.scratch / "moved-probe"
        staging.rename(moved)
        state = builder.observe_publication(staging, moved, identity)
        self.assertTrue(state["output_is_the_renamed_staging"])

    def test_a_different_directory_is_not_the_renamed_staging(self) -> None:
        """Control: the inode comparison can also say no."""
        staging = self.scratch / "stage-a"
        staging.mkdir()
        identity = builder.directory_identity(staging)
        other = self.scratch / "stage-b"
        other.mkdir()
        state = builder.observe_publication(staging, other, identity)
        self.assertFalse(state["output_is_the_renamed_staging"])

    def test_the_two_exit_codes_are_distinct(self) -> None:
        self.assertNotEqual(builder.EXIT_REFUSED_BEFORE_PUBLISH,
                            builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)

    def test_the_durability_message_does_not_claim_nothing_was_published(self) -> None:
        real = builder.fsync_directory
        state = {"calls": 0}

        def injected(path):
            state["calls"] += 1
            if state["calls"] < 2:
                return real(path)
            raise OSError(5, "injected directory fsync failure")

        builder.fsync_directory = injected
        try:
            with self.assertRaises(builder.PublishedDurabilityUncertain) as caught:
                import argparse
                builder.build(argparse.Namespace(
                    version=VERSION, target=self.commit, output_dir=str(self.out),
                    require_tag=None, expect_asset_sha256=None, repository=str(self.repo)))
        finally:
            builder.fsync_directory = real
        message = str(caught.exception)
        self.assertNotIn("nothing published", message)
        self.assertIn("EXISTS", message)
        self.assertIn("complete and valid", message)
        self.assertIn("Do NOT", message)


def statement_after(path: Path, function_name: str, needle: str) -> int:
    """Line of the statement executed immediately after the `needle` call.

    Found through the syntax tree rather than by a hard-coded number, so the
    probe keeps pointing at the right statement when the file moves.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == function_name)
    guards = []
    for parent in ast.walk(function):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if isinstance(statement, ast.Try):
                dumped = ast.dump(ast.Module(body=statement.body, type_ignores=[]))
                if needle in dumped:
                    guards.append((len(dumped), body, index))
    if not guards:
        raise AssertionError(f"no try guarding {needle!r} in {function_name}")
    _, body, index = min(guards, key=lambda item: item[0])
    guard = body[index]
    for position, statement in enumerate(guard.body):
        if needle in ast.dump(statement) and position + 1 < len(guard.body):
            return guard.body[position + 1].lineno
    if index + 1 < len(body):
        return body[index + 1].lineno
    raise AssertionError(f"nothing follows the {needle!r} call in {function_name}")


def success_report_line(path: Path, function_name: str) -> int:
    """Line of the statement just before `return EXIT_OK`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == function_name)
    for parent in ast.walk(function):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if (isinstance(statement, ast.Return) and isinstance(statement.value, ast.Name)
                    and statement.value.id == "EXIT_OK"):
                return body[index - 1].lineno if index else statement.lineno
    raise AssertionError(f"no `return EXIT_OK` in {function_name}")


class InterruptAtLine:
    """Raise on the first execution of one line of one file."""

    def __init__(self, filename: str, line: int, raiser):
        self.filename, self.line, self.raiser, self.fired = filename, line, raiser, False

    def _local(self, frame, event, arg):
        if event == "line" and frame.f_lineno == self.line and not self.fired:
            self.fired = True
            raise self.raiser()
        return self._local

    def _global(self, frame, event, arg):
        return self._local if frame.f_code.co_filename == self.filename else None

    def __enter__(self):
        sys.settrace(self._global)
        return self

    def __exit__(self, *exc):
        sys.settrace(None)
        return False


class Signal(BaseException):
    """A BaseException that is neither KeyboardInterrupt nor SystemExit."""


INTERRUPTIONS = {"KeyboardInterrupt": lambda: KeyboardInterrupt("interrupt"),
                 "SystemExit": lambda: SystemExit("interrupt"),
                 "custom BaseException": lambda: Signal("interrupt")}


class PostCommitInterruptWindows(unittest.TestCase):
    """A signal after the syscall, but outside the narrow guard around it.

    Measured on an earlier builder: guarding only the `os.rename` call left the
    next line -- the one recording that the rename happened -- unprotected, so
    an interruption there produced exit 2 and "nothing published" over a
    complete directory. A second window sat after `build()` returned, on the
    success report, where the interruption escaped as a traceback.
    """

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-window-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.commit = build_fixture_repository(self.repo)
        self.out = self.scratch / "out"

    def interrupt_at(self, line: int, raiser) -> tuple[int | None, str | None, str]:
        buffer = io.StringIO()
        code = escaped = None
        with InterruptAtLine(str(BUILDER), line, raiser) as trap:
            try:
                with contextlib.redirect_stderr(buffer):
                    code = builder.main(["--version", VERSION, "--target", self.commit,
                                         "--output-dir", str(self.out),
                                         "--repository", str(self.repo)])
            except BaseException as error:  # noqa: BLE001 - an escape is the defect
                escaped = type(error).__name__
        self.assertTrue(trap.fired, "the traced line never executed")
        return code, escaped, buffer.getvalue()

    def test_an_interrupt_recording_the_rename_is_exit_three(self) -> None:
        line = statement_after(BUILDER, "build", "rename")
        for name, raiser in INTERRUPTIONS.items():
            with self.subTest(interruption=name):
                if self.out.exists():
                    shutil.rmtree(self.out)
                code, escaped, err = self.interrupt_at(line, raiser)
                self.assertIsNone(escaped)
                self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
                self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)
                self.assertNotIn("nothing published", err)

    def test_an_interrupt_on_the_success_report_is_exit_three(self) -> None:
        line = success_report_line(BUILDER, "main")
        for name, raiser in INTERRUPTIONS.items():
            with self.subTest(interruption=name):
                if self.out.exists():
                    shutil.rmtree(self.out)
                code, escaped, err = self.interrupt_at(line, raiser)
                self.assertIsNone(escaped)
                self.assertEqual(code, builder.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
                self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)
                self.assertNotIn("nothing published", err)

    def test_the_traced_lines_are_the_intended_statements(self) -> None:
        """Control: the probe points where the test claims it does."""
        source = BUILDER.read_text(encoding="utf-8").splitlines()
        self.assertIn("published = True",
                      source[statement_after(BUILDER, "build", "rename") - 1])
        self.assertIn("print(", source[success_report_line(BUILDER, "main") - 1])

    def test_an_interrupt_before_the_rename_is_exit_two(self) -> None:
        """Control: the verdict follows the filesystem, not the code path."""
        real_rename = builder.os.rename

        def interrupting(src, dst, *a, **k):
            raise KeyboardInterrupt("before the rename")

        builder.os.rename = interrupting
        try:
            code = builder.main(["--version", VERSION, "--target", self.commit,
                                 "--output-dir", str(self.out), "--repository", str(self.repo)])
        finally:
            builder.os.rename = real_rename
        self.assertEqual(code, builder.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertFalse(self.out.exists())

    def test_a_normal_run_is_still_exit_zero(self) -> None:
        """Control: the widened boundary did not turn success into uncertainty."""
        code = builder.main(["--version", VERSION, "--target", self.commit,
                             "--output-dir", str(self.out), "--repository", str(self.repo)])
        self.assertEqual(code, builder.EXIT_OK)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), EXPECTED_OUTPUT)


class ArchiveSelfChecks(unittest.TestCase):
    """The archive runs the repository's own checks on itself."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="release-asset-selfcheck-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.repo = self.scratch / "repo"
        self.out = self.scratch / "out"

    def test_both_checks_run_and_none_are_missing(self) -> None:
        commit = build_fixture_repository(self.repo)
        self.assertEqual(run_builder(self.repo, self.out, target=commit).returncode,
                         builder.EXIT_OK)
        verification = record_of(self.out)["archive_self_verification"]
        self.assertEqual(verification["not_present_in_archive"], [])
        self.assertEqual(sorted(verification["ran"]), sorted(builder.ARCHIVE_CHECKS))
        for script, result in verification["ran"].items():
            with self.subTest(script=script):
                self.assertEqual(result["exit_code"], 0)

    def test_a_failing_check_refuses_the_build(self) -> None:
        commit = build_fixture_repository(self.repo, check_release=FAILING_CHECK_RELEASE)
        completed = run_builder(self.repo, self.out, target=commit)
        self.assertEqual(completed.returncode, builder.EXIT_REFUSED, completed.stderr)
        self.assertIn("check_release.py failed inside the extracted archive", completed.stderr)
        self.assertFalse(self.out.exists())

    def test_an_absent_optional_check_is_recorded_rather_than_ignored(self) -> None:
        """The builder records the gap; the attestation is what refuses it."""
        commit = build_fixture_repository(self.repo, check_release=None)
        self.assertEqual(run_builder(self.repo, self.out, target=commit).returncode,
                         builder.EXIT_OK)
        verification = record_of(self.out)["archive_self_verification"]
        self.assertEqual(verification["not_present_in_archive"], ["check_release.py"])
        self.assertNotIn("check_release.py", verification["ran"])


if __name__ == "__main__":
    unittest.main()
