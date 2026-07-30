#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import PurePosixPath

sys.dont_write_bytecode = True

from manifest_policy import ROOT, collect_expected_files, load_policy, sha256_file

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    policy = load_policy()
    manifest_path = ROOT / policy["manifest_path"]
    expected = set(collect_expected_files(policy))

    errors: list[str] = []
    listed: dict[str, str] = {}

    if not manifest_path.is_file():
        errors.append(f"missing manifest: {manifest_path.relative_to(ROOT)}")
    else:
        for line_number, raw_line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                digest, relative = raw_line.split("  ", 1)
            except ValueError:
                errors.append(f"malformed manifest line {line_number}")
                continue

            path = PurePosixPath(relative)
            if not HEX64.fullmatch(digest):
                errors.append(f"invalid SHA-256 on line {line_number}: {relative}")
            if path.is_absolute() or ".." in path.parts or not path.parts:
                errors.append(f"unsafe path on line {line_number}: {relative}")
                continue
            relative = path.as_posix()
            if relative in listed:
                errors.append(f"duplicate manifest path: {relative}")
                continue
            listed[relative] = digest

    listed_paths = set(listed)
    missing = sorted(expected - listed_paths)
    unexpected = sorted(listed_paths - expected)
    bad_hash: list[str] = []

    for relative in sorted(expected & listed_paths):
        candidate = ROOT / relative
        if not candidate.is_file() or sha256_file(candidate) != listed[relative]:
            bad_hash.append(relative)

    print(
        " ".join(
            [
                f"expected={len(expected)}",
                f"listed={len(listed)}",
                f"missing={len(missing)}",
                f"unexpected={len(unexpected)}",
                f"bad_hash={len(bad_hash)}",
                f"errors={len(errors)}",
            ]
        )
    )

    for heading, items in (
        ("errors", errors),
        ("missing", missing),
        ("unexpected", unexpected),
        ("bad_hash", bad_hash),
    ):
        if items:
            print(f"[{heading}]")
            print("\n".join(items))

    return 1 if errors or missing or unexpected or bad_hash else 0


if __name__ == "__main__":
    raise SystemExit(main())
