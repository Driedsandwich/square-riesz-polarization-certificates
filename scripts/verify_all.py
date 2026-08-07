#!/usr/bin/env python3
"""Replay many certifiers under the strict success contract.

Two things this deliberately does *not* accept:

* a job list that merely has the right size. ``--all`` requires the discovered
  configurations to equal the expected set exactly, checked before anything
  runs. Eighty-eight verifiers built from a directory set where n=52 was
  replaced by n=53 is still eighty-eight verifiers, and it proves nothing about
  the corpus this repository publishes;
* an output directory that already has files in it. Stale logs from an earlier
  run would be indistinguishable from this run's evidence once they are in the
  same artifact.

Each record is bound to the bytes it executed by ``repo_relative_script`` and
``script_sha256``, so ``scripts/validate_replay_output.py`` can check a replay
directory against the sources without trusting the summary.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from certificate_lib import (  # noqa: E402
    EXPECTED_NS,
    METHODS,
    QUICK_NS,
    canonical_log_name,
    csv_text,
    log_stem,
)
from verifier_runner import guard_optimized_mode, platform_summary, run_certifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

SUMMARY_FIELDS: tuple[str, ...] = (
    "n",
    "method",
    "repo_relative_script",
    "script_sha256",
    "return_code",
    "timed_out",
    "status",
    "certified",
    "failure_reason",
    "elapsed_seconds",
    "stdout_log",
    "stderr_log",
)


def discovered_configurations() -> list[int]:
    return sorted(int(path.name[1:]) for path in (ROOT / "certifiers").glob("n*") if path.is_dir())


def build_jobs(quick: bool) -> list[tuple[int, str, Path]]:
    """Fix the exact job list, or refuse to start."""
    discovered = discovered_configurations()
    if len(discovered) != len(set(discovered)):
        raise SystemExit(f"duplicate configuration directories: {discovered}")

    if quick:
        expected = list(QUICK_NS)
        missing = sorted(set(expected) - set(discovered))
        if missing:
            raise SystemExit(f"--quick needs configurations {missing}, which are not present")
        selected = expected
    else:
        missing = sorted(set(EXPECTED_NS) - set(discovered))
        unexpected = sorted(set(discovered) - set(EXPECTED_NS))
        if missing or unexpected:
            raise SystemExit(
                "--all requires the exact published configuration set.\n"
                f"  missing:    {missing}\n"
                f"  unexpected: {unexpected}\n"
                f"  expected {len(EXPECTED_NS)} configurations, found {len(discovered)}"
            )
        selected = list(EXPECTED_NS)

    jobs: list[tuple[int, str, Path]] = []
    for n in selected:
        for method in METHODS:
            script = ROOT / "certifiers" / f"n{n:02d}" / f"{method}.py"
            if not script.is_file():
                raise SystemExit(f"missing certifier: {script.relative_to(ROOT).as_posix()}")
            jobs.append((n, method, script))

    keys = [(n, method) for n, method, _ in jobs]
    if len(keys) != len(set(keys)):
        raise SystemExit("duplicate (n, method) pairs in the job list")
    return jobs


def prepare_output_dir(path: Path) -> None:
    """Require a fresh directory so stale logs cannot join this run's evidence."""
    if path.exists():
        if not path.is_dir():
            raise SystemExit(f"--output-dir exists and is not a directory: {path}")
        existing = sorted(entry.name for entry in path.iterdir())
        if existing:
            raise SystemExit(
                f"--output-dir is not empty: {path}\n"
                f"  {len(existing)} existing entries, first few: {existing[:5]}\n"
                "  Point at a new directory so old logs cannot be mistaken for this run."
            )
    else:
        path.mkdir(parents=True)


def source_git_state() -> dict[str, str | bool | None]:
    """Git provenance of the *source tree*, captured before the run starts.

    This must be read before the output directory gets its first file. The
    output directory is untracked, so writing into a repository — which is what
    CI does — makes ``git status`` dirty from that moment on, and a value read
    afterwards would report every clean checkout as dirty.

    A missing ``.git``, a missing ``git`` binary or a failing command all give
    ``None``, which is deliberately not the same as clean.
    """
    if not (ROOT / ".git").exists():
        return {"source_git_commit": None, "source_git_dirty": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return {"source_git_commit": None, "source_git_dirty": None}
    if commit.returncode != 0 or status.returncode != 0:
        return {"source_git_commit": None, "source_git_dirty": None}
    return {"source_git_commit": commit.stdout.strip(), "source_git_dirty": bool(status.stdout.strip())}


def summary_row(outcome, stdout_log: str, stderr_log: str) -> dict[str, object]:
    row = {field: getattr(outcome, field) for field in SUMMARY_FIELDS if hasattr(outcome, field)}
    row["stdout_log"] = stdout_log
    row["stderr_log"] = stderr_log
    return {field: row[field] for field in SUMMARY_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--quick", action="store_true")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--output-dir", type=Path)
    arguments = parser.parse_args()

    guard_optimized_mode()

    # Before the output directory exists and before any certifier runs: the
    # first file written into an in-repository output directory would otherwise
    # make this read report the source tree as dirty.
    source_git = source_git_state()

    jobs = build_jobs(arguments.quick)
    expected_keys = sorted((n, method) for n, method, _ in jobs)
    if arguments.all and len(jobs) != 2 * len(EXPECTED_NS):
        raise SystemExit(f"--all expects {2 * len(EXPECTED_NS)} certifiers, found {len(jobs)}")

    if arguments.output_dir:
        prepare_output_dir(arguments.output_dir)

    outcomes = []
    logs: dict[tuple[int, str], tuple[str, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, arguments.jobs)) as executor:
        futures = [
            executor.submit(run_certifier, n, method, script, arguments.timeout, ROOT)
            for n, method, script in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            print(
                f"n={outcome.n} {outcome.method} rc={outcome.return_code} "
                f"status={outcome.status} certified={outcome.certified} "
                f"elapsed={outcome.elapsed_seconds:.2f}",
                flush=True,
            )
            if not outcome.certified:
                print(f"  reason: {outcome.failure_reason}", flush=True)
                print(outcome.stdout)
                print(outcome.stderr, file=sys.stderr)

            stdout_name = canonical_log_name(outcome.n, outcome.method, "stdout")
            stderr_name = canonical_log_name(outcome.n, outcome.method, "stderr")
            logs[(outcome.n, outcome.method)] = (stdout_name, stderr_name)
            if arguments.output_dir:
                (arguments.output_dir / stdout_name).write_text(outcome.stdout, encoding="utf-8")
                (arguments.output_dir / stderr_name).write_text(outcome.stderr, encoding="utf-8")
                (arguments.output_dir / f"{log_stem(outcome.n, outcome.method)}.json").write_text(
                    json.dumps(summary_row(outcome, stdout_name, stderr_name), indent=2),
                    encoding="utf-8",
                )

    outcomes.sort(key=lambda outcome: (outcome.n, outcome.method))
    rows = [summary_row(outcome, *logs[(outcome.n, outcome.method)]) for outcome in outcomes]
    certified_count = sum(1 for outcome in outcomes if outcome.certified)
    failed = [outcome for outcome in outcomes if not outcome.certified]

    if arguments.output_dir:
        # Rows are pre-rendered with the shared csv_text() so that a checker
        # comparing a CSV cell with a JSON value never has to guess how a bool
        # or a None was spelled.
        with (arguments.output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(SUMMARY_FIELDS))
            writer.writeheader()
            writer.writerows([{field: csv_text(row[field]) for field in SUMMARY_FIELDS} for row in rows])
        summary = {
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "selection": "all" if arguments.all else "quick",
            "expected_configurations": sorted({n for n, _ in expected_keys}),
            "expected_methods": list(METHODS),
            "expected_keys": [[n, method] for n, method in expected_keys],
            "verifier_count": len(rows),
            "certified_count": certified_count,
            "failed_count": len(failed),
            "timed_out_count": sum(1 for outcome in outcomes if outcome.timed_out),
            "worker_count": max(1, arguments.jobs),
            "timeout_seconds": arguments.timeout,
            **platform_summary(),
            **source_git,
            "results": rows,
        }
        (arguments.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"verifier_count={len(rows)} certified_count={certified_count} failed_count={len(failed)}")
    for outcome in failed:
        print(f"FAILED n={outcome.n} {outcome.method}: {outcome.failure_reason}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
