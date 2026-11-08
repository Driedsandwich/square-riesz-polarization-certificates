"""Round 7: per-record release checks, full-count replays, contained source errors.

Each test here exercises a defect found by the post-v1.0.2 audit. Mutations are
applied to throwaway copies; nothing writes to this repository.
"""

from __future__ import annotations

import ast
import csv
import io
import json
import os
import re
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
    git_available,
    load_json,
    run_script,
    shared_quick_replay,
    write_fake_certifier,
)

import build_publication_attestation as attestation  # noqa: E402
import build_release_assets as builder  # noqa: E402
import check_frozen_corpus as frozen  # noqa: E402
from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    METHODS,
    CertifierSourceError,
    certifier_decimal_string,
    certifier_relpath,
    exact_potential,
    extract_certifier_facts,
    validate_proof_output,
)
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


class ReplayScriptsRefuseOptimizedMode(unittest.TestCase):
    """The certifiers of n18, n20 and n22-n52 prove the quarter square only.

    Covering the full square rests on two module-level ``assert`` statements of
    reflection symmetry, which ``python -O`` removes. The certifiers are frozen,
    so the protection lives in the replay scripts, which must refuse to start —
    before running any certifier — under either way of enabling optimisation.
    ``verify_all.py -O`` is covered in ``test_success_contract.py``.
    """

    def run_refused(self, script: str, *, flag: bool, arguments: "tuple[str, ...]") -> None:
        environment = dict(os.environ)
        environment.pop("PYTHONOPTIMIZE", None)
        command = [sys.executable, "-B"]
        if flag:
            command.append("-O")
        else:
            environment["PYTHONOPTIMIZE"] = "1"
        result = subprocess.run(
            [*command, str(REPO_ROOT / "scripts" / script), *arguments],
            capture_output=True,
            text=True,
            timeout=120,
            env=environment,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("refusing to run", output)
        self.assertNotIn("== n=", output)
        self.assertNotIn("status:", output)

    def test_verify_one_refuses_dash_o(self) -> None:
        self.run_refused("verify_one.py", flag=True, arguments=("--n", "22", "--method", "both"))

    def test_verify_one_refuses_pythonoptimize(self) -> None:
        self.run_refused("verify_one.py", flag=False, arguments=("--n", "22", "--method", "both"))

    def test_verify_all_refuses_pythonoptimize(self) -> None:
        self.run_refused("verify_all.py", flag=False, arguments=("--quick", "--jobs", "1"))



# --------------------------------------------------------------------------
# The workflows run their gates, not just mention them
# --------------------------------------------------------------------------

FROZEN_GATE = ("python -B scripts/check_frozen_corpus.py --expect-base-version "
               f"{frozen.BASE_VERSION} --expect-base-commit {frozen.BASE_COMMIT} --require-git-anchor")
STATIC_GATES = [
    ("frozen mathematical corpus (anchored to v1.0.1 objects)", FROZEN_GATE),
    ("unit tests", "python -B -m unittest discover -s tests -v"),
    ("manifest verification", "python -B scripts/verify_manifest.py"),
    ("release structure check", "python -B scripts/check_release.py"),
    ("semantic consistency check", "python -B scripts/check_semantic_consistency.py"),
    ("result table generation is current", "python -B scripts/regenerate_certified_results.py --check"),
    ("upper witness audit", "python -B scripts/audit_upper_witness.py"),
]
#: Every step with a ``run:`` key, in order, and the exact command it runs.
GATE_STEPS = {
    "smoke-test.yml": STATIC_GATES + [
        ("quick verifier replay", "python -B scripts/verify_all.py --quick --jobs 2"),
    ],
    "full-replay.yml": STATIC_GATES + [
        ("replay all 88 certifiers",
         "python -B scripts/verify_all.py --all --jobs 2 --output-dir ci-full-replay"),
        ("validate replay output",
         'python -B scripts/validate_replay_output.py ci-full-replay --expect-all '
         '--expect-source-commit "$GITHUB_SHA" --expect-source-clean'),
    ],
}


def workflow_steps(text: str) -> list[dict]:
    """The steps of the workflow's one job, read line by line.

    Enough YAML for these two files and no more: a step starts at ``      - ``,
    its keys sit at eight spaces, and a block scalar continues at ten. Comment
    lines are dropped. Anything this reader does not understand inside the steps
    list is kept as an unknown key, which ``gate_problems`` refuses.
    """
    lines = text.splitlines()
    start = lines.index("    steps:")
    steps: list[dict] = []
    block: "str | None" = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < 6:
            break
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if indent == 6 and stripped.startswith("- "):
            steps.append({})
            stripped, indent = stripped[2:], 8
        if not steps:
            raise AssertionError(f"line before the first step: {line!r}")
        step = steps[-1]
        if indent == 8:
            key, _, value = stripped.partition(":")
            value = value.strip()
            block = key if value in ("|", ">", "|-", ">-") else None
            step[key] = [] if block else value
        elif indent >= 10 and block is not None:
            step[block].append(stripped)
        elif indent >= 10:
            continue  # the body of `with:`, which configures an action
        else:
            step.setdefault("?unparsed", []).append(line)
    return steps


def command_of(run) -> str:
    """One command from a run value, joining backslash continuations."""
    parts = run if isinstance(run, list) else [run]
    return " ".join(part.rstrip("\\").strip() for part in parts if part.strip())


def gate_problems(name: str, text: str) -> list[str]:
    problems: list[str] = []
    for word in ("continue-on-error", "|| true", "|| :", "set +e"):
        if word in text:
            problems.append(f"{name}: contains {word!r}")
    job = re.search(r"(?m)^  [a-z-]+:\n((?:    .*\n|\n)*)", text.split("\njobs:\n", 1)[1])
    if job and re.search(r"(?m)^    if:", job.group(1)):
        problems.append(f"{name}: the job has an `if:` condition")
    steps = workflow_steps(text)
    run_steps = [step for step in steps if "run" in step]
    actual = [(step.get("name"), command_of(step["run"])) for step in run_steps]
    if actual != GATE_STEPS[name]:
        problems.append(f"{name}: run steps are {actual}, expected {GATE_STEPS[name]}")
    for step in run_steps:
        extra = sorted(set(step) - {"name", "run"})
        if extra:
            problems.append(f"{name}: step {step.get('name')!r} has {extra}; a gate step runs "
                            "unconditionally, in the default shell, with nothing else")
    first = next((step for step in steps if "uses" not in step), None)
    if first is None or first.get("name") != STATIC_GATES[0][0]:
        problems.append(f"{name}: the first non-action step is not the frozen-corpus gate")
    return problems


def neutralise_frozen_step(text: str) -> str:
    """The Codex audit's mutation: ':' runs, the real command survives as comments."""
    start = text.index("        run: |\n", text.index("      - name: frozen mathematical corpus"))
    end = text.index("      - name:", start + 1)
    body = text[start:end].splitlines()[1:]
    return (text[:start] + "        run: |\n          : # gate skipped\n"
            + "".join(f"          # {line.strip()}\n" for line in body) + text[end:])


class WorkflowGateStepsRunUnconditionally(unittest.TestCase):
    """The workflow contract test only looked for strings anywhere in the file.

    With the frozen-corpus step's command replaced by ':' and kept as comments,
    every contract test and the whole unit suite still passed. These tests read
    each step and require the exact command, with no condition attached.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.files = {path.name: path.read_text(encoding="utf-8")
                     for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))}

    def test_both_workflows_run_exactly_their_gates(self) -> None:
        self.assertEqual(sorted(self.files), sorted(GATE_STEPS))
        for name, text in self.files.items():
            with self.subTest(workflow=name):
                self.assertEqual(gate_problems(name, text), [])

    def test_every_way_of_skipping_a_gate_is_caught(self) -> None:
        mutations = {
            "command neutralised, kept as comments": neutralise_frozen_step,
            "condition on the step": lambda text: text.replace(
                "      - name: unit tests\n", "      - name: unit tests\n        if: false\n", 1),
            "failure ignored": lambda text: text.replace(
                "run: python -B scripts/check_release.py",
                "run: python -B scripts/check_release.py || true", 1),
            "continue on error": lambda text: text.replace(
                "      - name: manifest verification\n",
                "      - name: manifest verification\n        continue-on-error: true\n", 1),
            "flag dropped": lambda text: text.replace(" \\\n            --require-git-anchor", "", 1),
            "step removed": lambda text: re.sub(
                r"(?m)^      - name: semantic consistency check\n        run: .*\n", "", text, count=1),
            "different shell": lambda text: text.replace(
                "      - name: upper witness audit\n",
                "      - name: upper witness audit\n        shell: bash {0}\n", 1),
            "job condition": lambda text: re.sub(
                r"(?m)^(    runs-on: ubuntu-latest\n)", r"    if: false\n\1", text, count=1),
        }
        for name, text in self.files.items():
            for label, mutate in mutations.items():
                with self.subTest(workflow=name, mutation=label):
                    mutated = mutate(text)
                    self.assertNotEqual(mutated, text, "the mutation did not apply")
                    self.assertTrue(gate_problems(name, mutated))


# --------------------------------------------------------------------------
# The three proof counters describe one binary tree
# --------------------------------------------------------------------------

class ProofCountersDescribeOneTree(unittest.TestCase):
    """Each counter used to be checked on its own.

    ``splits=0, leaf_count=2, maximum_depth=999999`` had no problems, and a real
    log with one leaf added passed ``validate_replay_output.py --expect-all``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = extract_certifier_facts(REPO_ROOT / "certifiers" / "n07" / "spectral.py",
                                            verify_entry_point=True)
        cls.log = (REPO_ROOT / "evidence" / "full-cleanroom-replay" / "logs"
                   / "n07_spectral.stdout.txt").read_text(encoding="utf-8")

    def with_counts(self, **values: int) -> str:
        text = self.log
        for field, value in values.items():
            text, count = re.subn(rf"(?m)^{field}: .*$", f"{field}: {value}", text)
            self.assertEqual(count, 1, field)
        return text

    def counts(self) -> "tuple[int, int, int]":
        read = lambda field: int(re.search(rf"(?m)^{field}: (\d+)$", self.log).group(1))
        return read("splits"), read("leaf_count"), read("maximum_depth")

    def test_the_real_log_passes(self) -> None:
        self.assertEqual(validate_proof_output(self.log, self.facts, "control"), [])

    def test_impossible_and_inconsistent_counters_are_rejected(self) -> None:
        splits, leaves, depth = self.counts()
        cases = {
            "impossible tree": dict(splits=0, leaf_count=2, maximum_depth=999999),
            "one leaf added": dict(leaf_count=leaves + 1),
            "one split removed": dict(splits=splits - 1),
            "deeper than the splits allow": dict(maximum_depth=splits + 1),
            "shallower than the leaves require": dict(maximum_depth=(leaves - 1).bit_length() - 1),
        }
        for label, values in cases.items():
            with self.subTest(case=label):
                problems = validate_proof_output(self.with_counts(**values), self.facts, label)
                self.assertTrue(problems)

    def test_every_stored_log_satisfies_the_tree_relations(self) -> None:
        """The relation is a fact of the frozen corpus, not of one example."""
        logs = sorted((REPO_ROOT / "evidence").rglob("*.stdout.txt"))
        self.assertGreaterEqual(len(logs), 88)
        checked = 0
        for path in logs:
            text = path.read_text(encoding="utf-8")
            values = {field: re.search(rf"(?m)^{field}: (\d+)$", text)
                      for field in ("splits", "leaf_count", "maximum_depth")}
            if not all(values.values()):
                continue
            splits, leaves, depth = (int(values[f].group(1)) for f in ("splits", "leaf_count", "maximum_depth"))
            with self.subTest(log=path.name):
                self.assertEqual(leaves, splits + 1)
                self.assertTrue((leaves - 1).bit_length() <= depth <= splits)
            checked += 1
        self.assertGreaterEqual(checked, 88)


# --------------------------------------------------------------------------
# No local path reaches the public attestation
# --------------------------------------------------------------------------

class AttestationPathScanReadsEveryDepth(unittest.TestCase):
    """The attestation's scan read only top-level values, for three spellings.

    The build record is embedded in the attestation, so a path nested in it was
    published. A path written ``C:\\Users`` passed too: the pattern only matched
    a doubled backslash.
    """

    def scan(self, document: dict) -> bool:
        try:
            attestation.check_no_secrets_or_placeholders(document)
        except attestation.Refused:
            return True
        return False

    def test_paths_at_any_depth_and_in_any_spelling_are_refused(self) -> None:
        for document in ({"record": {"ran": {"x": {"stdout_tail": ["/home/someone/repository"]}}}},
                         {"record": {"tail": ["root=/Users/someone/work"]}},
                         {"path": "C:\\Users\\someone"},
                         {"note": "built in /private/var/folders/xx/T/build"},
                         {"path": "\\\\server\\share"}):
            with self.subTest(document=document):
                self.assertTrue(self.scan(document))

    # Each of these passed both scanners under an earlier pattern, which required
    # an ASCII character after the slash and treated a colon or an option letter
    # before it as part of a word (found by the two November 2026 reviews of the
    # v1.0.2 rebuild).
    NON_ASCII_AND_UNUSUAL_PATHS = (
        {"platform": "/秘密"},
        {"platform": "/ space"},
        {"path": "//server/share"},
        {"note": "built in /ビルド"},
        {"path": "\\\\サーバ\\share"},
        {"record": {"tail": ["root=/ñ"]}},
        {"argv": ["cc", "-I/home/someone/include"]},
        {"url": "file:///home/someone/build"},
        {"note": "build:/home/someone/build"},
        {"record": {"tail": ["root=/ private/build"]}},
    )

    def test_non_ascii_and_unusual_paths_are_refused_by_both_scanners(self) -> None:
        for document in self.NON_ASCII_AND_UNUSUAL_PATHS:
            with self.subTest(document=document):
                self.assertTrue(self.scan(document))
                self.assertTrue(builder.find_absolute_paths(document))

    def test_ordinary_values_pass(self) -> None:
        document = {"url": "https://github.com/Driedsandwich/square-riesz-polarization-certificates",
                    "argv": ["git", "-c", "core.attributesFile=/dev/null", "--output=<OUTPUT_ZIP>"],
                    "tail": ["certified_rows=44 certifier_dirs=44 replay=88/88 issues=0"],
                    "ratio": "88 / 88 and a/b",
                    "non_ascii_url": "https://example.org/資料/結果",
                    "relative": "資料/結果",
                    "prefix": "--prefix=square-riesz-polarization-certificates-v1.0.2/",
                    "ref": "refs/tags/v1.0.2"}
        self.assertFalse(self.scan(document))
        self.assertEqual(builder.find_absolute_paths(document), [])

    def test_builder_and_attestation_share_one_pattern(self) -> None:
        self.assertEqual(attestation.LOCAL_PATH.pattern, builder.LOCAL_PATH.pattern)


# --------------------------------------------------------------------------
# The attestation's mathematical delta is measured against v1.0.1
# --------------------------------------------------------------------------

def mathematical_delta_literal() -> dict:
    tree = ast.parse((REPO_ROOT / "scripts" / "build_publication_attestation.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "mathematical_delta_from_v1_0_1":
                    return ast.literal_eval(value)
    raise AssertionError("mathematical_delta_from_v1_0_1 not found")


@unittest.skipUnless(git_available() and frozen.git_repository(REPO_ROOT),
                     "needs the Git objects of v1.0.1")
class MathematicalDeltaIsMeasured(unittest.TestCase):
    """``render()`` writes this block as literals; nothing used to check them.

    Every value is recomputed here from the v1.0.1 commit object, so the
    attestation cannot state a delta the repository does not have.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.delta = mathematical_delta_literal()
        old = frozen._git(REPO_ROOT, "show", f"{frozen.BASE_COMMIT}:data/certified-results.csv")
        cls.old = list(csv.DictReader(io.StringIO(old)))
        with (REPO_ROOT / "data" / "certified-results.csv").open(encoding="utf-8", newline="") as handle:
            cls.new = list(csv.DictReader(handle))

    def changed(self, column: str) -> int:
        self.assertEqual([row["n"] for row in self.old], [row["n"] for row in self.new])
        return sum(1 for old, new in zip(self.old, self.new) if old[column] != new[column])

    def test_the_block_is_the_one_measured_here(self) -> None:
        self.assertEqual(sorted(self.delta), sorted([
            "fixed_configurations_changed", "certified_lower_bounds_changed",
            "certifier_sources_changed", "witness_points_changed",
            "historical_replay_evidence_changed", "upper_witness_decimal_corrections",
            "interval_width_corrections", "provenance_text_corrections"]))

    def test_correction_counts(self) -> None:
        self.assertEqual(self.changed("rigorous_upper_witness"), self.delta["upper_witness_decimal_corrections"])
        self.assertEqual(self.changed("interval_width"), self.delta["interval_width_corrections"])
        self.assertEqual(self.changed("symmetry_or_family"), self.delta["provenance_text_corrections"])

    def test_lower_bounds_unchanged(self) -> None:
        self.assertIs(self.delta["certified_lower_bounds_changed"], False)
        self.assertEqual(self.changed("certified_lower_bound"), 0)

    def test_frozen_files_unchanged(self) -> None:
        """Certifiers (and the witness points they contain), configurations, evidence."""
        for flag in ("fixed_configurations_changed", "certifier_sources_changed",
                     "witness_points_changed", "historical_replay_evidence_changed"):
            self.assertIs(self.delta[flag], False, flag)
        self.assertEqual(set(frozen.FROZEN_ROOTS), {
            "certifiers", "data/configurations",
            "evidence/full-cleanroom-replay", "evidence/saved-replays"})
        release, _ = frozen.release_inventory(REPO_ROOT)
        actual, unexpected = frozen.working_tree_inventory(REPO_ROOT)
        self.assertEqual(unexpected, [])
        self.assertEqual(frozen.compare(release, actual, "working tree"), [])


# --------------------------------------------------------------------------
# What the documentation states about the frozen certifiers stays true
# --------------------------------------------------------------------------

QUARTER_ROOT = re.compile(r"root(?::\s*Box)?\s*=\s*\(\s*ZERO\s*,\s*HALF\s*,\s*ZERO\s*,\s*HALF\s*\)")
REDUCTION_CLAIM = re.compile(r"1/2\]\^2|quarter square|reflection.symmetry", re.I)
SYMMETRY_STATEMENTS = ("assert {(ONE-x,y) for x,y in LIGHT_SET} == LIGHT_SET",
                       "assert {(x,ONE-y) for x,y in LIGHT_SET} == LIGHT_SET")


class FrozenCertifierFactsMatchTheDocumentation(unittest.TestCase):
    """README and docs/ state counts about the certifiers that cannot be fixed in place.

    Each count is recomputed, so the text cannot drift from the corpus, and the
    two docstrings known to be wrong (n17 and n19 componentwise) stay the only
    ones.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {(n, method): (REPO_ROOT / certifier_relpath(n, method)).read_text(encoding="utf-8")
                       for n in EXPECTED_NS for method in METHODS}

    def test_quarter_square_certifiers_are_n18_n20_and_n22_to_n52(self) -> None:
        quarter = {key for key, text in self.sources.items() if QUARTER_ROOT.search(text)}
        expected = {(n, method) for n in [18, 20, *range(22, 53)] for method in METHODS}
        self.assertEqual(quarter, expected)
        self.assertEqual(len(quarter), 66)
        for key in sorted(quarter):
            with self.subTest(certifier=key):
                for statement in SYMMETRY_STATEMENTS:
                    self.assertIn(statement, self.sources[key])

    def test_docstring_reduction_claims_match_the_code(self) -> None:
        mismatched = set()
        for key, text in self.sources.items():
            claims = bool(REDUCTION_CLAIM.search(ast.get_docstring(ast.parse(text)) or ""))
            if claims != bool(QUARTER_ROOT.search(text)):
                mismatched.add(key)
        self.assertEqual(mismatched, {(17, "componentwise"), (19, "componentwise")})

    def test_positive_divisor_assert_is_in_38_componentwise_certifiers(self) -> None:
        using = {n for (n, method), text in self.sources.items() if method == "componentwise"
                 and re.search(r"def divide_by_positive_interval[\s\S]*?\n    assert ", text)}
        self.assertEqual(set(EXPECTED_NS) - using, {7, 8, 10, 11, 12, 21})
        self.assertEqual(len(using), 38)

    def test_printed_upper_witness_is_below_the_exact_value_in_39_certifiers(self) -> None:
        below = 0
        for n in EXPECTED_NS:
            for method in METHODS:
                facts = extract_certifier_facts(REPO_ROOT / certifier_relpath(n, method))
                exact = exact_potential(facts.lights, facts.witness)
                printed = certifier_decimal_string(exact, facts.decimal_precision)
                if attestation_fraction(printed) < exact:
                    below += 1
        self.assertEqual(below, 39)


def attestation_fraction(decimal_text: str):
    from fractions import Fraction
    return Fraction(decimal_text)


if __name__ == "__main__":
    unittest.main()
