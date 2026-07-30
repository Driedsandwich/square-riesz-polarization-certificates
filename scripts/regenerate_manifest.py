#!/usr/bin/env python3
from __future__ import annotations

from manifest_policy import ROOT, collect_expected_files, load_policy, sha256_file


def main() -> int:
    policy = load_policy()
    manifest_path = ROOT / policy["manifest_path"]
    expected = collect_expected_files(policy)
    lines = [f"{sha256_file(ROOT / relative)}  {relative}" for relative in expected]
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote={len(lines)} manifest={manifest_path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
