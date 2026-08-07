"""Mutation tests for the second audit round.

Every test here corrupts exactly one thing in a throwaway copy and requires the
relevant check to reject it *for that reason*: the expected diagnostic is
asserted, not just the exit code, so a test cannot pass because some earlier
unrelated error happened to fire first. Each mutation also asserts that it was
actually applied.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from support import (  # noqa: E402
    REPO_ROOT,
    copy_repository,
    dump_results_json,
    load_json,
    read_text,
    replace_once,
    run_script,
    shared_quick_replay,
    write_text,
)

from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    METHODS,
    ROOT,
    StrictJSONError,
    certifier_relpath,
    configuration_relpath,
    exact_square_symmetries,
    extract_certifier_facts,
    load_json_strict,
    load_results_csv,
    read_coordinates_csv,
)

WITNESS_NAMES = ("UPPER_WITNESS", "WITNESS_POINT", "WITNESS")


def mutate_witness_x(repo: Path, n: int, new_literal: str) -> None:
    """Rewrite the witness x coordinate of both certifiers of one configuration."""
    for method in METHODS:
        path = repo / certifier_relpath(n, method)
        lines = read_text(path).split("\n")
        changed = 0
        for index, line in enumerate(lines):
            if not any(re.search(rf"\b{name}\b\s*[:=]", line) for name in WITNESS_NAMES):
                continue
            replaced, count = re.subn(r'Q\("[^"]+"\)', f'Q("{new_literal}")', line, count=1)
            if count:
                lines[index] = replaced
                changed += count
                break
        if changed != 1:
            raise AssertionError(f"{path}: witness literal was not rewritten")
        write_text(path, "\n".join(lines))


class EntryPointShape(unittest.TestCase):
    """P1-A: a module must still run its proof before declaring a status."""

    def assert_semantic_rejects(self, repo: Path, fragment: str) -> None:
        result = run_script(repo, "check_semantic_consistency.py")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn(fragment, output)

    def test_guard_that_prints_certified_without_running_the_proof_is_rejected(self) -> None:
        """Requirement 1."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / certifier_relpath(15, "spectral")
            replace_once(path, 'if __name__ == "__main__":\n    main()', 'if __name__ == "__main__":\n    print("status: CERTIFIED")')
            self.assert_semantic_rejects(repo, "the __main__ guard body must be exactly `main()`")

    def test_removing_the_final_certified_assertion_is_rejected(self) -> None:
        """Requirement 2."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / certifier_relpath(15, "spectral")
            replace_once(path, "    assert result.certified\n", "")
            self.assert_semantic_rejects(repo, "final assertions are wrong: missing ['certified']")

    def test_main_that_never_calls_certify_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / certifier_relpath(15, "spectral")
            replace_once(path, "    result = certify()", "    result = None")
            self.assert_semantic_rejects(repo, "must call certify() directly, found Constant")

    def test_all_current_certifiers_pass_the_entry_point_shape(self) -> None:
        """Requirement: the allow-list must admit the whole existing corpus."""
        checked = 0
        for n in EXPECTED_NS:
            for method in METHODS:
                with self.subTest(n=n, method=method):
                    extract_certifier_facts(ROOT / certifier_relpath(n, method), verify_entry_point=True)
                    checked += 1
        self.assertEqual(checked, 88)


class WitnessDomain(unittest.TestCase):
    """P1-B: the witness must lie in the unit square."""

    def test_out_of_domain_witness_is_rejected_by_generator_and_semantic_check(self) -> None:
        """Requirement 3."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            mutate_witness_x(repo, 15, "2")

            generator = run_script(repo, "regenerate_certified_results.py", "--check")
            self.assertNotEqual(generator.returncode, 0)
            self.assertIn("outside the unit square", generator.stdout + generator.stderr)

            semantic = run_script(repo, "check_semantic_consistency.py")
            self.assertEqual(semantic.returncode, 1, semantic.stdout)
            self.assertIn("outside the unit square", semantic.stdout + semantic.stderr)

            audit = run_script(repo, "audit_upper_witness.py", "--quiet")
            self.assertNotEqual(audit.returncode, 0)
            self.assertIn("outside the unit square", audit.stdout + audit.stderr)

    def test_all_four_corners_are_accepted(self) -> None:
        from certificate_lib import validate_witness_point
        from fractions import Fraction

        lights = read_coordinates_csv(ROOT / configuration_relpath(15))
        for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
            with self.subTest(corner=(x, y)):
                point = (Fraction(x), Fraction(y))
                self.assertEqual(validate_witness_point(point, lights, "t"), point)


class ConfigurationSetOfTheFullReplay(unittest.TestCase):
    """P1-C: eighty-eight certifiers is not the same as the published corpus."""

    def test_equal_count_swap_of_n52_for_n53_is_rejected(self) -> None:
        """Requirement 4."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            source = repo / "certifiers" / "n52"
            target = repo / "certifiers" / "n53"
            self.assertTrue(source.is_dir())
            source.rename(target)
            self.assertEqual(len(list((repo / "certifiers").glob("n*"))), 44)

            result = run_script(repo, "verify_all.py", "--all", "--jobs", "1")
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("missing:    [52]", output)
            self.assertIn("unexpected: [53]", output)

    def test_a_missing_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            shutil.rmtree(repo / "certifiers" / "n52")
            result = run_script(repo, "verify_all.py", "--all", "--jobs", "1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing:    [52]", result.stdout + result.stderr)

    def test_a_missing_method_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            (repo / certifier_relpath(52, "componentwise")).unlink()
            result = run_script(repo, "verify_all.py", "--all", "--jobs", "1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing certifier: certifiers/n52/componentwise.py", result.stdout + result.stderr)


class SuccessContractCoversStderr(unittest.TestCase):
    """P1-D: a failure on stderr is a failure."""

    def test_certified_on_stdout_with_not_certified_on_stderr_is_rejected(self) -> None:
        """Requirement 5."""
        from verifier_runner import classify

        status, certified, reason = classify(0, False, "status: CERTIFIED\n", "status: NOT_CERTIFIED\n")
        self.assertFalse(certified)
        self.assertIn("stderr declares a status", reason or "")

    def test_certified_on_stdout_with_any_status_on_stderr_is_rejected(self) -> None:
        from verifier_runner import classify

        _, certified, reason = classify(0, False, "status: CERTIFIED\n", "status: CERTIFIED\n")
        self.assertFalse(certified)
        self.assertIn("stderr declares a status", reason or "")

    def test_forbidden_token_on_stderr_is_rejected(self) -> None:
        from verifier_runner import classify

        _, certified, reason = classify(0, False, "status: CERTIFIED\n", "the job FAILED to converge\n")
        self.assertFalse(certified)
        self.assertIn("FAILED", reason or "")

    def test_normal_output_with_empty_stderr_is_accepted(self) -> None:
        from verifier_runner import classify

        status, certified, reason = classify(0, False, "status: CERTIFIED\nsplits: 3\n", "")
        self.assertEqual(status, "CERTIFIED")
        self.assertTrue(certified)
        self.assertIsNone(reason)

    def test_harmless_stderr_text_is_still_accepted(self) -> None:
        from verifier_runner import classify

        _, certified, _ = classify(0, False, "status: CERTIFIED\n", "note: this run was slow\n")
        self.assertTrue(certified)

    def test_every_stored_certifier_run_has_empty_stderr(self) -> None:
        logs = sorted((ROOT / "evidence" / "full-cleanroom-replay" / "logs").glob("*.stderr.txt"))
        self.assertEqual(len(logs), 88)
        for log in logs:
            self.assertEqual(log.read_text(encoding="utf-8").strip(), "", log.name)


class FullReplayCsvIntegrity(unittest.TestCase):
    """P1-F: eighty-eight rows is not the same as eighty-eight distinct keys."""

    def test_duplicated_and_missing_csv_row_keeping_88_rows_is_rejected(self) -> None:
        """Requirement 6."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "evidence" / "full-cleanroom-replay" / "PUBLIC_REPO_FULL_REPLAY.csv"
            text = read_text(path)
            lines = text.splitlines()
            header, rows = lines[0], lines[1:]
            self.assertEqual(len(rows), 88)
            rows[1] = rows[0]  # duplicate the first key, drop the second
            self.assertEqual(len(rows), 88)
            write_text(path, "\n".join([header, *rows]) + "\n")

            result = run_script(repo, "check_semantic_consistency.py")
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, output)
            self.assertIn("full replay CSV: duplicate (n, method) rows", output)
            self.assertIn("full replay CSV: missing rows", output)


class StrictJsonParsing(unittest.TestCase):
    """P2-A: research evidence must not depend on which duplicate key wins."""

    def test_duplicate_object_key_is_rejected(self) -> None:
        """Requirement 7."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "d.json"
            path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(StrictJSONError) as caught:
                load_json_strict(path)
            self.assertIn("duplicate object key", str(caught.exception))

    def test_non_finite_constants_are_rejected(self) -> None:
        for body in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "d.json"
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(StrictJSONError) as caught:
                    load_json_strict(path)
                self.assertIn("non-finite JSON constant", str(caught.exception))

    def test_duplicate_key_in_a_published_json_is_rejected_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "data" / "results-metadata.json"
            replace_once(path, '  "7": {', '  "7": {\n    "notes": "duplicated",\n    "notes": "duplicated",')
            result = run_script(repo, "check_semantic_consistency.py")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("duplicate object key", result.stdout + result.stderr)


class MetadataSchema(unittest.TestCase):
    """P2-A: the metadata file has an exact shape."""

    def mutate(self, transform) -> "tuple[int, str]":
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "data" / "results-metadata.json"
            raw = load_json(path)
            transform(raw)
            write_text(path, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
            result = run_script(repo, "check_semantic_consistency.py")
            return result.returncode, result.stdout + result.stderr

    def test_extra_metadata_field_is_rejected(self) -> None:
        """Requirement 8."""
        code, output = self.mutate(lambda raw: raw["7"].update({"extra": "x"}))
        self.assertEqual(code, 1, output)
        self.assertIn("field mismatch", output)

    def test_missing_metadata_field_is_rejected(self) -> None:
        code, output = self.mutate(lambda raw: raw["7"].pop("notes"))
        self.assertEqual(code, 1, output)
        self.assertIn("field mismatch", output)

    def test_unexpected_configuration_in_metadata_is_rejected(self) -> None:
        def add(raw):
            raw["53"] = copy.deepcopy(raw["52"])

        code, output = self.mutate(add)
        self.assertEqual(code, 1, output)
        self.assertIn("configuration set mismatch", output)

    def test_wrong_metadata_field_type_is_rejected(self) -> None:
        code, output = self.mutate(lambda raw: raw["7"].update({"upper_decimal_places": "68"}))
        self.assertEqual(code, 1, output)
        self.assertIn("expected int", output)


class ReplayIndexSchema(unittest.TestCase):
    """P2-A: the stored replay index must be exactly the expected key set."""

    def test_unexpected_key_in_the_stored_replay_is_rejected(self) -> None:
        """Requirement 9."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = copy_repository(Path(temporary))
            path = repo / "evidence" / "full-cleanroom-replay" / "PUBLIC_REPO_FULL_REPLAY.json"
            replay = load_json(path)
            extra = copy.deepcopy(replay["results"][0])
            extra["n"] = 53
            replay["results"].append(extra)
            write_text(path, json.dumps(replay, indent=2))
            result = run_script(repo, "check_semantic_consistency.py")
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, output)
            self.assertIn("unexpected record (53, 'componentwise')", output)


class FreshReplayOutput(unittest.TestCase):
    """P1-E: a replay directory must be new, and bound to what it ran.

    One real quick replay is produced for the whole class and copied per test.
    Running a fresh proof inside each test made the suite's runtime dominated
    by branch-and-bound while checking nothing extra: each mutation only needs
    a valid replay directory to corrupt, not a separately proved one. The
    demonstration that a real replay still passes end to end stays here (the
    first test below) and in the smoke workflow.
    """

    fixture_repo: Path
    fixture_replay: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_repo, cls.fixture_replay = shared_quick_replay()

    def replay_copy(self, temporary: Path) -> Path:
        destination = temporary / "replay"
        shutil.copytree(self.fixture_replay, destination)
        return destination

    def test_the_fixture_replay_validates_end_to_end(self) -> None:
        result = run_script(self.fixture_repo, "validate_replay_output.py", str(self.fixture_replay))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("problems=0", result.stdout)

    def test_non_empty_output_directory_is_rejected(self) -> None:
        """Requirement 10."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            output.mkdir()
            (output / "stale.txt").write_text("old", encoding="utf-8")
            result = run_script(
                self.fixture_repo, "verify_all.py", "--quick", "--jobs", "1", "--output-dir", str(output)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--output-dir is not empty", result.stdout + result.stderr)

    def test_script_sha_mismatch_is_detected_by_the_validator(self) -> None:
        """Requirement 11."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            shutil.copytree(self.fixture_repo, repo)
            replay = self.replay_copy(Path(temporary))

            clean = run_script(repo, "validate_replay_output.py", str(replay))
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)

            certifier = repo / certifier_relpath(14, "spectral")
            before = certifier.read_bytes()
            certifier.write_bytes(before + b"\n# appended\n")
            self.assertNotEqual(certifier.read_bytes(), before)

            dirty = run_script(repo, "validate_replay_output.py", str(replay))
            output_text = dirty.stdout + dirty.stderr
            self.assertEqual(dirty.returncode, 1, output_text)
            self.assertIn("recorded script_sha256 does not match", output_text)

    def test_missing_log_is_detected_by_the_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            removed = replay / "n14_spectral.stdout.txt"
            self.assertTrue(removed.is_file())
            removed.unlink()
            result = run_script(self.fixture_repo, "validate_replay_output.py", str(replay))
            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, text)
            self.assertIn("missing log files", text)

    def test_stale_file_in_the_replay_directory_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            replay = self.replay_copy(Path(temporary))
            (replay / "leftover.log").write_text("stale", encoding="utf-8")
            result = run_script(self.fixture_repo, "validate_replay_output.py", str(replay))
            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, text)
            self.assertIn("unexpected files in the replay directory", text)


class EndOfLineProtection(unittest.TestCase):
    """P1-G: manifest bytes must survive any core.autocrlf setting."""

    SAMPLE = (
        "data/certified-results.csv",
        "data/certified-results.json",
        "certifiers/n15/spectral.py",
        "evidence/saved-replays/n15/spectral.txt",
    )

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available; this check cannot be verified in this environment")

    def _round_trip(self, autocrlf: str, with_attributes: bool) -> "tuple[int, int]":
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for command in (
                ["git", "init", "-q", "."],
                ["git", "config", "core.autocrlf", autocrlf],
                ["git", "config", "user.email", "t@example.com"],
                ["git", "config", "user.name", "t"],
            ):
                subprocess.run(command, cwd=work, check=True, capture_output=True)
            if with_attributes:
                shutil.copy(REPO_ROOT / ".gitattributes", work / ".gitattributes")
            for relative in self.SAMPLE:
                (work / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(REPO_ROOT / relative, work / relative)
            subprocess.run(["git", "add", "-A"], cwd=work, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=work, check=True, capture_output=True)

            blobs = 0
            for relative in self.SAMPLE:
                stored = subprocess.run(
                    ["git", "cat-file", "-p", f":{relative}"], cwd=work, check=True, capture_output=True
                ).stdout
                blobs += stored == (REPO_ROOT / relative).read_bytes()
            for relative in self.SAMPLE:
                (work / relative).unlink()
            subprocess.run(["git", "checkout", "-q", "--", "."], cwd=work, check=True, capture_output=True)
            checkouts = sum(
                (work / relative).read_bytes() == (REPO_ROOT / relative).read_bytes() for relative in self.SAMPLE
            )
            return blobs, checkouts

    def test_bytes_survive_every_autocrlf_setting(self) -> None:
        """Requirement 12."""
        for autocrlf in ("false", "true", "input"):
            with self.subTest(autocrlf=autocrlf):
                blobs, checkouts = self._round_trip(autocrlf, with_attributes=True)
                self.assertEqual(blobs, len(self.SAMPLE), f"blob bytes changed with core.autocrlf={autocrlf}")
                self.assertEqual(checkouts, len(self.SAMPLE), f"checkout bytes changed with core.autocrlf={autocrlf}")

    def test_the_check_would_notice_without_the_attributes_file(self) -> None:
        """The control: without .gitattributes the round trip must break."""
        blobs, checkouts = self._round_trip("input", with_attributes=False)
        self.assertLess(min(blobs, checkouts), len(self.SAMPLE), "the EOL round-trip check cannot fail, so it proves nothing")


class ExactSymmetryClassification(unittest.TestCase):
    """P1-H: pin the exact facts the prose is now required to match."""

    def symmetries(self, n: int) -> "tuple[str, ...]":
        return exact_square_symmetries(read_coordinates_csv(ROOT / configuration_relpath(n)))

    def test_n15_has_no_non_trivial_exact_symmetry(self) -> None:
        """Requirement 13."""
        self.assertEqual(self.symmetries(15), ("identity",))

    def test_n16_is_exactly_d2_and_not_more(self) -> None:
        """Requirement 13."""
        self.assertEqual(self.symmetries(16), ("identity", "reflect_x", "reflect_y", "rotate_180"))

    def test_prose_no_longer_claims_a_symmetry_n15_does_not_have(self) -> None:
        rows = {int(row["n"]): row for row in load_results_csv()}
        self.assertNotEqual(rows[15]["symmetry_or_family"], "left-right reflection only")
        self.assertIn("no exact non-identity square symmetry", rows[15]["symmetry_or_family"])
        self.assertNotIn("none/full square", rows[16]["symmetry_or_family"])

    def test_metadata_and_generated_table_agree(self) -> None:
        from certificate_lib import load_results_metadata

        metadata = load_results_metadata()
        rows = {int(row["n"]): row for row in load_results_csv()}
        for n in EXPECTED_NS:
            with self.subTest(n=n):
                self.assertEqual(rows[n]["symmetry_or_family"], metadata[n]["symmetry_or_family"])


if __name__ == "__main__":
    unittest.main()
