#!/usr/bin/env python3
"""Build the canonical release ZIP and its checksum companion from one commit.

The v1.0.0 and v1.0.1 assets were produced by one-shot workflows that deleted
themselves in the release they published, so neither released tree contains the
command that built it. This script is that command, kept in the tree it
archives.

Six properties are enforced here because a counterexample was measured for each
one, not because they seemed prudent.

**The target commit is part of the output.** ``git archive`` writes the source
commit id into the archive, so two commits with byte-identical trees produce
archives with different digests. The tag ruleset forbids moving a ``v*`` tag, so
``--require-tag`` binds to an exact ``refs/tags/<name>``; a *branch* of the same
name previously satisfied a plain revision lookup.

**The environment is part of the output.** ``git archive --format=zip`` writes
DOS member timestamps in the local timezone, so the same commit built under
``TZ=UTC`` and ``TZ=Pacific/Kiritimati`` produced different digests -- measured,
fourteen hours apart. The subprocess environment is therefore constructed from
an allow-list with ``TZ=UTC`` and ``LC_ALL=C`` fixed, rather than inherited.

**Attributes that are not in the commit change the archive.** An
``export-ignore`` line in ``.git/info/attributes`` silently dropped a file while
``git status`` stayed empty. Attribute sources are neutralised *and* the archive
is compared file-by-file and byte-by-byte against the raw target tree, which
also catches ``export-subst`` and any in-tree ``.gitattributes``.

**A partial delivery is a published artifact.** Moving the ZIP, the sidecar and
the record one at a time left a canonical-named ZIP behind when the second move
failed -- measured. Everything is now built in a staging directory beside the
destination and published by a **single** ``rename`` of that directory, so the
output directory either does not exist or is complete.

**The script that runs is part of the output too.** A build was measured in
which the ``scripts/build_release_assets.py`` blob inside the target commit was
different bytes from the script that actually executed, and the build, the
record and the publication attestation all reported success. Recording two
identifiers of different lengths keeps them from being pasted into each other's
slot; it does not bind them to the same file. The executed script's bytes are
now hashed and required to equal the target blob's bytes before any output is
created, and re-hashed before the record is written.

**After the rename there is no such thing as "nothing published".** Failing the
parent-directory ``fsync`` that follows the rename produced exit 2 and the
message ``nothing published`` while a complete, valid three-file output
directory sat on disk -- measured. That state now has its own exit code and its
own sentence.

Standard library and ``git`` only. No network access, no GitHub write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT = "square-riesz-polarization-certificates"
RECORD_NAME = "build-record.json"
RECORD_SCHEMA = "square-riesz-release-asset-build.v4"
BUILDER_PATH_IN_TREE = "scripts/build_release_assets.py"
MANDATORY_ARCHIVE_CHECK = "verify_manifest.py"
ARCHIVE_CHECKS = ("verify_manifest.py", "check_release.py")
HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
SEMVER = re.compile(r"\A[0-9]+\.[0-9]+\.[0-9]+\Z")
ALLOWED_MODES = {"100644", "100755"}
COMPRESSION_LEVEL = "-9"

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_REFUSED_BEFORE_PUBLISH = EXIT_REFUSED
EXIT_PUBLISHED_DURABILITY_UNCERTAIN = 3

REDACTED_REPOSITORY = "<REPOSITORY>"
REDACTED_OUTPUT_ZIP = "<OUTPUT_ZIP>"

# Everything the subprocess is allowed to inherit. Anything not named here is
# dropped, so a variable that reroutes Git or shifts the clock cannot reach the
# archive by accident.
INHERITED_ENVIRONMENT = ("PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")
FIXED_ENVIRONMENT = {
    "TZ": "UTC",
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}
# Named only so the build record can say what was excluded on purpose.
DROPPED_ENVIRONMENT = (
    "GIT_REPLACE_REF_BASE", "GIT_ATTR_SOURCE", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_CEILING_DIRECTORIES",
    "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_*", "GIT_CONFIG_VALUE_*",
)


class Refused(Exception):
    """A precondition failed. The destination has not been created."""


class PublishedDurabilityUncertain(Exception):
    """The rename succeeded and then a durability step failed.

    The output directory exists and is complete. Nothing may be rebuilt over it
    and nothing may be uploaded from it until its state has been checked by
    hand, because whether the directory entry survives a power loss is unknown.
    """


# --------------------------------------------------------------------------
# Git access
# --------------------------------------------------------------------------

def git_environment() -> dict[str, str]:
    """Build the subprocess environment from an allow-list.

    Constructed rather than filtered: a deny-list has to anticipate every
    variable that matters, and ``TZ`` was the one that got through last time.
    """
    environment = {name: os.environ[name] for name in INHERITED_ENVIRONMENT if name in os.environ}
    environment.update(FIXED_ENVIRONMENT)
    return environment


def git_prefix(repository: Path) -> list[str]:
    return ["git", "--no-replace-objects", "-c", f"core.attributesFile={os.devnull}",
            "-C", str(repository)]


def git(*arguments: str, repository: Path, binary: bool = False):
    completed = subprocess.run([*git_prefix(repository), *arguments],
                               capture_output=True, env=git_environment())
    if completed.returncode != 0:
        raise Refused(f"git {' '.join(arguments)} failed: "
                      + completed.stderr.decode('utf-8', 'replace').strip())
    return completed.stdout if binary else completed.stdout.decode().strip()


def git_status(repository: Path, *arguments: str) -> int:
    return subprocess.run([*git_prefix(repository), *arguments],
                          capture_output=True, env=git_environment()).returncode


def repository_root(start: Path) -> Path:
    return Path(git("rev-parse", "--show-toplevel", repository=start))


# --------------------------------------------------------------------------
# Path safety -- one normaliser for the archive reader and the tree comparison
# --------------------------------------------------------------------------

CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def reject_unsafe_path(value: str, where: str) -> PurePosixPath:
    if not value:
        raise Refused(f"{where}: empty path")
    control = CONTROL_CHARACTERS.search(value)
    if control:
        raise Refused(f"{where}: control character {control.group(0)!r} in path {value!r}")
    if "\\" in value:
        raise Refused(f"{where}: backslash in path {value!r}")
    if value.startswith("/"):
        raise Refused(f"{where}: absolute path {value!r}")
    if re.match(r"\A[A-Za-z]:", value):
        raise Refused(f"{where}: drive-letter path {value!r}")
    if value.startswith("//"):
        raise Refused(f"{where}: UNC path {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise Refused(f"{where}: absolute path {value!r}")
    for part in path.parts:
        if part in ("", ".", ".."):
            raise Refused(f"{where}: unsafe component {part!r} in {value!r}")
    return path


def reject_file_directory_collisions(paths, where: str) -> None:
    """No path may also be a directory prefix of another path."""
    known = set(paths)
    for candidate in paths:
        parts = PurePosixPath(candidate).parts
        for depth in range(1, len(parts)):
            ancestor = PurePosixPath(*parts[:depth]).as_posix()
            if ancestor in known:
                raise Refused(f"{where}: {ancestor!r} is both a file and a parent of {candidate!r}")


# --------------------------------------------------------------------------
# Preconditions
# --------------------------------------------------------------------------

def check_require_tag(repository: Path, version: str, require_tag: str) -> dict:
    expected = f"v{version}"
    if require_tag != expected:
        raise Refused(f"--require-tag must be {expected!r} for version {version}, got {require_tag!r}")
    ref = f"refs/tags/{require_tag}"
    if git_status(repository, "check-ref-format", ref) != 0:
        raise Refused(f"{ref} is not a valid ref name")
    if git_status(repository, "show-ref", "--verify", "--quiet", ref) != 0:
        raise Refused(f"{ref} does not exist. A branch or other revision of the same name "
                      "is not accepted.")
    return {"tag_ref": ref,
            "tag_target": git("rev-parse", "--verify", f"{ref}^{{commit}}", repository=repository)}


def check_local_attributes(repository: Path) -> None:
    info_attributes = repository / ".git" / "info" / "attributes"
    if not info_attributes.is_file():
        return
    meaningful = [line for line in
                  info_attributes.read_text(encoding="utf-8", errors="replace").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    if meaningful:
        raise Refused(".git/info/attributes has content. It is not part of any commit and does "
                      "not show in git status, but export-ignore there silently removes files "
                      "from the archive. Remove it before building:\n  " + "\n  ".join(meaningful[:5]))


def check_target(repository: Path, target: str, version: str, require_tag: str | None) -> dict:
    if not HEX40.match(target):
        raise Refused(f"--target must be a full 40-character lowercase hex commit id, got {target!r}")
    kind = git("cat-file", "-t", target, repository=repository)
    if kind != "commit":
        raise Refused(f"--target {target} is a {kind} object, not a commit")
    if git("for-each-ref", "refs/replace", repository=repository):
        raise Refused("refs/replace/* exists; object replacement can change what an unchanged "
                      "commit id archives. Remove the replace refs first.")
    check_local_attributes(repository)

    # The checkout is what supplies the executing builder, so it has to be the
    # commit being archived. A clean tree at some other commit would let a
    # builder from one revision archive another.
    head = git("rev-parse", "--verify", "HEAD^{commit}", repository=repository)
    if head != target:
        raise Refused(f"HEAD is {head}, not the requested target {target}. The build must run "
                      "from a checkout of the commit it archives, because the executing builder "
                      "is checked against the builder blob in that commit.")

    tag_facts = {"tag_ref": None, "tag_target": None}
    if require_tag is not None:
        tag_facts = check_require_tag(repository, version, require_tag)
        if tag_facts["tag_target"] != target:
            raise Refused(f"--require-tag {require_tag} resolves to {tag_facts['tag_target']}, "
                          f"not the requested target {target}")
    try:
        committed_version = git("show", f"{target}:VERSION", repository=repository).strip()
    except Refused:
        raise Refused(f"commit {target} has no VERSION file")
    if committed_version != version:
        raise Refused(f"--version {version} does not match VERSION at {target}, "
                      f"which is {committed_version!r}")
    status = git("status", "--porcelain=v1", "--untracked-files=all", repository=repository)
    if status:
        raise Refused("the working tree is not clean. Release assets are built from a committed "
                      "target, and a dirty tree means the checkout does not match what is being "
                      "archived:\n" + status)
    return {"head_commit": head, "target_commit": target,
            "target_tree": git("rev-parse", f"{target}^{{tree}}", repository=repository),
            "require_tag": require_tag, **tag_facts, "committed_version": committed_version}


def check_output_location(repository: Path, output_dir: Path) -> None:
    resolved_repository = repository.resolve()
    parent = output_dir.parent.resolve() if output_dir.parent.exists() else None
    if parent is None:
        raise Refused(f"--output-dir parent directory does not exist: {output_dir.parent}")
    candidate = parent / output_dir.name
    if candidate == resolved_repository or resolved_repository in candidate.parents:
        raise Refused(f"--output-dir {output_dir} is inside the repository. Building an archive "
                      "of the tree into the tree is a recursive packaging bug.")
    if output_dir.exists() or output_dir.is_symlink():
        raise Refused(f"--output-dir {output_dir} already exists. The directory is published by a "
                      "single rename, so it must not exist beforehand; that is what makes a "
                      "half-delivered set of assets impossible.")


# --------------------------------------------------------------------------
# Raw target tree
# --------------------------------------------------------------------------

def raw_tree_inventory(repository: Path, target: str) -> dict[str, tuple[str, str]]:
    raw = git("ls-tree", "-r", "-z", "--full-tree", target, repository=repository, binary=True)
    inventory: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, _, path_bytes = record.partition(b"\t")
        path = path_bytes.decode("utf-8")
        mode, kind, oid = meta.decode().split()
        if kind == "commit":
            raise Refused(f"target tree contains a submodule at {path!r}; refusing to archive it")
        if kind != "blob":
            raise Refused(f"target tree contains a {kind} entry at {path!r}")
        if mode not in ALLOWED_MODES:
            raise Refused(f"target tree entry {path!r} has mode {mode}; only 100644 and 100755 "
                          "are allowed (120000 is a symlink)")
        reject_unsafe_path(path, "target tree")
        if path in inventory:
            raise Refused(f"target tree lists {path!r} twice")
        inventory[path] = (mode, oid)
    if not inventory:
        raise Refused(f"target tree of {target} is empty")
    reject_file_directory_collisions(list(inventory), "target tree")
    return inventory


def read_blobs(repository: Path, oids: list[str]) -> dict[str, bytes]:
    if not oids:
        return {}
    process = subprocess.run([*git_prefix(repository), "cat-file", "--batch"],
                             input="\n".join(oids).encode() + b"\n",
                             capture_output=True, env=git_environment())
    if process.returncode != 0:
        raise Refused("git cat-file --batch failed: "
                      + process.stderr.decode("utf-8", "replace").strip())
    stream = process.stdout
    contents: dict[str, bytes] = {}
    offset = 0
    for oid in oids:
        end = stream.find(b"\n", offset)
        if end < 0:
            raise Refused(f"cat-file response truncated before the header for {oid}")
        parts = stream[offset:end].decode().split()
        offset = end + 1
        if len(parts) != 3:
            raise Refused(f"cat-file header for {oid} is malformed")
        got_oid, kind, size_text = parts
        if got_oid != oid:
            raise Refused(f"cat-file answered for {got_oid}, not the requested {oid}")
        if kind != "blob":
            raise Refused(f"cat-file says {oid} is a {kind}, not a blob")
        size = int(size_text)
        payload = stream[offset:offset + size]
        if len(payload) != size:
            raise Refused(f"cat-file payload for {oid} is {len(payload)} bytes, declared {size}")
        offset += size
        if stream[offset:offset + 1] != b"\n":
            raise Refused(f"cat-file record for {oid} is not terminated by a newline")
        offset += 1
        contents[oid] = payload
    if offset != len(stream):
        raise Refused(f"cat-file returned {len(stream) - offset} unexpected trailing bytes")
    return contents


# --------------------------------------------------------------------------
# Builder source binding
# --------------------------------------------------------------------------

def executing_script_digest() -> tuple[Path, str]:
    """SHA-256 of the file this process is running, read from disk each time."""
    script = Path(__file__).resolve()
    try:
        payload = script.read_bytes()
    except OSError as error:
        raise Refused(f"cannot read the executing builder {script.name}: {error}")
    return script, hashlib.sha256(payload).hexdigest()


def bind_builder_to_target(inventory, blobs) -> dict:
    """Require the executing script to be the builder blob in the target commit.

    Measured on an earlier builder: a target commit whose
    ``scripts/build_release_assets.py`` was different bytes from the script that
    ran produced exit 0 for the pre-tag build, the tagged build and the
    publication attestation. The record carried a 40-hex blob id and a 64-hex
    file digest, which cannot be confused for one another but were never
    required to describe the same bytes.
    """
    entry = inventory.get(BUILDER_PATH_IN_TREE)
    if entry is None:
        raise Refused(f"the target commit has no {BUILDER_PATH_IN_TREE}. The builder must be "
                      "version-controlled in the tree it archives; that is the only way the "
                      "released archive contains the command that produced it.")
    mode, oid = entry
    if mode not in ALLOWED_MODES:
        raise Refused(f"{BUILDER_PATH_IN_TREE} has mode {mode} in the target tree")
    payload = blobs.get(oid)
    if payload is None:
        raise Refused(f"the blob {oid} for {BUILDER_PATH_IN_TREE} was not read from the target tree")
    target_digest = hashlib.sha256(payload).hexdigest()
    script, executed_digest = executing_script_digest()
    if target_digest != executed_digest:
        raise Refused(
            f"the executing builder does not match {BUILDER_PATH_IN_TREE} in the target commit. "
            f"target blob {oid} hashes to {target_digest}; the running {script.name} hashes to "
            f"{executed_digest}. A release may only be built by the builder that is inside the "
            "commit being released.")
    return {"builder_script": BUILDER_PATH_IN_TREE,
            "builder_script_blob_oid": oid,
            "builder_script_mode": mode,
            "builder_script_target_sha256": target_digest,
            "builder_script_executed_sha256": executed_digest,
            "builder_script_matches_target": True}


# --------------------------------------------------------------------------
# Archive inspection
# --------------------------------------------------------------------------

def entry_mode(entry: zipfile.ZipInfo) -> int:
    return (entry.external_attr >> 16) & 0xFFFF


def inspect_archive(archive: Path, prefix: str, version: str) -> dict:
    root = prefix.rstrip("/")
    with zipfile.ZipFile(archive) as bundle:
        broken = bundle.testzip()
        if broken is not None:
            raise Refused(f"archive CRC check failed on {broken}")
        entries = bundle.infolist()
        if not entries:
            raise Refused("archive is empty")
        seen: set[str] = set()
        members: dict[str, zipfile.ZipInfo] = {}
        for entry in entries:
            name = entry.filename
            if name in seen:
                raise Refused(f"archive contains duplicate entry {name!r}")
            seen.add(name)
            bare = name[:-1] if name.endswith("/") else name
            path = reject_unsafe_path(bare, "archive")
            if path.parts[0] != root:
                raise Refused(f"archive must have exactly one root {root!r}, found entry {name!r}")
            # Only the file-type bits decide what an entry is. A permission-only
            # mode is normal: zipfile.writestr records 0o600 with no type bits
            # while git archive records 0o100644, so testing S_ISREG on a
            # permission-only mode rejects an ordinary entry.
            mode = entry_mode(entry)
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise Refused(f"archive entry {name!r} is a symlink; refusing")
            if entry.is_dir():
                continue
            if file_type and file_type != stat.S_IFREG:
                raise Refused(f"archive entry {name!r} has non-regular file type {file_type:o}")
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if not relative:
                raise Refused(f"archive entry {name!r} has no path below the root")
            members[relative] = entry
        reject_file_directory_collisions(list(members), "archive")
        if "VERSION" not in members:
            raise Refused(f"archive has no {prefix}VERSION")
        archived_version = bundle.read(members["VERSION"]).decode().strip()
        if archived_version != version:
            raise Refused(f"archive VERSION is {archived_version!r}, expected {version!r}")
        return {"entry_count": len(entries), "file_count": len(members),
                "uncompressed_size": sum(e.file_size for e in entries),
                "archive_comment": bundle.comment.decode("utf-8", "replace").strip(),
                "_members": members}


def compare_archive_to_tree(archive: Path, inventory, blobs, members) -> dict:
    tree_paths = set(inventory)
    missing = sorted(tree_paths - set(members))
    if missing:
        raise Refused(f"{len(missing)} path(s) are in the target tree but not in the archive, "
                      f"e.g. {missing[:5]}. An export-ignore attribute removes files from the "
                      "archive without changing the commit.")
    extra = sorted(set(members) - tree_paths)
    if extra:
        raise Refused(f"{len(extra)} path(s) are in the archive but not in the target tree, "
                      f"e.g. {extra[:5]}")
    executable = 0
    with zipfile.ZipFile(archive) as bundle:
        for relative in sorted(tree_paths):
            mode, oid = inventory[relative]
            entry = members[relative]
            if bundle.read(entry) != blobs[oid]:
                raise Refused(f"archive content for {relative!r} differs from the target tree blob "
                              f"{oid}. An export-subst attribute rewrites file content during "
                              "archiving.")
            archive_mode = entry_mode(entry)
            if archive_mode:
                expected_executable = mode == "100755"
                if expected_executable != bool(archive_mode & 0o111):
                    raise Refused(f"archive mode for {relative!r} is {archive_mode:o}, which "
                                  f"disagrees with the Git mode {mode}")
                permission = archive_mode & 0o7777
                if permission not in (0o644, 0o755):
                    raise Refused(f"archive mode for {relative!r} is {permission:o}; expected "
                                  "644 or 755 to match the Git mode")
            if mode == "100755":
                executable += 1
    return {"compared_paths": len(tree_paths), "executable_paths": executable}


def verify_from_archive(archive: Path, prefix: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="release-asset-verify-") as scratch:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(scratch)
        root = Path(scratch) / prefix.rstrip("/")
        if not root.is_dir():
            raise Refused(f"extracted archive has no {prefix} directory")
        ran: dict[str, dict] = {}
        absent: list[str] = []
        for script in ARCHIVE_CHECKS:
            if not (root / "scripts" / script).is_file():
                if script == MANDATORY_ARCHIVE_CHECK:
                    raise Refused(f"extracted archive has no scripts/{script}")
                absent.append(script)
                continue
            completed = subprocess.run([sys.executable, "-B", f"scripts/{script}"],
                                       cwd=root, capture_output=True, text=True)
            ran[script] = {"exit_code": completed.returncode,
                           "stdout_tail": completed.stdout.strip().splitlines()[-1:]}
            if completed.returncode != 0:
                raise Refused(f"scripts/{script} failed inside the extracted archive "
                              f"(exit {completed.returncode}): {completed.stdout.strip()} "
                              f"{completed.stderr.strip()}")
        return {"ran": ran, "not_present_in_archive": absent}


# --------------------------------------------------------------------------
# Durability helpers
# --------------------------------------------------------------------------

def fsync_file(path: Path) -> None:
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def fsync_directory(path: Path) -> None:
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def safely(description: str, thunk, errors: list):
    """Run a check on the published output. Record a failure; never raise one.

    Measured on an earlier builder: this inspection raised, the exception
    escaped the handler that was classifying the state, and a complete,
    already-published three-file directory was reported as ``nothing
    published``. Whatever the inspection cannot determine is reported as
    unknown, which is a different claim from "absent".
    """
    try:
        return thunk()
    except BaseException as error:  # noqa: BLE001 - recorded, never propagated
        errors.append(f"{description}: {type(error).__name__}")
        return None


def inspect_published_output(output_dir: Path, record: dict) -> dict:
    """Describe what is on disk after the publishing rename. Never raises."""
    errors: list[str] = []
    expected = safely("output_inventory", lambda: list(record["output_inventory"]), errors)
    present = safely("listing", lambda: sorted(p.name for p in output_dir.iterdir()), errors)

    def asset_matches():
        asset = output_dir / record["asset"]["name"]
        return asset.is_file() and digest(asset) == record["asset"]["sha256"]

    def sidecar_matches():
        sidecar = output_dir / record["sidecar"]["name"]
        return (sidecar.is_file()
                and hashlib.sha256(sidecar.read_bytes()).hexdigest() == record["sidecar"]["sha256"])

    def record_matches():
        stored = output_dir / RECORD_NAME
        if not stored.is_file():
            return False
        return json.loads(stored.read_text(encoding="utf-8")) == record

    findings = {
        "output_directory": safely("name", lambda: output_dir.name, errors),
        "expected_files": expected,
        "present_files": present,
        "inventory_matches": None if present is None or expected is None else present == expected,
        "asset_sha256_matches": safely("asset digest", asset_matches, errors),
        "sidecar_sha256_matches": safely("sidecar digest", sidecar_matches, errors),
        "record_parses": safely("record", record_matches, errors),
    }
    checks = (findings["inventory_matches"], findings["asset_sha256_matches"],
              findings["sidecar_sha256_matches"], findings["record_parses"])
    # None means "not determined", which must not collapse into False.
    findings["complete_and_valid"] = None if any(c is None for c in checks) else all(checks)
    findings["inspection_errors"] = errors
    return findings


def directory_identity(path: Path):
    """(st_dev, st_ino) for a directory, or None. Never raises."""
    try:
        status = path.stat()
        return (status.st_dev, status.st_ino)
    except BaseException:  # noqa: BLE001
        return None


def observe_publication(staging: Path, output_dir: Path, staging_identity) -> dict:
    """Look at the filesystem after an interrupted rename. Never raises.

    `os.rename` completes inside the C call, and a signal can be delivered
    before the next Python bytecode runs. Measured: a `KeyboardInterrupt` raised
    at that moment escaped every handler in this file while a complete
    three-file output directory sat on disk. So the question "did the rename
    commit?" has to be answered by looking, not by a flag that may never have
    been assigned.
    """
    errors: list[str] = []
    output_exists = safely("output exists", lambda: output_dir.exists(), errors)
    identity = safely("output identity", lambda: directory_identity(output_dir), errors)
    return {
        "staging_exists": safely("staging exists", lambda: staging.exists(), errors),
        "output_exists": output_exists,
        "output_is_directory": safely("output is a directory", lambda: output_dir.is_dir(), errors),
        "present_files": safely("listing", lambda: sorted(p.name for p in output_dir.iterdir()),
                                errors) if output_exists else None,
        "staging_identity_before_rename": list(staging_identity) if staging_identity else None,
        "output_identity_after": list(identity) if identity else None,
        "output_is_the_renamed_staging": (None if not staging_identity or not identity
                                          else staging_identity == identity),
        "observation_errors": errors,
    }


def describe_interrupted_publication(output_dir: Path, record: dict, state: dict,
                                     cause: BaseException) -> str:
    """The exit-3 sentence for any failure inside the publication transaction.

    Covers the rename call, the line that records it, the durability fsync and
    the return. Never raises, whatever the inspection does.
    """
    try:
        present = state.get("present_files")
        listing = ", ".join(present) if present else "directory listing unavailable"
        same = {True: "and it is the staging directory that was renamed",
                False: "but it is NOT the staging directory that was renamed"}.get(
            state.get("output_is_the_renamed_staging"),
            "and whether it is the renamed staging directory could not be determined")
        detail = json.dumps(state, sort_keys=True, default=str)
    except BaseException:  # noqa: BLE001
        listing, same, detail = "directory listing unavailable", "", "{}"
    try:
        contents = inspect_published_output(output_dir, record)
        verdict = {True: "re-reads as complete and valid",
                   False: "re-reads as INCOMPLETE"}.get(
            contents.get("complete_and_valid"),
            "could NOT be verified because the inspection itself failed")
    except BaseException:  # noqa: BLE001
        verdict = "could NOT be verified because the inspection itself failed"
    try:
        reason = f"{type(cause).__name__}: {cause}"
    except BaseException:  # noqa: BLE001
        reason = "an error whose description could not be rendered"
    return (f"the publication transaction was interrupted by {reason}, and the output directory "
            f"EXISTS ({listing}) {same}; it {verdict}. The rename may have completed before the "
            "interruption was delivered, so this is treated as published. Whether the directory "
            "entry is durable is unknown. Do NOT re-run this command and do NOT upload from this "
            f"directory automatically; check the state by hand first. Details: {detail}")


def report_unexpected_outcome(output_dir: Path, cause: BaseException) -> int:
    """Classify an unexpected failure in `main` by looking at the destination.

    An interruption delivered after `build()` returned -- on the success report,
    or on the return itself -- is outside every handler inside `build()`. It is
    still a question about what is on disk, not about which line was running.
    Never raises.
    """
    try:
        exists = output_dir.exists()
    except BaseException:  # noqa: BLE001 - an unknown is not a denial
        exists = None
    try:
        reason = f"{type(cause).__name__}: {cause}"
    except BaseException:  # noqa: BLE001
        reason = "an error whose description could not be rendered"
    if exists is not False:
        certainty = ("EXISTS" if exists else
                     "may exist -- its existence could not be determined")
        print(f"published-durability-uncertain: interrupted after the publication transaction by "
              f"{reason}. The output directory {certainty}. Do NOT re-run this command and do NOT "
              "upload from this directory automatically; check the state by hand first.",
              file=sys.stderr)
        return EXIT_PUBLISHED_DURABILITY_UNCERTAIN
    print(f"refused: {reason}, nothing published", file=sys.stderr)
    return EXIT_REFUSED_BEFORE_PUBLISH


def describe_published_output(output_dir: Path, record: dict, cause: BaseException) -> str:
    """Build the exit-3 sentence. Never raises, whatever the inspection does."""
    try:
        state = inspect_published_output(output_dir, record)
        verdict = {True: "re-reads as complete and valid",
                   False: "re-reads as INCOMPLETE"}.get(
            state["complete_and_valid"],
            "could NOT be verified because the inspection itself failed")
        listing = ", ".join(state["present_files"]) if state["present_files"] else \
            "directory listing unavailable"
        detail = json.dumps(state, sort_keys=True, default=str)
    except BaseException:  # noqa: BLE001 - the message must exist regardless
        verdict = "could NOT be verified because the inspection itself failed"
        listing = "directory listing unavailable"
        detail = "{}"
    try:
        reason = f"{type(cause).__name__}: {cause}"
    except BaseException:  # noqa: BLE001
        reason = "an error whose description could not be rendered"
    return (f"the rename that publishes the output directory succeeded, so the output EXISTS "
            f"({listing}) and {verdict}. A step after the publication commit point then failed: "
            f"{reason}. Whether the directory entry survives a power loss is unknown. Do NOT "
            "re-run this command and do NOT upload from this directory automatically; check the "
            f"state by hand first. Details: {detail}")


def find_absolute_paths(value, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found += find_absolute_paths(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += find_absolute_paths(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if value == os.devnull or value.startswith("core.attributesFile="):
            return found
        if value.startswith("/") or re.match(r"\A[A-Za-z]:[\\/]", value):
            found.append(f"{path}={value}")
    return found


def redact_argument(element: str, repository: Path, staged_asset: Path) -> str:
    """Replace the two local paths in the archive argv, leaving the rest exact."""
    if element == str(repository):
        return REDACTED_REPOSITORY
    if element == f"--output={staged_asset}":
        return f"--output={REDACTED_OUTPUT_ZIP}"
    return element


def canonical_record_bytes(record: dict) -> bytes:
    """The one spelling of the record. The attestation re-derives this exactly."""
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def build(arguments: argparse.Namespace) -> dict:
    if not SEMVER.match(arguments.version):
        raise Refused(f"--version must look like 1.2.3, got {arguments.version!r}")
    if arguments.expect_asset_sha256 is not None and not HEX64.match(arguments.expect_asset_sha256):
        raise Refused("--expect-asset-sha256 must be 64 lowercase hex characters")
    # A tag cannot be moved once the ruleset is in force, so the digest a tagged
    # build produces has to have been agreed before the tag existed. Without
    # this the final record cannot show that the pre-tag gate was ever used.
    if arguments.require_tag is not None and arguments.expect_asset_sha256 is None:
        raise Refused(
            "--require-tag needs --expect-asset-sha256. The tagged build must reproduce a digest "
            "measured by a tagless build of the same commit; a tagged build with no expected "
            "digest cannot show that the pre-tag gate was used, and the tag cannot be moved "
            "afterwards to match whatever it produced.")

    repository = repository_root(Path(arguments.repository).resolve())
    output_dir = Path(arguments.output_dir)
    target_facts = check_target(repository, arguments.target, arguments.version, arguments.require_tag)
    check_output_location(repository, output_dir)

    name = f"{PROJECT}-v{arguments.version}"
    prefix = f"{name}/"
    asset_name = f"{name}.zip"
    sidecar_name = f"{asset_name}.sha256"
    inventory_names = sorted([asset_name, sidecar_name, RECORD_NAME])

    inventory = raw_tree_inventory(repository, arguments.target)
    blobs = read_blobs(repository, sorted({oid for _, oid in inventory.values()}))
    builder_facts = bind_builder_to_target(inventory, blobs)
    binding_digest_at_start = builder_facts["builder_script_executed_sha256"]

    # The staging directory is a sibling of the destination so the final publish
    # is a rename within one filesystem, which is atomic. A staging directory in
    # the system temp area could land on a different filesystem, where rename
    # degrades to copy-then-delete and the atomicity is lost.
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-",
                                    dir=str(output_dir.parent)))
    published = False
    try:
        staged_asset = staging / asset_name
        staged_sidecar = staging / sidecar_name
        staged_record = staging / RECORD_NAME

        archive_argv = [*git_prefix(repository), "archive", "--format=zip", COMPRESSION_LEVEL,
                        f"--prefix={prefix}", f"--output={staged_asset}", arguments.target]
        completed = subprocess.run(archive_argv, capture_output=True, env=git_environment())
        if completed.returncode != 0:
            raise Refused("git archive failed: "
                          + completed.stderr.decode("utf-8", "replace").strip())

        archive_facts = inspect_archive(staged_asset, prefix, arguments.version)
        members = archive_facts.pop("_members")
        if archive_facts["archive_comment"] != arguments.target:
            raise Refused(f"archive comment is {archive_facts['archive_comment']!r}, expected the "
                          f"target commit {arguments.target!r}")
        comparison = compare_archive_to_tree(staged_asset, inventory, blobs, members)
        manifest_results = verify_from_archive(staged_asset, prefix)

        asset_digest = digest(staged_asset)
        if arguments.expect_asset_sha256 is not None and asset_digest != arguments.expect_asset_sha256:
            raise Refused(
                f"the archive digest {asset_digest} does not match --expect-asset-sha256 "
                f"{arguments.expect_asset_sha256}. The tagged build must reproduce the digest "
                "measured before the tag was created; the tag cannot be moved to match it.")

        sidecar_bytes = f"{asset_digest}  {asset_name}\n".encode()
        staged_sidecar.write_bytes(sidecar_bytes)

        # Re-read the archive from disk after every inspection has touched it.
        # This is a second measurement, not a restatement of the first.
        if digest(staged_asset) != asset_digest:
            raise Refused("the staged archive changed while it was being verified")

        # The script could have been replaced on disk while the archive was
        # being built and checked, so the binding is measured again against the
        # blob it was compared with at the start.
        _, binding_digest_now = executing_script_digest()
        if binding_digest_now != binding_digest_at_start:
            raise Refused(f"the executing builder changed during the build: it hashed to "
                          f"{binding_digest_at_start} at the source-binding check and to "
                          f"{binding_digest_now} now")

        record = {
            "schema": RECORD_SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project": PROJECT,
            "version": arguments.version,
            **target_facts,
            **builder_facts,
            # Derived from the argv that actually ran, with the two local paths
            # replaced, so the published command cannot drift from the executed
            # one by being written out a second time.
            "archive_command": [redact_argument(element, repository, staged_asset)
                                for element in archive_argv],
            "repository": REDACTED_REPOSITORY,
            "output_zip": REDACTED_OUTPUT_ZIP,
            "generation_semantics": (
                f"git archive --format=zip {COMPRESSION_LEVEL} --prefix={prefix} <target>"),
            "environment": {
                "timezone": FIXED_ENVIRONMENT["TZ"],
                "locale": FIXED_ENVIRONMENT["LC_ALL"],
                "inherited": list(INHERITED_ENVIRONMENT),
                "fixed": dict(FIXED_ENVIRONMENT),
                "dropped": list(DROPPED_ENVIRONMENT),
            },
            "git_version": git("version", repository=repository),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "asset": {"name": asset_name, "sha256": asset_digest,
                      "size": staged_asset.stat().st_size, **archive_facts},
            "sidecar": {"name": sidecar_name,
                        "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
                        "size": len(sidecar_bytes)},
            "raw_tree_comparison": {"tree_paths": len(inventory), **comparison},
            "archive_self_verification": manifest_results,
            "expected_asset_sha256": arguments.expect_asset_sha256,
            "output_inventory": inventory_names,
            "determinism_note": (
                "Byte-identical output is asserted for repeated builds of the same commit with "
                "the same git version on the same platform, with the environment fixed as "
                "recorded above -- notably TZ=UTC, because git archive writes DOS member "
                "timestamps in local time and an inherited TZ changed the digest. "
                "Cross-platform and cross-git-version reproducibility is not claimed."),
            "github_writes": 0,
        }
        leaked = find_absolute_paths(record)
        if leaked:
            raise Refused(f"build record would publish local paths: {leaked[:3]}")
        staged_record.write_bytes(canonical_record_bytes(record))

        staged = sorted(p.name for p in staging.iterdir())
        if staged != inventory_names:
            raise Refused(f"the staging directory holds {staged}, not the declared output "
                          f"inventory {inventory_names}")

        for item in (staged_asset, staged_sidecar, staged_record):
            fsync_file(item)
        fsync_directory(staging)

        # One syscall publishes the whole set. There is no window in which the
        # destination holds some of the three files.
        #
        # The publication commit point is this *call*, not the line after it.
        # os.rename completes inside C and a signal is delivered between
        # bytecodes, so `published = True` may never run even though the
        # directory is on disk -- measured with KeyboardInterrupt and SystemExit,
        # both of which escaped every handler here. Nothing may be concluded from
        # control flow; the filesystem is asked instead.
        staging_identity = directory_identity(staging)

        # One transaction, from the syscall to the successful return. An earlier
        # version guarded only the `os.rename` call, which left the very next
        # line -- the one that records that the rename happened -- outside every
        # handler: an interruption there produced exit 2 and "nothing published"
        # over a complete directory. Measured with KeyboardInterrupt, SystemExit
        # and a custom BaseException. The boundary now ends where the function
        # does, and the verdict comes from the filesystem rather than from
        # whether `published` was ever assigned.
        try:
            os.rename(staging, output_dir)
            published = True
            fsync_directory(output_dir.parent)
            return record
        except BaseException as error:  # noqa: BLE001 - classified below, never swallowed
            state = observe_publication(staging, output_dir, staging_identity)
            # `False` is the only answer that permits claiming absence. `None`
            # means the check itself failed, and an unknown is not a denial.
            if state["output_exists"] is not False:
                published = True
                raise PublishedDurabilityUncertain(
                    describe_interrupted_publication(output_dir, record, state, error)) from error
            if isinstance(error, OSError):
                raise Refused(f"could not publish the output directory: {error}") from error
            raise
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the canonical release ZIP and checksum companion.")
    parser.add_argument("--version", required=True, help="release version, e.g. 1.0.2")
    parser.add_argument("--target", required=True, help="40-character lowercase commit id")
    parser.add_argument("--output-dir", required=True,
                        help="directory to create; must not already exist")
    parser.add_argument("--require-tag", default=None,
                        help="exact tag ref that must resolve to --target; needs --expect-asset-sha256")
    parser.add_argument("--expect-asset-sha256", default=None,
                        help="digest the archive must reproduce, from an earlier pre-tag build")
    parser.add_argument("--repository", default=".", help="path inside the repository (default: cwd)")
    arguments = parser.parse_args(argv)

    # The CLI transaction runs from the call into `build()` through the success
    # report to the return. An interruption delivered after `build()` returned --
    # while printing, or on the return itself -- previously escaped as an
    # uncaught traceback beside a complete output directory. `Refused` keeps its
    # own branch because it is raised only by preconditions, where the
    # destination is known not to have been created.
    output_dir = Path(arguments.output_dir)
    try:
        record = build(arguments)
        print(f"built {record['asset']['name']} sha256={record['asset']['sha256']} "
              f"size={record['asset']['size']} files={record['asset']['file_count']} "
              f"target={record['target_commit']}")
        return EXIT_OK
    except PublishedDurabilityUncertain as state:
        print(f"published-durability-uncertain: {state}", file=sys.stderr)
        return EXIT_PUBLISHED_DURABILITY_UNCERTAIN
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return EXIT_REFUSED_BEFORE_PUBLISH
    except BaseException as unexpected:  # noqa: BLE001 - classified by the filesystem
        return report_unexpected_outcome(output_dir, unexpected)


if __name__ == "__main__":
    raise SystemExit(main())
