#!/usr/bin/env python3
"""Replay one certified configuration under the strict success contract.

The previous version only inspected the child's exit code, so a certifier that
printed NOT_CERTIFIED and still exited 0 was reported as a pass. Success is now
decided by ``verifier_runner.classify``: exit code 0, no timeout, and exactly
one ``status: CERTIFIED`` line.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from verifier_runner import guard_optimized_mode, run_certifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--method", choices=["spectral", "componentwise", "both"], default="both")
    parser.add_argument("--timeout", type=int, default=1800)
    arguments = parser.parse_args()

    guard_optimized_mode()

    methods = ["spectral", "componentwise"] if arguments.method == "both" else [arguments.method]
    failures: list[str] = []

    for method in methods:
        script = ROOT / "certifiers" / f"n{arguments.n:02d}" / f"{method}.py"
        if not script.is_file():
            print(f"No certified verifier: {script}", file=sys.stderr)
            return 2

        print(f"== n={arguments.n} {method} ==", flush=True)
        outcome = run_certifier(arguments.n, method, script, arguments.timeout, ROOT)
        print(outcome.stdout, end="", flush=True)
        if outcome.stderr:
            print(outcome.stderr, end="", file=sys.stderr, flush=True)

        if not outcome.certified:
            failures.append(f"n={arguments.n} {method}: {outcome.failure_reason}")

    if failures:
        for failure in failures:
            print(f"FAILED {failure}", file=sys.stderr)
        print(f"certified={len(methods) - len(failures)}/{len(methods)}", file=sys.stderr)
        return 1

    print(f"certified={len(methods)}/{len(methods)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
