#!/usr/bin/env bash
set -euo pipefail

TAG="v1.0.1"
VERSION_VALUE="1.0.1"
RELEASE_DATE="2026-07-30"
STAGING_BRANCH="v1.0.1-release-staging"
ASSET_NAME="square-riesz-polarization-certificates-v1.0.1.zip"
PREFIX="square-riesz-polarization-certificates-v1.0.1"
WORKFLOW_PATH=".github/workflows/v1.0.1-release-publisher.yml"
SCRIPT_PATH=".github/release/v1.0.1-publish.sh"
REPLAY_DIR="${RUNNER_TEMP}/v1.0.1-full-replay"

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"

echo "::group::Preflight"
test "$(tr -d '\r\n' < VERSION)" = "$VERSION_VALUE"
grep -q 'version: "1.0.1"' CITATION.cff
grep -q 'date-released: "2026-07-30"' CITATION.cff
grep -q '/releases/tag/v1.0.1' CITATION.cff
test -f RELEASE_NOTES_v1.0.1.md
test -f MANIFEST_POLICY.json
test -f "$WORKFLOW_PATH"
test -f "$SCRIPT_PATH"

if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
  echo "::error::$TAG already exists"
  exit 1
fi
if gh release view "$TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo "::error::$TAG Release already exists"
  exit 1
fi
gh api --method DELETE \
  "repos/${GITHUB_REPOSITORY}/git/refs/heads/${STAGING_BRANCH}" \
  >/dev/null 2>&1 || true
echo "::endgroup::"

echo "::group::Verify scoped corpus"
python scripts/regenerate_manifest.py
python scripts/verify_manifest.py
python scripts/check_release.py
echo "::endgroup::"

echo "::group::Full 88-verifier replay"
rm -rf "$REPLAY_DIR"
python scripts/verify_all.py --all --jobs 2 --output-dir "$REPLAY_DIR"
python - "$REPLAY_DIR/summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1], encoding="utf-8"))
assert summary["verifier_count"] == 88, summary
assert summary["certified_count"] == 88, summary
assert all(item["certified"] for item in summary["results"]), summary
print("full_replay=88/88_CERTIFIED")
PY
echo "::endgroup::"

echo "::group::Finalize release tree"
git rm "$WORKFLOW_PATH" "$SCRIPT_PATH"
python - "$REPLAY_DIR/summary.json" <<'PY'
import json
import os
import pathlib
import re
import subprocess
import sys

root = pathlib.Path.cwd()
summary = json.load(open(sys.argv[1], encoding="utf-8"))
paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
paths = [p for p in paths if p and p not in {"PUBLICATION_AUDIT.json", "SHA256SUMS"}]

findings = []
patterns = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "local_container_path": re.compile(r"/mnt/data/"),
    "mac_user_path": re.compile(r"/Users/[^/\s]+/"),
    "unrelated_notebook": re.compile(
        r"P02_AIAGENTSEC_M3_HOSTED_SAFE_SINGLE_POST_BASELINE_v09\.ipynb"
    ),
    "private_mailbox": re.compile(r"(?:erichfriedman68|sts0516k)@gmail\.com", re.I),
}

for relative in paths:
    candidate = root / relative
    try:
        text = candidate.read_text(encoding="utf-8")
    except (UnicodeDecodeError, IsADirectoryError):
        continue
    for name, pattern in patterns.items():
        if pattern.search(text):
            findings.append({"path": relative, "pattern": name})

readme = (root / "README.md").read_text(encoding="utf-8")
if "Driedsandwich supervised the research" not in readme:
    findings.append({"path": "README.md", "pattern": "public_attribution_boundary"})

if findings:
    print(json.dumps(findings, indent=2))
    raise SystemExit("privacy or secret scan failed")

audit = {
    "release_version": "1.0.1",
    "audit_run_id": os.environ["GITHUB_RUN_ID"],
    "files_scanned": len(paths),
    "patterns_checked": sorted(patterns) + ["public_attribution_boundary"],
    "findings": [],
    "internal_manifest": {
        "policy": "MANIFEST_POLICY.json",
        "entry_count": sum(
            1
            for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ),
    },
    "full_release_replay": {
        "verifiers": summary["verifier_count"],
        "certified": summary["certified_count"],
        "failed": summary["verifier_count"] - summary["certified_count"],
    },
    "mathematical_changes_from_v1.0.0": False,
    "status": "PASS",
    "repository_url": (
        "https://github.com/Driedsandwich/"
        "square-riesz-polarization-certificates"
    ),
    "release_url": (
        "https://github.com/Driedsandwich/"
        "square-riesz-polarization-certificates/releases/tag/v1.0.1"
    ),
    "excluded_from_internal_manifest": [
        "PUBLICATION_AUDIT.json",
        "SHA256SUMS",
        "human-facing documentation",
        "GitHub automation",
    ],
}
(root / "PUBLICATION_AUDIT.json").write_text(
    json.dumps(audit, indent=2) + "\n",
    encoding="utf-8",
)

record_lines = [
    "# GitHub release operator record — v1.0.1",
    "",
    "## Mathematical boundary",
    "",
    "- Fixed configurations changed from v1.0.0: **no**",
    "- Certified lower bounds changed from v1.0.0: **no**",
    "- Exact certifier algorithms changed from v1.0.0: **no**",
    (
        "- Fresh publication replay: "
        f"**{summary['certified_count']}/{summary['verifier_count']} CERTIFIED**"
    ),
    "",
    "## Completed pre-publication checks",
    "",
    "- [x] Scoped manifest regenerated and verified.",
    "- [x] Release structure check passed.",
    "- [x] All 88 exact certifiers passed in fresh processes.",
    "- [x] Privacy and secret scan reported zero findings.",
    "- [x] README public-attribution boundary preserved.",
    "- [x] v1.0.0 tag, Release, and existing assets were not modified.",
    "",
    "## Publication mechanism",
    "",
    (
        "The canonical deterministic ZIP is generated from the final tagged "
        "commit. A draft Release receives the ZIP and checksum companion "
        "before publication. After draft-asset verification, the Release is "
        "published and checked for immutable status."
    ),
    "",
    (
        "Workflow run: https://github.com/"
        f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
        f"{os.environ['GITHUB_RUN_ID']}"
    ),
]
(root / "docs" / "release-record-v1.0.1.md").write_text(
    "\n".join(record_lines) + "\n",
    encoding="utf-8",
)
PY

python scripts/regenerate_manifest.py
python scripts/verify_manifest.py
python scripts/check_release.py
python scripts/verify_all.py --quick --jobs 2

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git commit -m "release: finalize v1.0.1 state"

FINAL_SHA="$(git rev-parse HEAD)"
BASE_REMOTE="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
test "$(git rev-parse HEAD^)" = "$BASE_REMOTE"
git push origin "$FINAL_SHA:refs/heads/$STAGING_BRANCH"
echo "::endgroup::"

echo "::group::Build deterministic assets"
ASSET="${RUNNER_TEMP}/${ASSET_NAME}"
CHECKSUM="${RUNNER_TEMP}/${ASSET_NAME}.sha256"
git archive --format=zip --prefix="${PREFIX}/" --output="$ASSET" "$FINAL_SHA"
ZIP_SHA="$(sha256sum "$ASSET" | awk '{print $1}')"
ZIP_SIZE="$(wc -c < "$ASSET" | tr -d ' ')"
printf '%s  %s\n' "$ZIP_SHA" "$ASSET_NAME" > "$CHECKSUM"
unzip -t "$ASSET" >/dev/null

EXTRACT_DIR="${RUNNER_TEMP}/v1.0.1-extracted"
rm -rf "$EXTRACT_DIR"
mkdir -p "$EXTRACT_DIR"
unzip -q "$ASSET" -d "$EXTRACT_DIR"
(
  cd "$EXTRACT_DIR/$PREFIX"
  test "$(tr -d '\r\n' < VERSION)" = "$VERSION_VALUE"
  test ! -e "$WORKFLOW_PATH"
  test ! -e "$SCRIPT_PATH"
  grep -q 'Driedsandwich supervised the research' README.md
  python scripts/verify_manifest.py
  python scripts/check_release.py
  python scripts/verify_all.py --quick --jobs 2
)
echo "::endgroup::"

echo "::group::Create and verify draft Release"
gh release create "$TAG" \
  "$ASSET#Canonical deterministic source and certificate corpus" \
  "$CHECKSUM#SHA-256 checksum for the canonical ZIP" \
  --repo "$GITHUB_REPOSITORY" \
  --target "$FINAL_SHA" \
  --title "v1.0.1 — Documentation and reproducibility hardening" \
  --notes-file RELEASE_NOTES_v1.0.1.md \
  --draft

DRAFT_JSON="${RUNNER_TEMP}/v1.0.1-draft-release.json"
gh release view "$TAG" \
  --repo "$GITHUB_REPOSITORY" \
  --json tagName,isDraft,isPrerelease,targetCommitish,assets,url \
  > "$DRAFT_JSON"
test "$(jq -r '.tagName' "$DRAFT_JSON")" = "$TAG"
test "$(jq -r '.isDraft' "$DRAFT_JSON")" = "true"
test "$(jq -r '.isPrerelease' "$DRAFT_JSON")" = "false"
test "$(jq '.assets | length' "$DRAFT_JSON")" = "2"

DRAFT_DOWNLOAD="${RUNNER_TEMP}/v1.0.1-draft-download"
rm -rf "$DRAFT_DOWNLOAD"
mkdir -p "$DRAFT_DOWNLOAD"
gh release download "$TAG" \
  --repo "$GITHUB_REPOSITORY" \
  --dir "$DRAFT_DOWNLOAD"
(
  cd "$DRAFT_DOWNLOAD"
  test -f "$ASSET_NAME"
  test -f "${ASSET_NAME}.sha256"
  sha256sum -c "${ASSET_NAME}.sha256"
  test "$(find . -maxdepth 1 -type f | wc -l | tr -d ' ')" = "2"
)
echo "::endgroup::"

echo "::group::Publish and verify immutable Release"
gh release edit "$TAG" \
  --repo "$GITHUB_REPOSITORY" \
  --draft=false \
  --latest

PUBLISHED_JSON="${RUNNER_TEMP}/v1.0.1-published-release.json"
gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${GITHUB_REPOSITORY}/releases/tags/${TAG}" \
  > "$PUBLISHED_JSON"

if [[ "$(jq -r '.immutable // false' "$PUBLISHED_JSON")" != "true" ]]; then
  gh release delete "$TAG" --repo "$GITHUB_REPOSITORY" --yes --cleanup-tag
  gh api --method DELETE \
    "repos/${GITHUB_REPOSITORY}/git/refs/heads/${STAGING_BRANCH}" \
    >/dev/null 2>&1 || true
  echo "::error::Release immutability is not enabled."
  exit 1
fi

test "$(jq -r '.draft' "$PUBLISHED_JSON")" = "false"
test "$(jq -r '.prerelease' "$PUBLISHED_JSON")" = "false"
test "$(jq '.assets | length' "$PUBLISHED_JSON")" = "2"
TAG_SHA="$(git ls-remote origin "refs/tags/$TAG" | awk '{print $1}')"
test "$TAG_SHA" = "$FINAL_SHA"

PUBLISHED_DOWNLOAD="${RUNNER_TEMP}/v1.0.1-published-download"
rm -rf "$PUBLISHED_DOWNLOAD"
mkdir -p "$PUBLISHED_DOWNLOAD"
gh release download "$TAG" \
  --repo "$GITHUB_REPOSITORY" \
  --dir "$PUBLISHED_DOWNLOAD"
(
  cd "$PUBLISHED_DOWNLOAD"
  sha256sum -c "${ASSET_NAME}.sha256"
  test "$(find . -maxdepth 1 -type f | wc -l | tr -d ' ')" = "2"
)
RELEASE_URL="$(jq -r '.html_url' "$PUBLISHED_JSON")"
echo "::endgroup::"

echo "::group::Advance main"
CURRENT_MAIN="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
test "$(git rev-parse "$FINAL_SHA^")" = "$CURRENT_MAIN"
git push origin "$FINAL_SHA:refs/heads/main"
REMOTE_MAIN="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
test "$REMOTE_MAIN" = "$FINAL_SHA"
gh api --method DELETE \
  "repos/${GITHUB_REPOSITORY}/git/refs/heads/${STAGING_BRANCH}" \
  >/dev/null 2>&1 || echo "::warning::Could not delete staging branch"
echo "::endgroup::"

{
  echo "## v1.0.1 publication result"
  echo "- final main/tag: $FINAL_SHA"
  echo "- canonical ZIP SHA-256: $ZIP_SHA"
  echo "- canonical ZIP size: $ZIP_SIZE bytes"
  echo "- Release: $RELEASE_URL"
  echo "- immutable: true"
  echo "- assets: 2/2 verified after re-download"
  echo "- full replay: 88/88 CERTIFIED"
} >> "$GITHUB_STEP_SUMMARY"
