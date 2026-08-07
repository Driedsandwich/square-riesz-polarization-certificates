#!/usr/bin/env python3
"""One success contract shared by the replay scripts and the evidence checks.

A certifier run counts as a success only when all of the following hold:

1. the child process exited with code 0;
2. it did not time out;
3. its stdout declares exactly one status in the strict line format
   ``status: <TOKEN>``;
4. that token is ``CERTIFIED``;
5. stderr declares no status at all;
6. neither stream contains a structured failure token.

Searching stdout for the substring ``CERTIFIED`` is not enough: it also matches
``NOT_CERTIFIED``, and it accepts output that declares a status twice or not at
all. Ignoring stderr is not enough either: a process can print
``status: CERTIFIED`` on stdout, report a failure on stderr and still exit 0.

The forbidden tokens are structured, not ordinary English words, and are
matched on word boundaries. All 88 certifiers were measured before adopting
them: none of their stdout contains any forbidden token, and all 88 of their
stderr files are empty, so this contract does not reclassify any existing run.

A status line is still only a claim. Conditions 1-6 are all satisfied by a
stdout file whose entire content is ``status: CERTIFIED``, so a successful run
is additionally required to report the proof it performed:
``certificate_lib.validate_proof_output`` reads the target, the split, leaf and
depth counts, the minimum leaf bound and the upper witness value out of the
same stdout and ties them back to the certifier source. That check is defined
once and shared by every path that judges certifier output, so no script can
drift into a looser rule of its own.

Every certifier ends in ``assert`` statements that re-check its own result, so
running one under ``python -O`` would silently drop the final checks. The
runner therefore refuses to start when optimisation is enabled, and removes
``PYTHONOPTIMIZE`` from the child environment.

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

sys.dont_write_bytecode = True

from certificate_lib import (  # noqa: E402
    CertifierSourceError,
    EntryPointError,
    extract_certifier_facts,
    validate_proof_output,
)

SUCCESS_STATUS = "CERTIFIED"
FAILURE_STATUS = "NOT_CERTIFIED"

#: A status declaration must occupy a whole line of its own.
STATUS_LINE = re.compile(r"^[ \t]*status[ \t]*:[ \t]*([A-Za-z_]+)[ \t]*$", re.MULTILINE)

#: Structured tokens that mean "this run failed", wherever they appear.
FORBIDDEN_TOKENS: tuple[str, ...] = ("NOT_CERTIFIED", "FAILED")
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN_TOKENS) + r")\b")

TIMEOUT_RETURN_CODE = 124


class RunOutcome(NamedTuple):
    n: int
    method: str
    repo_relative_script: str
    script_sha256: str
    return_code: int
    timed_out: bool
    status: str | None
    certified: bool
    failure_reason: str | None
    elapsed_seconds: float
    stdout: str
    stderr: str


def guard_optimized_mode() -> None:
    """Refuse to run when assertions are disabled."""
    if sys.flags.optimize:
        raise SystemExit(
            "refusing to run: Python optimisation level is "
            f"{sys.flags.optimize}, which disables the assert statements that "
            "each certifier uses to re-check its own certificate. "
            "Run without -O and without PYTHONOPTIMIZE=1."
        )


def child_environment() -> dict[str, str]:
    """Environment for the child, with optimisation forced off."""
    environment = dict(os.environ)
    environment.pop("PYTHONOPTIMIZE", None)
    environment.setdefault("PYTHONHASHSEED", "0")
    return environment


def declared_statuses(text: str) -> list[str]:
    return STATUS_LINE.findall(text)


def forbidden_tokens_in(text: str) -> list[str]:
    return sorted(set(_FORBIDDEN_RE.findall(text)))


def classify(return_code: int, timed_out: bool, stdout: str, stderr: str) -> tuple[str | None, bool, str | None]:
    """Apply the success contract to one finished run."""
    out_statuses = declared_statuses(stdout)
    err_statuses = declared_statuses(stderr)
    declared = out_statuses[0] if len(out_statuses) == 1 else None

    if timed_out:
        return declared, False, "timed out"
    if return_code != 0:
        return declared, False, f"return code {return_code}"
    if not out_statuses:
        return None, False, "no status line in stdout"
    if len(out_statuses) > 1:
        return None, False, f"{len(out_statuses)} status lines in stdout: {out_statuses}"
    if err_statuses:
        return declared, False, f"stderr declares a status: {err_statuses}"

    status = out_statuses[0]
    if status != SUCCESS_STATUS:
        return status, False, f"status is {status}"

    for stream_name, text in (("stdout", stdout), ("stderr", stderr)):
        tokens = forbidden_tokens_in(text)
        if tokens:
            return status, False, f"{stream_name} declares {SUCCESS_STATUS} but contains {tokens}"
    return status, True, None


def proof_output_problems(script: Path, stdout: str, where: str) -> list[str]:
    """Check a successful run's stdout against the certifier that produced it.

    The source is re-read here rather than passed in, so that every caller —
    the single-configuration replay, the parallel replay and the after-the-fact
    validator — asks the same question of the same bytes.
    """
    try:
        facts = extract_certifier_facts(script, verify_entry_point=True)
    except (CertifierSourceError, EntryPointError) as error:
        return [f"{where}: {error}"]
    return validate_proof_output(stdout, facts, where)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def platform_summary() -> dict[str, str]:
    """Enough of the environment to tell two replays apart."""
    return {
        "python_version": sys.version.split()[0],
        "python_version_full": sys.version.replace("\n", " "),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def run_certifier(n: int, method: str, script: Path, timeout: int, repo_root: Path | None = None) -> RunOutcome:
    """Run one certifier and bind the result to the bytes that produced it.

    The script digest is taken before the run, so a log can be checked against
    the source it claims to have executed without trusting the log.
    """
    digest = sha256_file(script)
    if repo_root is None:
        relative = script.name
    else:
        relative = script.resolve().relative_to(repo_root.resolve()).as_posix()

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, script.name],
            cwd=str(script.parent),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=child_environment(),
        )
        stdout, stderr = completed.stdout, completed.stderr
        return_code, timed_out = completed.returncode, False
    except subprocess.TimeoutExpired as expired:
        stdout = _as_text(expired.stdout)
        stderr = _as_text(expired.stderr)
        return_code, timed_out = TIMEOUT_RETURN_CODE, True
    elapsed = time.perf_counter() - started

    status, certified, failure_reason = classify(return_code, timed_out, stdout, stderr)
    if certified:
        problems = proof_output_problems(script, stdout, f"n{n:02d} {method}")
        if problems:
            certified = False
            failure_reason = "; ".join(problems)
    return RunOutcome(
        n=n,
        method=method,
        repo_relative_script=relative,
        script_sha256=digest,
        return_code=return_code,
        timed_out=timed_out,
        status=status,
        certified=certified,
        failure_reason=failure_reason,
        elapsed_seconds=round(elapsed, 6),
        stdout=stdout,
        stderr=stderr,
    )


def _as_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
