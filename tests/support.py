"""Helpers for the regression and mutation tests.

Every mutation test works on a throwaway copy of the repository, so no test can
modify the certifiers, the configurations or the stored replay evidence.
"""

from __future__ import annotations

import atexit
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def copy_repository(destination: Path) -> Path:
    """Copy the working tree, minus git metadata and stray bytecode."""
    repo = destination / "repo"
    shutil.copytree(
        REPO_ROOT,
        repo,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "venv"),
    )
    return repo


def run_script(repo: Path, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one of the repository scripts inside ``repo``.

    ``-B`` keeps the copy free of bytecode, which ``check_release.py`` treats as
    a packaging defect.
    """
    return subprocess.run(
        [sys.executable, "-B", str(repo / "scripts" / script), *arguments],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=900,
    )


def read_text(path: Path) -> str:
    """Read a file without touching its line endings.

    ``Path.read_text`` translates CRLF to LF and ``write_text`` translates back
    to ``os.linesep``, so a round trip through them silently rewrites the CRLF
    result tables. Everything here goes through bytes instead.
    """
    return path.read_bytes().decode("utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace the first occurrence of ``old``, proving that it was there.

    A silent no-op would make a mutation test pass for the wrong reason: the
    check would be credited with catching a mutation that never happened.
    """
    text = read_text(path)
    if old not in text:
        raise AssertionError(f"{path}: pattern to mutate was not found: {old!r}")
    mutated = text.replace(old, new, 1)
    if mutated == text:
        raise AssertionError(f"{path}: mutation did not change the file")
    write_text(path, mutated)


WITNESS_LITERAL = re.compile(r'(?:UPPER_WITNESS|WITNESS_POINT|WITNESS)\b[^\n]*?Q\("([^"]+)"\)')


def witness_literal(path: Path) -> str:
    """The decimal literal of a certifier's witness point, as written in source."""
    match = WITNESS_LITERAL.search(read_text(path))
    if match is None:
        raise AssertionError(f"{path}: no witness literal found")
    return match.group(1)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_results_json(path: Path, records) -> None:
    """Write the results JSON in its published shape (no trailing newline)."""
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


_SHARED_REPLAY: dict[str, Path] = {}


def shared_quick_replay() -> "tuple[Path, Path]":
    """One real quick replay for the whole test process, created on first use.

    Returns ``(repo, replay_dir)``. Callers must copy the replay directory (and
    the repository, if they intend to modify it) before mutating anything.

    Each mutation test needs a valid replay directory to corrupt, not a
    separately proved one. Producing one per test class made the suite's
    runtime dominated by branch-and-bound while checking nothing extra; the
    demonstration that a real replay passes end to end is a single test, and
    the smoke workflow runs a real replay independently.
    """
    if "replay" not in _SHARED_REPLAY:
        base = Path(tempfile.mkdtemp(prefix="square-riesz-replay-fixture-"))
        atexit.register(shutil.rmtree, base, ignore_errors=True)
        repo = copy_repository(base)
        replay = base / "replay_fixture"
        result = run_script(
            repo, "verify_all.py", "--quick", "--jobs", "2", "--output-dir", str(replay), "--timeout", "600"
        )
        if result.returncode != 0:
            raise AssertionError(f"shared quick replay fixture failed:\n{result.stdout}\n{result.stderr}")
        _SHARED_REPLAY["repo"] = repo
        _SHARED_REPLAY["replay"] = replay
    return _SHARED_REPLAY["repo"], _SHARED_REPLAY["replay"]


#: A complete but trivial certifier, for tests about the replay plumbing rather
#: than about the mathematics.
#:
#: Until Round 4, those tests planted a script that printed ``status: CERTIFIED``
#: and nothing else. That is now rejected — a status line without the proof it
#: summarises is precisely what the proof-output contract exists to catch — so a
#: stand-in has to be a real certifier: the audited entry-point shape, a real
#: branch-and-bound over the unit square, and printed measurements that
#: reproduce from its own source.
#:
#: One light at the centre of the square. The termwise distance bound on the
#: root box is already 2, so the run certifies at once, with no splits, and the
#: whole thing takes milliseconds. This is not a published certificate and does
#: not live under ``certifiers/``; it is written into throwaway copies.
MINIMAL_CERTIFIER = '''#!/usr/bin/env python3
"""Trivial exact lower-bound certificate, used as a test fixture."""

from __future__ import annotations

from decimal import Decimal, getcontext
from fractions import Fraction as Q
from heapq import heappop, heappush
from typing import NamedTuple

ZERO = Q(0)
ONE = Q(1)
TARGET = Q("1.0")

Point = tuple[Q, Q]
Box = tuple[Q, Q, Q, Q]

LIGHTS: list[Point] = [
    (Q("0.5"), Q("0.5")),
]
assert len(LIGHTS) == 1
assert len(set(LIGHTS)) == 1
WITNESS_POINT: Point = (Q("0"), Q("0"))


def max_sq_1d(source: Q, lo: Q, hi: Q) -> Q:
    return max((lo - source) ** 2, (hi - source) ** 2)


def potential_at(point: Point) -> Q:
    x, y = point
    total = ZERO
    for sx, sy in LIGHTS:
        r2 = (x - sx) ** 2 + (y - sy) ** 2
        if r2 == 0:
            raise ValueError("Potential is +infinity at a light source")
        total += ONE / r2
    return total


def box_lower_bound(box: Box) -> Q:
    x0, x1, y0, y1 = box
    bound = ZERO
    for sx, sy in LIGHTS:
        bound += ONE / (max_sq_1d(sx, x0, x1) + max_sq_1d(sy, y0, y1))
    return bound


class CertificateResult(NamedTuple):
    certified: bool
    splits: int
    leaf_count: int
    maximum_depth: int
    minimum_leaf_lower_bound: Q | None
    failed_lower_bound: Q | None
    failed_box: Box | None


def certify(target: Q = TARGET, max_splits: int = 1000) -> CertificateResult:
    root: Box = (ZERO, ONE, ZERO, ONE)
    serial = 0
    heap: list[tuple[Q, int, int, Box]] = []
    heappush(heap, (box_lower_bound(root), 0, serial, root))
    serial += 1

    splits = 0
    leaves = 0
    maximum_depth = 0
    minimum_leaf_lower_bound: Q | None = None

    while heap:
        lower_bound, depth, _, box = heappop(heap)
        if lower_bound >= target:
            leaves += 1
            maximum_depth = max(maximum_depth, depth)
            if minimum_leaf_lower_bound is None:
                minimum_leaf_lower_bound = lower_bound
            else:
                minimum_leaf_lower_bound = min(minimum_leaf_lower_bound, lower_bound)
            continue
        if splits >= max_splits:
            return CertificateResult(False, splits, leaves, maximum_depth, minimum_leaf_lower_bound, lower_bound, box)
        x0, x1, y0, y1 = box
        mid = (x0 + x1) / 2
        for child in ((x0, mid, y0, y1), (mid, x1, y0, y1)):
            heappush(heap, (box_lower_bound(child), depth + 1, serial, child))
            serial += 1
        splits += 1

    return CertificateResult(True, splits, leaves, maximum_depth, minimum_leaf_lower_bound, None, None)


def decimal_string(value: Q, precision: int = 60) -> str:
    getcontext().prec = precision
    return str(Decimal(value.numerator) / Decimal(value.denominator))


def main() -> None:
    result = certify()
    witness_upper_bound = potential_at(WITNESS_POINT)

    print("status:", "CERTIFIED" if result.certified else "NOT_CERTIFIED")
    print("target_decimal:", decimal_string(TARGET))
    print("splits:", result.splits)
    print("leaf_count:", result.leaf_count)
    print("maximum_depth:", result.maximum_depth)
    if result.minimum_leaf_lower_bound is not None:
        print("minimum_leaf_lower_bound_decimal:", decimal_string(result.minimum_leaf_lower_bound))
    print("witness_value_upper_bound_decimal:", decimal_string(witness_upper_bound))

    assert result.certified
    assert result.minimum_leaf_lower_bound is not None
    assert result.minimum_leaf_lower_bound >= TARGET
    assert witness_upper_bound >= TARGET


if __name__ == "__main__":
    main()
'''


_SHARED_CLONE: dict[str, Path] = {}

#: A git invocation that cannot pick up the developer's identity or config.
GIT_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin:/usr/local/bin",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git_available() -> bool:
    return shutil.which("git") is not None


def shared_release_clone() -> Path:
    """A real clone of this repository, with the uncommitted files copied in.

    The frozen-corpus check reads the ``v1.0.1`` commit and tag objects, so a
    plain ``copytree`` of the working tree cannot exercise it — there are no
    objects in one. A clone has them. It is made once per process (about a
    tenth of a second, 2.5 MB) and copied per test.
    """
    if "clone" not in _SHARED_CLONE:
        base = Path(tempfile.mkdtemp(prefix="square-riesz-clone-fixture-"))
        atexit.register(shutil.rmtree, base, ignore_errors=True)
        clone = base / "clone"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(clone)],
            env=GIT_ENVIRONMENT, capture_output=True, check=True, timeout=300,
        )
        listing = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=True, timeout=300,
        ).stdout
        for line in listing.splitlines():
            relative = line[3:]
            source = REPO_ROOT / relative
            if source.is_file():
                (clone / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, clone / relative)
        _SHARED_CLONE["clone"] = clone
    return _SHARED_CLONE["clone"]


def copy_release_clone(destination: Path) -> Path:
    """A private copy of the shared clone, safe to mutate."""
    target = destination / "clone"
    shutil.copytree(shared_release_clone(), target)
    return target


def write_fake_certifier(repo: Path, n: int, method: str, body: str) -> Path:
    directory = repo / "certifiers" / f"n{n:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"{method}.py"
    script.write_text(body, encoding="utf-8")
    return script
