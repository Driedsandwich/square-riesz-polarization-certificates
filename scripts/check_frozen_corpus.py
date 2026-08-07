#!/usr/bin/env python3
"""Pin the mathematical corpus to the raw Git objects of the release it was published in.

Three things have been tried as the anchor here, and only the third survives.

``SHA256SUMS`` is regenerated whenever the repository changes, so it cannot tell
a maintenance patch apart from an edit to a certifier.

``data/frozen-corpus-v1.0.1.sha256`` was written once from the release commit,
but it is still a file in the repository: it can be edited in the same change as
the corpus, and when that was measured every check passed.

Naming the commit is necessary but not sufficient either. ``git replace`` lets a
repository serve different bytes under an unchanged object name: with a
commit or blob replacement configured, ``git ls-tree`` and ``git cat-file``
return the substituted content, and a checker that follows them reports
``git_anchor=verified`` on a corpus that has been altered. So every object read
here disables replacement — ``git --no-replace-objects`` plus
``GIT_NO_REPLACE_OBJECTS=1``, with ``GIT_REPLACE_REF_BASE`` refused from the
environment — and every ``cat-file --batch`` response is checked against the
object id, type and size that were asked for. ``refs/replace/`` is enumerated
and reported, and under ``--require-git-anchor`` its mere existence is a
failure.

Bytes are not the whole file either. A frozen file replaced by a symlink to an
identical copy has the same digest, and so does one that has gained the
executable bit. The working tree is therefore inventoried with ``lstat`` and no
symlink following: the four roots must be real directories, every listed path
must be a regular file, and anything else — a symlink, a FIFO, a socket, a
device — is reported rather than silently read through. When the release
objects are available, the Git file mode is compared as well.

    BASE_VERSION = v1.0.1
    BASE_COMMIT  = d92992101ca45a5cd755b8d962652ab7e4329973

Inside a Git repository three derivations must agree: the raw release blobs,
the in-tree baseline, and the working tree. Outside one — a release archive or
an evidence snapshot — there are no objects to read; the baseline check still
runs, and the result is reported as ``git_anchor_unverifiable=1`` rather than
being passed off as a comparison against the release.

Usage:
    python scripts/check_frozen_corpus.py
    python scripts/check_frozen_corpus.py --require-git-anchor
    python scripts/check_frozen_corpus.py \\
        --expect-base-version v1.0.1 \\
        --expect-base-commit d92992101ca45a5cd755b8d962652ab7e4329973 \\
        --require-git-anchor

Exit codes: 0 agreement, 1 a difference was found, 2 the check could not be
performed as demanded (unusable baseline, a required anchor that could not be
read, or a replacement configured while the anchor was required).

Dependencies: Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data" / "frozen-corpus-v1.0.1.sha256"

#: The published release this corpus belongs to. Fixed in code, not read from
#: the file being checked: a header that vouches for itself vouches for nothing.
BASE_VERSION = "v1.0.1"
BASE_COMMIT = "d92992101ca45a5cd755b8d962652ab7e4329973"

#: The directories the baseline covers in full. A file that appears under one of
#: these without being listed is an addition to the corpus, not a maintenance
#: change, so it is reported rather than ignored.
FROZEN_ROOTS: tuple[str, ...] = (
    "certifiers",
    "data/configurations",
    "evidence/full-cleanroom-replay",
    "evidence/saved-replays",
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
ENTRY = re.compile(r"^([0-9a-f]{64})  (\S.*)$")
HEADER_FIELD = re.compile(r"^# ([a-z-]+): (.*)$")

#: Headers the baseline must declare exactly once each.
REQUIRED_HEADERS: tuple[str, ...] = ("base-version", "base-commit", "file-count")

#: Git modes a frozen blob may have. `120000` (symlink) and `160000` (submodule)
#: are deliberately absent.
REGULAR_MODES = frozenset({"100644", "100755"})
EXECUTABLE_MODE = "100755"
NON_EXECUTABLE_MODE = "100644"


class Entry(NamedTuple):
    """One frozen file: its content digest, and its Git file mode when known."""

    digest: str
    mode: str | None


class BaselineError(Exception):
    """The baseline file itself is unusable."""


class GitAnchorError(Exception):
    """The release objects could not be read, or must not be trusted."""


# --------------------------------------------------------------------------
# the baseline file
# --------------------------------------------------------------------------


def unsafe_path_reason(relative: str) -> str | None:
    """Why this path may not be used, or None when it is safe."""
    if relative != relative.strip():
        return "leading or trailing whitespace"
    if relative.startswith("/") or (len(relative) > 1 and relative[1] == ":"):
        return "not repository-relative"
    if "\\" in relative:
        return "backslash separator"
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "empty or traversing path component"
    if not any(relative.startswith(root + "/") for root in FROZEN_ROOTS):
        return f"outside the frozen roots {list(FROZEN_ROOTS)}"
    return None


def parse_baseline(
    path: Path, *, expect_version: str = BASE_VERSION, expect_commit: str = BASE_COMMIT
) -> tuple[dict[str, Entry], dict[str, str]]:
    """Read the baseline into {path: Entry} plus its declared header fields.

    The baseline lists digests only, so every entry carries ``mode=None``; the
    file mode is anchored against the release objects, not against this file.

    A structured header may appear exactly once. Taking the last occurrence let
    ``# base-version: v9.9.9`` sit above the real line and be silently
    overwritten, which is a difference the reader would never see.
    """
    if not path.is_file():
        raise BaselineError(f"no frozen-corpus baseline at {path}")

    entries: dict[str, Entry] = {}
    header: dict[str, str] = {}
    seen_headers: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        if line.startswith("#"):
            field = HEADER_FIELD.match(line)
            if field:
                name, value = field.group(1), field.group(2).strip()
                if name in REQUIRED_HEADERS:
                    if name in seen_headers:
                        raise BaselineError(
                            f"{path}:{number}: header {name!r} appears twice "
                            f"(also on line {seen_headers[name]}); it must appear exactly once"
                        )
                    seen_headers[name] = number
                    header[name] = value
                else:
                    header.setdefault(name, value)
            continue
        match = ENTRY.match(line)
        if match is None:
            raise BaselineError(f"{path}:{number}: not a `<sha256>  <path>` entry: {line!r}")
        digest, relative = match.group(1), match.group(2)
        if not HEX64.fullmatch(digest):
            raise BaselineError(f"{path}:{number}: digest is not 64 lowercase hex characters")
        problem = unsafe_path_reason(relative)
        if problem is not None:
            raise BaselineError(f"{path}:{number}: unsafe path {relative!r}: {problem}")
        if relative in entries:
            raise BaselineError(f"{path}:{number}: duplicate path {relative!r}")
        entries[relative] = Entry(digest, None)

    if not entries:
        raise BaselineError(f"{path}: no entries")

    missing = [name for name in REQUIRED_HEADERS if name not in header]
    if missing:
        raise BaselineError(f"{path}: header does not declare {missing}")

    if header["base-version"] != expect_version:
        raise BaselineError(
            f"{path}: header base-version is {header['base-version']!r}, expected {expect_version!r}"
        )
    if not HEX40.fullmatch(header["base-commit"]):
        raise BaselineError(
            f"{path}: header base-commit is {header['base-commit']!r}, "
            f"which is not 40 lowercase hex characters"
        )
    if header["base-commit"] != expect_commit:
        raise BaselineError(
            f"{path}: header base-commit is {header['base-commit']!r}, expected {expect_commit!r}"
        )
    declared = header["file-count"]
    if not declared.isdigit():
        raise BaselineError(f"{path}: header file-count is {declared!r}, which is not a decimal integer")
    if int(declared) != len(entries):
        raise BaselineError(f"{path}: header declares file-count {declared}, found {len(entries)} entries")
    return entries, header


# --------------------------------------------------------------------------
# the release objects, read raw
# --------------------------------------------------------------------------


def git_environment() -> dict[str, str]:
    """An environment in which Git cannot be told to substitute objects.

    ``GIT_NO_REPLACE_OBJECTS`` is forced on and ``GIT_REPLACE_REF_BASE`` is
    dropped, so neither the caller's environment nor a repository-local
    configuration can point the reads at a different set of refs.
    """
    environment = dict(os.environ)
    environment.pop("GIT_REPLACE_REF_BASE", None)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git(root: Path, *arguments: str) -> str:
    """Run one Git command with replacement disabled, or raise."""
    try:
        completed = subprocess.run(
            ["git", "--no-replace-objects", *arguments],
            cwd=root, capture_output=True, timeout=300, check=False, env=git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GitAnchorError(f"git {' '.join(arguments)}: {error}") from error
    if completed.returncode != 0:
        message = completed.stderr.decode(errors="replace").strip().splitlines()
        raise GitAnchorError(
            f"git {' '.join(arguments)} exited {completed.returncode}"
            + (f": {message[-1]}" if message else "")
        )
    return completed.stdout.decode()


def git_repository(root: Path) -> bool:
    return (root / ".git").exists()


def replacement_refs(root: Path) -> list[str]:
    """Every ``refs/replace/`` ref in this repository.

    Reads are already immune to these, but their presence means someone
    configured object substitution, and that is worth saying out loud rather
    than passing over in silence.
    """
    listing = _git(root, "for-each-ref", "--format=%(refname)", "refs/replace/")
    return [line.strip() for line in listing.splitlines() if line.strip()]


def release_inventory(
    root: Path, commit: str = BASE_COMMIT, version: str = BASE_VERSION
) -> tuple[dict[str, Entry], dict[str, str]]:
    """Mode and SHA-256 of every frozen file as stored in ``commit``.

    Read through ``git cat-file --batch`` rather than ``git archive`` so that no
    ``.gitattributes`` filter can stand between the stored object and the digest.
    """
    notes: dict[str, str] = {}

    kind = _git(root, "cat-file", "-t", commit).strip()
    if kind != "commit":
        raise GitAnchorError(f"{commit} is a {kind!r}, not a commit")
    notes["base_commit"] = commit

    # The tag is checked when present. A shallow or tagless clone is a weaker
    # anchor, not a broken one, and says which it is.
    try:
        tagged = _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{version}^{{commit}}").strip()
    except GitAnchorError:
        tagged = ""
    if tagged:
        if tagged != commit:
            raise GitAnchorError(f"tag {version} points at {tagged}, not at {commit}")
        notes["tag"] = f"{version} -> {commit}"
    else:
        notes["tag"] = f"{version} not present in this clone; commit checked directly"

    listing = _git(root, "ls-tree", "-r", "-z", commit, "--", *FROZEN_ROOTS)
    blobs: list[tuple[str, str, str]] = []  # (path, mode, object id)
    for record in listing.split("\0"):
        if not record:
            continue
        meta, relative = record.split("\t", 1)
        mode, object_kind, object_id = meta.split()
        if object_kind != "blob":
            raise GitAnchorError(f"{relative}: {object_kind} where a blob was expected")
        if mode not in REGULAR_MODES:
            raise GitAnchorError(
                f"{relative}: mode {mode} is not a regular file "
                f"(120000 is a symlink, 160000 a submodule)"
            )
        if not HEX40.fullmatch(object_id):
            raise GitAnchorError(f"{relative}: malformed object id {object_id!r}")
        problem = unsafe_path_reason(relative)
        if problem is not None:
            raise GitAnchorError(f"{relative}: unsafe path in the release tree: {problem}")
        blobs.append((relative, mode, object_id))

    if not blobs:
        raise GitAnchorError(f"{commit} has no files under {list(FROZEN_ROOTS)}")
    paths = [relative for relative, _, _ in blobs]
    if len(set(paths)) != len(paths):
        raise GitAnchorError("the release tree lists a path twice")

    digests = _batch_digests(root, [object_id for _, _, object_id in blobs])
    inventory = {
        relative: Entry(digest, mode)
        for (relative, mode, _), digest in zip(blobs, digests)
    }
    notes["blob_count"] = str(len(inventory))
    executable = sum(1 for entry in inventory.values() if entry.mode == EXECUTABLE_MODE)
    notes["modes"] = f"{len(inventory) - executable} x {NON_EXECUTABLE_MODE}, {executable} x {EXECUTABLE_MODE}"
    return inventory, notes


def _batch_digests(root: Path, object_ids: list[str]) -> list[str]:
    """SHA-256 of each object, read in one ``git cat-file --batch`` pass.

    Every response is matched against the request: same object id, type
    ``blob``, the declared size actually present, and the newline the batch
    protocol puts after each payload. A reordered, missing, extra or truncated
    response is an error, not something to resynchronise past.
    """
    try:
        process = subprocess.Popen(
            ["git", "--no-replace-objects", "cat-file", "--batch"],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git_environment(),
        )
    except OSError as error:
        raise GitAnchorError(f"git cat-file --batch: {error}") from error
    stdout, stderr = process.communicate(("\n".join(object_ids) + "\n").encode(), timeout=600)
    if process.returncode != 0:
        raise GitAnchorError(
            f"git cat-file --batch exited {process.returncode}: {stderr.decode(errors='replace')[:200]}"
        )

    digests: list[str] = []
    offset = 0
    for position, object_id in enumerate(object_ids):
        end = stdout.find(b"\n", offset)
        if end == -1:
            raise GitAnchorError(f"git cat-file --batch: output ended before the response for {object_id}")
        header = stdout[offset:end].decode(errors="replace")
        parts = header.split()
        if len(parts) == 2 and parts[1] in ("missing", "ambiguous"):
            raise GitAnchorError(f"git cat-file --batch: object {object_id} is {parts[1]}")
        if len(parts) != 3:
            raise GitAnchorError(f"git cat-file --batch: unexpected response header {header!r}")
        returned_id, returned_type, returned_size = parts
        if returned_id != object_id:
            raise GitAnchorError(
                f"git cat-file --batch: response {position} is for {returned_id}, "
                f"but {object_id} was requested"
            )
        if returned_type != "blob":
            raise GitAnchorError(f"git cat-file --batch: {object_id} came back as a {returned_type}")
        if not returned_size.isdigit():
            raise GitAnchorError(f"git cat-file --batch: {object_id} declared size {returned_size!r}")
        size = int(returned_size)
        start = end + 1
        payload = stdout[start:start + size]
        if len(payload) != size:
            raise GitAnchorError(
                f"git cat-file --batch: {object_id} declared {size} bytes but {len(payload)} were available"
            )
        terminator = stdout[start + size:start + size + 1]
        if terminator != b"\n":
            raise GitAnchorError(f"git cat-file --batch: {object_id} is not followed by the record separator")
        digests.append(hashlib.sha256(payload).hexdigest())
        offset = start + size + 1

    if offset != len(stdout):
        raise GitAnchorError(
            f"git cat-file --batch: {len(stdout) - offset} unexpected trailing bytes after "
            f"{len(object_ids)} responses"
        )
    return digests


# --------------------------------------------------------------------------
# the working tree, without following anything
# --------------------------------------------------------------------------


def _kind_of(mode: int) -> str:
    for predicate, name in (
        (stat.S_ISLNK, "symbolic link"),
        (stat.S_ISDIR, "directory"),
        (stat.S_ISFIFO, "FIFO"),
        (stat.S_ISSOCK, "socket"),
        (stat.S_ISBLK, "block device"),
        (stat.S_ISCHR, "character device"),
    ):
        if predicate(mode):
            return name
    return "special file"


def modes_are_meaningful() -> bool:
    """POSIX permission bits carry the executable flag; on Windows they do not."""
    return os.name == "posix"


def working_tree_inventory(root: Path) -> tuple[dict[str, Entry], list[str]]:
    """Every regular file under the frozen roots, found without following symlinks.

    ``Path.is_file()`` follows symlinks, so a frozen file replaced by a link to
    an identical copy read as present and unchanged. Every entry here is
    classified from ``lstat`` before anything is opened, and anything that is
    not a regular file is reported by name.
    """
    found: dict[str, Entry] = {}
    problems: list[str] = []
    check_modes = modes_are_meaningful()

    for name in FROZEN_ROOTS:
        base = root / name
        try:
            base_stat = base.lstat()
        except FileNotFoundError:
            problems.append(f"frozen root is missing: {name}")
            continue
        if stat.S_ISLNK(base_stat.st_mode):
            problems.append(f"frozen root {name} is a symbolic link, not a directory")
            continue
        if not stat.S_ISDIR(base_stat.st_mode):
            problems.append(f"frozen root {name} is a {_kind_of(base_stat.st_mode)}, not a directory")
            continue

        stack = [base]
        while stack:
            directory = stack.pop()
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as error:
                problems.append(f"{directory.relative_to(root).as_posix()}: cannot be listed: {error}")
                continue
            for item in entries:
                path = Path(item.path)
                relative = path.relative_to(root).as_posix()
                info = item.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    problems.append(
                        f"{relative}: symbolic link -> {os.readlink(path)!r}; a frozen path must be a "
                        f"regular file, and a link to an identical copy has an identical digest"
                    )
                elif stat.S_ISDIR(info.st_mode):
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    mode = None
                    if check_modes:
                        mode = EXECUTABLE_MODE if info.st_mode & 0o111 else NON_EXECUTABLE_MODE
                    found[relative] = Entry(sha256_file(path), mode)
                else:
                    problems.append(f"{relative}: {_kind_of(info.st_mode)}, not a regular file")
    return found, problems


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------


def compare(expected: dict[str, Entry], actual: dict[str, Entry], label: str) -> list[str]:
    """Differences between two inventories, with moves called out as moves.

    Modes are compared only where both sides know one; the baseline lists
    digests alone, and on a platform without POSIX permission bits the working
    tree has no mode to offer.
    """
    problems: list[str] = []
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    shared = set(expected) & set(actual)

    by_digest: dict[str, list[str]] = {}
    for path in extra:
        by_digest.setdefault(actual[path].digest, []).append(path)
    moved: list[tuple[str, str]] = []
    for path in list(missing):
        candidates = by_digest.get(expected[path].digest)
        if candidates:
            destination = candidates.pop(0)
            moved.append((path, destination))
            missing.remove(path)
            extra.remove(destination)

    for source, destination in moved:
        problems.append(f"{label}: moved: {source} -> {destination}")
    for path in missing:
        problems.append(f"{label}: missing: {path}")
    for path in extra:
        problems.append(f"{label}: unlisted: {path}")
    for path in sorted(shared):
        left, right = expected[path], actual[path]
        if left.digest != right.digest:
            problems.append(
                f"{label}: changed: {path}\n"
                f"    expected {left.digest}\n"
                f"    actual   {right.digest}"
            )
        elif left.mode is not None and right.mode is not None and left.mode != right.mode:
            problems.append(
                f"{label}: mode changed: {path}: expected {left.mode}, found {right.mode} "
                f"(same bytes, different file mode)"
            )
    return problems


def check(
    root: Path = ROOT,
    baseline_path: Path = BASELINE,
    *,
    expect_version: str = BASE_VERSION,
    expect_commit: str = BASE_COMMIT,
    require_git_anchor: bool = False,
) -> tuple[list[str], dict[str, object]]:
    entries, header = parse_baseline(
        baseline_path, expect_version=expect_version, expect_commit=expect_commit
    )
    problems: list[str] = []
    counts: dict[str, object] = {
        "baseline_entries": len(entries),
        "base_version": header["base-version"],
        "base_commit": header["base-commit"],
    }

    tree, tree_problems = working_tree_inventory(root)
    counts["worktree_files"] = len(tree)
    problems += tree_problems

    if not modes_are_meaningful():
        counts["mode_anchor_unverifiable"] = 1

    if git_repository(root):
        try:
            replacements = replacement_refs(root)
            if replacements:
                counts["replace_refs"] = len(replacements)
                if require_git_anchor:
                    raise GitAnchorError(
                        f"object replacement is configured in this repository "
                        f"({', '.join(replacements)}). Reads here disable it, but its presence means "
                        f"someone arranged for these objects to be served as something else, so an "
                        f"anchored run refuses to continue."
                    )
                problems.append(
                    f"refs/replace/ exists ({', '.join(replacements)}); object reads ignore it, "
                    f"but its presence is reported rather than passed over"
                )
            release, notes = release_inventory(root, expect_commit, expect_version)
        except GitAnchorError:
            counts["git_anchor"] = "failed"
            # Never quietly become a baseline-only check because git misbehaved.
            raise
        counts["git_anchor"] = "verified"
        counts["release_blobs"] = len(release)
        counts["release_tag"] = notes["tag"]
        counts["release_modes"] = notes["modes"]
        problems += compare(release, entries, "release commit vs baseline")
        problems += compare(release, tree, "release commit vs working tree")
        if not problems:
            counts["agreeing_files"] = len(release)
    else:
        if require_git_anchor:
            raise GitAnchorError(
                f"--require-git-anchor was given but {root} has no .git, so the release objects "
                f"cannot be read. A snapshot can only be checked against the baseline it carries."
            )
        counts["git_anchor"] = "unverifiable"
        counts["git_anchor_unverifiable"] = 1
        # Without the release tree there is no mode to compare against, but the
        # file-type requirement above still holds.
        counts["mode_anchor_unverifiable"] = 1
        problems += compare(entries, tree, "baseline vs working tree")
        if not problems:
            counts["agreeing_files"] = len(entries)
    return problems, counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expect-base-version", default=BASE_VERSION)
    parser.add_argument("--expect-base-commit", default=BASE_COMMIT)
    parser.add_argument(
        "--require-git-anchor",
        action="store_true",
        help="fail unless the raw release objects were read and compared",
    )
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args()

    if not HEX40.fullmatch(arguments.expect_base_commit):
        print(f"--expect-base-commit is not a full commit id: {arguments.expect_base_commit!r}", file=sys.stderr)
        return 2

    try:
        problems, counts = check(
            arguments.root,
            arguments.baseline,
            expect_version=arguments.expect_base_version,
            expect_commit=arguments.expect_base_commit,
            require_git_anchor=arguments.require_git_anchor,
        )
    except BaselineError as error:
        print(f"frozen corpus baseline is unusable: {error}", file=sys.stderr)
        return 2
    except GitAnchorError as error:
        print(f"frozen corpus git anchor unavailable: {error}", file=sys.stderr)
        return 2

    if problems:
        print(f"frozen corpus: {len(problems)} problems", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nThe mathematical corpus is fixed by the raw objects of "
            f"{counts['base_version']} ({counts['base_commit']}). Updating the baseline to match an "
            "edited tree does not change them, and neither does configuring object replacement. If "
            "the corpus must change, that is a research release, not a maintenance patch.",
            file=sys.stderr,
        )
        return 1

    if not arguments.quiet:
        print("frozen corpus: " + " ".join(f"{key}={value}" for key, value in counts.items()))
        if counts.get("git_anchor") == "verified":
            print(
                f"  {counts['agreeing_files']} files agree across the raw {counts['base_version']} "
                f"objects, the baseline and the working tree, in content and file mode"
            )
        else:
            print(
                "  baseline-only: no .git here, so this was NOT checked against the release objects"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
