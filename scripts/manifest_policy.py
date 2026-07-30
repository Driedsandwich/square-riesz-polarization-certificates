#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "MANIFEST_POLICY.json"


def load_policy() -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ValueError("unsupported MANIFEST_POLICY.json schema_version")
    for key in ("manifest_path", "include_roots", "include_files", "exclude_files", "exclude_globs"):
        if key not in policy:
            raise ValueError(f"manifest policy missing key: {key}")
    return policy


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe manifest path: {value!r}")
    return path.as_posix()


def _is_excluded(relative_path: str, policy: dict[str, Any]) -> bool:
    path = PurePosixPath(relative_path)
    return any(path.match(pattern) for pattern in policy["exclude_globs"])


def collect_expected_files(policy: dict[str, Any]) -> list[str]:
    expected: set[str] = set()

    for relative_root in policy["include_roots"]:
        relative_root = _safe_relative_path(str(relative_root))
        root = ROOT / relative_root
        if not root.is_dir():
            raise ValueError(f"manifest include root is missing: {relative_root}")
        for candidate in root.rglob("*"):
            if candidate.is_file():
                relative = candidate.relative_to(ROOT).as_posix()
                if not _is_excluded(relative, policy):
                    expected.add(relative)

    for relative_file in policy["include_files"]:
        relative_file = _safe_relative_path(str(relative_file))
        candidate = ROOT / relative_file
        if not candidate.is_file():
            raise ValueError(f"manifest include file is missing: {relative_file}")
        if not _is_excluded(relative_file, policy):
            expected.add(relative_file)

    for relative_file in policy["exclude_files"]:
        expected.discard(_safe_relative_path(str(relative_file)))

    manifest_path = _safe_relative_path(str(policy["manifest_path"]))
    expected.discard(manifest_path)
    return sorted(expected)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
