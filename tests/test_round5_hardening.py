"""Round 5: the release objects as the anchor, and import time as attack surface.

Round 4 treated ``data/frozen-corpus-v1.0.1.sha256`` as if it could not be
edited, and checked ``main()`` as if nothing ran before it. Both were wrong, and
both were measured before being fixed. Every test here failed against the
Round 4 implementation.

Mutations are applied to copies — of the working tree, or of a real clone when
the Git objects are what is under test. Nothing writes to this repository.
"""

from __future__ import annotations

import ast
import collections
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import (  # noqa: E402
    GIT_ENVIRONMENT,
    REPO_ROOT,
    copy_release_clone,
    copy_repository,
    git_available,
    read_text,
    replace_once,
    write_text,
)

from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    METHODS,
    ROOT,
    CertifierSourceError,
    EntryPointError,
    certifier_relpath,
    extract_certifier_facts,
)

import check_frozen_corpus as frozen  # noqa: E402

N15_SPECTRAL = ROOT / "certifiers" / "n15" / "spectral.py"
CERTIFY_DEF = "def certify(target: Q = TARGET, max_splits: int = 2_000_000) -> CertificateResult:\n"
FAKE = "CertificateResult(True, 0, 1, 0, TARGET, None, None)"
BASELINE_NAME = "data/frozen-corpus-v1.0.1.sha256"

ANCHORED = (
    "--expect-base-version", frozen.BASE_VERSION,
    "--expect-base-commit", frozen.BASE_COMMIT,
    "--require-git-anchor",
)


def mutate_source(old: str, new: str) -> str:
    source = N15_SPECTRAL.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise AssertionError(f"pattern occurs {source.count(old)} times: {old!r}")
    return source.replace(old, new, 1)


def check_entry_point(source: str) -> "str | None":
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "spectral.py"
        path.write_text(source, encoding="utf-8")
        try:
            extract_certifier_facts(path, verify_entry_point=True)
        except (EntryPointError, CertifierSourceError) as error:
            return str(error)
    return None


def rewrite_baseline(tree: Path, updates: dict[str, str]) -> None:
    """Point baseline entries at whatever the working tree now holds."""
    path = tree / BASELINE_NAME
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if line.startswith("#") or not line.strip():
            continue
        _, relative = line.split("  ", 1)
        if relative in updates:
            lines[index] = f"{updates[relative]}  {relative}"
            seen.add(relative)
    if seen != set(updates):
        raise AssertionError(f"baseline did not list {sorted(set(updates) - seen)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class FrozenCorpusIsAnchoredToTheRelease(unittest.TestCase):
    """P1-A. The baseline is a file in the repository; the commit is not."""

    def setUp(self) -> None:
        if not git_available():
            self.skipTest("git is not available; the release objects cannot be read")

    def run_check(self, tree: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(tree / "scripts" / "check_frozen_corpus.py"),
             "--root", str(tree), "--baseline", str(tree / BASELINE_NAME), *extra],
            capture_output=True, text=True, timeout=900, env={**GIT_ENVIRONMENT, "HOME": str(tree)},
        )

    def test_a_clean_clone_agrees_on_all_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("git_anchor=verified", result.stdout)
        self.assertIn("release_blobs=531", result.stdout)
        self.assertIn("agreeing_files=531", result.stdout)

    def test_header_base_commit_of_all_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            replace_once(tree / BASELINE_NAME, f"# base-commit: {frozen.BASE_COMMIT}",
                         "# base-commit: " + "0" * 40)
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("header base-commit is", result.stderr)

    def test_header_base_version_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            replace_once(tree / BASELINE_NAME, f"# base-version: {frozen.BASE_VERSION}",
                         "# base-version: v9.9.9")
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("header base-version is", result.stderr)

    def test_one_byte_with_the_baseline_following(self) -> None:
        """Round 4 accepted this: the baseline agreed with the tree."""
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            target = tree / "certifiers/n15/spectral.py"
            target.write_bytes(target.read_bytes() + b"\n")
            rewrite_baseline(tree, {"certifiers/n15/spectral.py": hashlib.sha256(target.read_bytes()).hexdigest()})
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("release commit vs baseline", result.stderr)
        self.assertIn("certifiers/n15/spectral.py", result.stderr)

    def test_baseline_altered_on_its_own(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            rewrite_baseline(tree, {"certifiers/n15/spectral.py": "0" * 64})
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("release commit vs baseline", result.stderr)

    def test_a_moved_file_is_reported_as_a_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            source = tree / "certifiers/n15/spectral.py"
            source.rename(tree / "certifiers/n15/moved.py")
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("moved: certifiers/n15/spectral.py -> certifiers/n15/moved.py", result.stderr)

    def test_proof_skipping_certifier_with_every_digest_updated(self) -> None:
        """The whole Round 5 finding, end to end."""
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            certifier = tree / "certifiers/n15/spectral.py"
            replace_once(
                certifier, CERTIFY_DEF,
                "def skip_proof(function):\n"
                "    def replacement(target: Q = TARGET, max_splits: int = 2_000_000) -> CertificateResult:\n"
                f"        return {FAKE}\n"
                "    return replacement\n\n\n@skip_proof\n" + CERTIFY_DEF,
            )
            digest = hashlib.sha256(certifier.read_bytes()).hexdigest()

            aggregate = tree / "evidence/full-cleanroom-replay/PUBLIC_REPO_FULL_REPLAY.json"
            payload = json.loads(read_text(aggregate))
            for record in payload["results"]:
                if record["n"] == 15 and record["method"] == "spectral":
                    record["script_sha256"] = digest
            write_text(aggregate, json.dumps(payload, indent=2) + "\n")

            meta = tree / "evidence/full-cleanroom-replay/logs/n15_spectral.meta.json"
            job = json.loads(read_text(meta)); job["script_sha256"] = digest
            write_text(meta, json.dumps(job, indent=2) + "\n")

            table = tree / "evidence/full-cleanroom-replay/PUBLIC_REPO_FULL_REPLAY.csv"
            raw = read_text(table)
            reader = csv.DictReader(io.StringIO(raw, newline=""))
            rows, fields = list(reader), reader.fieldnames
            for row in rows:
                if row["n"] == "15" and row["method"] == "spectral":
                    row["script_sha256"] = digest
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=fields,
                                    lineterminator="\r\n" if "\r\n" in raw else "\n")
            writer.writeheader(); writer.writerows(rows)
            write_text(table, buffer.getvalue())

            rewrite_baseline(tree, {
                relative: hashlib.sha256((tree / relative).read_bytes()).hexdigest()
                for relative in (
                    "certifiers/n15/spectral.py",
                    "evidence/full-cleanroom-replay/PUBLIC_REPO_FULL_REPLAY.json",
                    "evidence/full-cleanroom-replay/PUBLIC_REPO_FULL_REPLAY.csv",
                    "evidence/full-cleanroom-replay/logs/n15_spectral.meta.json",
                )
            })
            subprocess.run([sys.executable, "-B", "scripts/regenerate_manifest.py"],
                           cwd=tree, capture_output=True, timeout=900)

            anchor = self.run_check(tree, *ANCHORED)
            manifest = subprocess.run(
                [sys.executable, "-B", "scripts/verify_manifest.py"], cwd=tree,
                capture_output=True, text=True, timeout=900)

        self.assertEqual(anchor.returncode, 1, anchor.stdout)
        self.assertIn("certifiers/n15/spectral.py", anchor.stderr)
        # The manifest still passes, which is exactly why the anchor is needed.
        self.assertEqual(manifest.returncode, 0, manifest.stdout + manifest.stderr)

    def test_require_git_anchor_without_the_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            shutil.rmtree(tree / ".git")
            required = self.run_check(tree, *ANCHORED)
            optional = self.run_check(tree)
        self.assertEqual(required.returncode, 2, required.stdout)
        self.assertIn("--require-git-anchor", required.stderr)
        self.assertEqual(optional.returncode, 0, optional.stdout + optional.stderr)
        self.assertIn("git_anchor_unverifiable=1", optional.stdout)
        self.assertIn("NOT checked against the release objects", optional.stdout)

    def test_a_repository_without_the_base_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            shutil.rmtree(tree / ".git")
            for command in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "x"]):
                subprocess.run(command, cwd=tree, env={**GIT_ENVIRONMENT, "HOME": str(tree)},
                               capture_output=True, timeout=300)
            result = self.run_check(tree, *ANCHORED)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("git anchor unavailable", result.stderr)

    def test_release_digests_are_read_from_the_objects(self) -> None:
        """Positive control: the comparison must be able to see a one-byte change.

        Round 6 renamed ``release_blob_digests`` to ``release_inventory`` and
        made every entry carry a Git file mode alongside the digest.
        """
        with tempfile.TemporaryDirectory() as directory:
            tree = copy_release_clone(Path(directory))
            release, notes = frozen.release_inventory(tree)
            self.assertEqual(len(release), 531)
            self.assertEqual(notes["tag"], f"{frozen.BASE_VERSION} -> {frozen.BASE_COMMIT}")
            relative = "certifiers/n15/spectral.py"
            actual = (tree / relative).read_bytes()
            self.assertEqual(release[relative].digest, hashlib.sha256(actual).hexdigest())
            self.assertNotEqual(release[relative].digest, hashlib.sha256(actual + b"\n").hexdigest())
            altered = {**release, relative: frozen.Entry("0" * 64, release[relative].mode)}
            problems = frozen.compare(release, altered, "control")
            self.assertEqual(len(problems), 1)
            self.assertIn("changed", problems[0])

    def test_the_repository_itself_is_anchored(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "check_frozen_corpus.py"), *ANCHORED],
            capture_output=True, text=True, timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("git_anchor=verified", result.stdout)


class ImportTimeRebinding(unittest.TestCase):
    """P1-B. Everything that runs before ``main()`` does."""

    def assert_rejected(self, source: str, fragment: str) -> None:
        diagnostic = check_entry_point(source)
        self.assertIsNotNone(diagnostic, "the mutated module was accepted")
        self.assertIn(fragment, diagnostic)

    def test_decorator_on_certify(self) -> None:
        self.assert_rejected(
            mutate_source(CERTIFY_DEF,
                          "def skip_proof(function):\n"
                          "    def replacement(target: Q = TARGET, max_splits: int = 2_000_000) -> CertificateResult:\n"
                          f"        return {FAKE}\n"
                          "    return replacement\n\n\n@skip_proof\n" + CERTIFY_DEF),
            "'certify' is decorated",
        )

    def test_decorator_on_an_unrelated_helper(self) -> None:
        self.assert_rejected(
            mutate_source("def decimal_string(value: Q, precision: int = 60) -> str:\n",
                          "def poison(function):\n"
                          "    globals()['certify'] = function\n"
                          "    return function\n\n\n@poison\n"
                          "def decimal_string(value: Q, precision: int = 60) -> str:\n"),
            "'decimal_string' is decorated",
        )

    def test_function_default_with_a_side_effect(self) -> None:
        self.assert_rejected(
            mutate_source("def main() -> None:\n",
                          "def poison(\n"
                          "    _=globals().__setitem__(\n"
                          '        "certify",\n'
                          f"        fake,\n"
                          "    )\n"
                          "):\n"
                          "    return None\n\n\ndef main() -> None:\n"),
            "is outside the audited shape",
        )

    def test_module_level_assignment_with_a_side_effect(self) -> None:
        """No lambda, no decorator: only the unevaluable right-hand side."""
        self.assert_rejected(
            mutate_source("def main() -> None:\n",
                          "def fake_certify(target: Q = TARGET, max_splits: int = 0) -> CertificateResult:\n"
                          f"    return {FAKE}\n\n\n"
                          'POISON = globals().__setitem__("certify", fake_certify)\n\n\n'
                          "def main() -> None:\n"),
            "has a value this checker cannot evaluate",
        )

    def test_module_level_lambda_anywhere(self) -> None:
        self.assert_rejected(
            mutate_source("def main() -> None:\n",
                          f"HELPER = lambda: {FAKE}\n\n\ndef main() -> None:\n"),
            "lambda is not part of the audited certifier shape",
        )

    def test_class_decorator(self) -> None:
        self.assert_rejected(
            mutate_source("class CertificateResult(NamedTuple):\n",
                          "def tag(cls):\n    return cls\n\n\n@tag\nclass CertificateResult(NamedTuple):\n"),
            "'CertificateResult' is decorated",
        )

    def test_class_keyword_such_as_a_metaclass(self) -> None:
        self.assert_rejected(
            mutate_source("class CertificateResult(NamedTuple):\n",
                          "class CertificateResult(NamedTuple, metaclass=type):\n"),
            "must not take class keywords",
        )

    def test_class_base_containing_a_call(self) -> None:
        self.assert_rejected(
            mutate_source("class CertificateResult(NamedTuple):\n",
                          "class CertificateResult(tuple(  [NamedTuple]  )[0]):\n"),
            "must derive from NamedTuple alone",
        )

    def test_executable_statement_in_the_class_body(self) -> None:
        self.assert_rejected(
            mutate_source("class CertificateResult(NamedTuple):\n    certified: bool\n",
                          "class CertificateResult(NamedTuple):\n"
                          "    print('side effect')\n    certified: bool\n"),
            "must be annotations without values",
        )

    def test_async_definition(self) -> None:
        """Refused while reading the module, before the entry-point rules run."""
        self.assert_rejected(
            mutate_source("def decimal_string(value: Q, precision: int = 60) -> str:\n",
                          "async def unused() -> None:\n    return None\n\n\n"
                          "def decimal_string(value: Q, precision: int = 60) -> str:\n"),
            "unsupported module-level statement AsyncFunctionDef",
        )

    def test_round4_mutations_are_still_rejected(self) -> None:
        cases = {
            "certify() on a false branch": (
                "    result = certify()\n", f"    result = certify() if False else {FAKE}\n"),
            "certify rebound at module level": (
                "def main() -> None:\n", f"certify = {FAKE}\n\n\ndef main() -> None:\n"),
            "second def certify": (
                "def main() -> None:\n",
                f"def certify(target=TARGET, max_splits=1):\n    return {FAKE}\n\n\ndef main() -> None:\n"),
            "early return after the status": (
                "    result = certify()\n",
                '    print("status:", "CERTIFIED")\n    return\n    result = certify()\n'),
            "result rebound after the call": (
                "    result = certify()\n", f"    result = certify()\n    result = {FAKE}\n"),
        }
        for label, (old, new) in cases.items():
            with self.subTest(label=label):
                self.assertIsNotNone(check_entry_point(mutate_source(old, new)),
                                     f"{label} was accepted")

    def test_every_published_certifier_is_accepted(self) -> None:
        rejected = []
        for n in EXPECTED_NS:
            for method in METHODS:
                path = ROOT / certifier_relpath(n, method)
                try:
                    extract_certifier_facts(path, verify_entry_point=True)
                except (EntryPointError, CertifierSourceError) as error:
                    rejected.append(f"{path.relative_to(ROOT)}: {error}")
        self.assertEqual(rejected, [], "the allow-list must accept the corpus it was derived from")

    def test_a_gutted_certifier_still_reaches_the_runner(self) -> None:
        """The stated limit: shape alone cannot see a wrong bound."""
        with tempfile.TemporaryDirectory() as directory:
            repo = copy_repository(Path(directory))
            path = repo / certifier_relpath(15, "spectral")
            body = path.read_text(encoding="utf-8")
            marker = "    root: Box = (ZERO, ONE, ZERO, ONE)\n"
            self.assertIn(marker, body)
            index = body.index(marker)
            gutted = body[:index] + f"    return {FAKE}\n\n\ndef _unused() -> None:\n    return None\n"
            gutted += body[body.index("def decimal_string("):]
            path.write_text(gutted, encoding="utf-8")
            diagnostic = check_entry_point(gutted)
        self.assertIsNone(
            diagnostic,
            "the entry-point check is not claimed to catch a rewritten certify() body; "
            "the frozen-corpus anchor is what does",
        )


class EntryPointInventoryIsStillTrue(unittest.TestCase):
    """The allow-list is only sound while the corpus really has this shape."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.trees = {
            (n, method): ast.parse((ROOT / certifier_relpath(n, method)).read_text(encoding="utf-8"))
            for n in EXPECTED_NS for method in METHODS
        }

    def test_no_definition_anywhere_is_decorated(self) -> None:
        decorated = [
            f"{key}: {node.name}"
            for key, tree in self.trees.items()
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list
        ]
        self.assertEqual(decorated, [])

    def test_definition_count_and_placement(self) -> None:
        total = sum(
            1 for tree in self.trees.values() for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        module_level = sum(
            1 for tree in self.trees.values() for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        self.assertEqual(total, 927)
        self.assertEqual(module_level, 927, "a nested definition would need its own rule")

    def test_default_expression_shapes(self) -> None:
        kinds: collections.Counter[str] = collections.Counter()
        for tree in self.trees.values():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    arguments = node.args
                    for default in list(arguments.defaults) + [d for d in arguments.kw_defaults if d is not None]:
                        kinds[type(default).__name__] += 1
                        if any(isinstance(inner, ast.Call) for inner in ast.walk(default)):
                            kinds["contains-call"] += 1
        self.assertEqual(dict(kinds), {"Name": 88, "Constant": 176})

    def test_class_shapes(self) -> None:
        shapes: collections.Counter[tuple] = collections.Counter()
        for tree in self.trees.values():
            classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
            self.assertEqual(len(classes), 1)
            node = classes[0]
            shapes[(
                tuple(ast.unparse(base) for base in node.bases),
                tuple(keyword.arg for keyword in node.keywords),
                len(node.decorator_list),
                tuple(sorted({type(statement).__name__ for statement in node.body})),
            )] += 1
        self.assertEqual(dict(shapes), {(("NamedTuple",), (), 0, ("AnnAssign",)): 88})

    def test_no_lambda_and_no_async(self) -> None:
        offenders = [
            f"{key}: {type(node).__name__}"
            for key, tree in self.trees.items()
            for node in ast.walk(tree)
            if isinstance(node, (ast.Lambda, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        self.assertEqual(offenders, [])


class WorkflowsKeepTheirContract(unittest.TestCase):
    """§5: what the workflow files must still say, checked without a YAML parser."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.files = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        }

    def test_both_workflows_exist(self) -> None:
        self.assertEqual(sorted(self.files), ["full-replay.yml", "smoke-test.yml"])

    def test_every_action_is_pinned_to_a_full_sha(self) -> None:
        import re
        for name, text in self.files.items():
            with self.subTest(name=name):
                uses = re.findall(r"^\s*(?:- )?uses: (.+)$", text, re.M)
                self.assertTrue(uses)
                for reference in uses:
                    self.assertRegex(reference, r"@[0-9a-f]{40}( #.*)?$")

    def test_checkout_is_unshallow_and_credential_free(self) -> None:
        for name, text in self.files.items():
            with self.subTest(name=name):
                self.assertIn("persist-credentials: false", text)
                self.assertIn("fetch-depth: 0", text)

    def test_permissions_are_read_only(self) -> None:
        import re
        for name, text in self.files.items():
            with self.subTest(name=name):
                self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")

    def test_frozen_corpus_is_the_first_step_and_is_anchored(self) -> None:
        import re
        for name, text in self.files.items():
            with self.subTest(name=name):
                steps = re.findall(r"^      - name: (.+)$", text, re.M)
                self.assertTrue(steps)
                self.assertIn("frozen mathematical corpus", steps[0])
                self.assertIn("--require-git-anchor", text)
                self.assertIn(f"--expect-base-commit {frozen.BASE_COMMIT}", text)

    def test_required_check_names_are_unchanged(self) -> None:
        import re
        self.assertRegex(self.files["smoke-test.yml"], r"(?m)^name: smoke-test$")
        self.assertRegex(self.files["smoke-test.yml"], r"(?m)^  verify:$")
        self.assertRegex(self.files["full-replay.yml"], r"(?m)^name: full-certificate-replay$")
        self.assertRegex(self.files["full-replay.yml"], r"(?m)^  verify-all:$")

    def test_source_provenance_checks_are_kept(self) -> None:
        text = self.files["full-replay.yml"]
        self.assertIn("--expect-source-commit", text)
        self.assertIn("--expect-source-clean", text)


if __name__ == "__main__":
    unittest.main()
