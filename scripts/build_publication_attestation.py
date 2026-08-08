#!/usr/bin/env python3
"""Build the publication-attestation asset from measured release facts.

Why this is an asset and not release notes: GitHub's immutable releases protect
the tag and the **assets**, and its documentation states that "you can only edit
the title and release notes after a release is published". A record kept in the
release body would stay editable for the life of the release and could not be
the integrity authority. Uploading it as a third asset to the draft release,
before publication, puts it inside what immutability actually covers.

The generator measures nothing. It reads two files -- the facts gathered from
GitHub and CI during the release, and the **machine-produced build record** from
``build_release_assets.py`` -- and refuses unless they agree with each other and
with this project's fixed history.

Four things this file learned the hard way.

*An accepted record is not a checked record.* An earlier version required a
handful of fields by name and let everything else through, so it accepted a
record whose builder was never bound to the target commit, a record from a
tagged build with no expected digest, and a fixture record in which
``check_release.py`` had never run. The record schema is now exact: every
top-level key and every key of every nested block is named, unknown keys are
refused, and a boolean in an integer slot is refused.

*A digest without its preimage is not evidence.* The attestation used to record
``build_record_sha256`` while the record itself stayed on the build machine, so
a reader of the published release could not check what the digest was of. The
strictly validated record is embedded here in full, and the digest is
recomputable from the embedded object.

*Two identifiers of different lengths are not a binding.* A 40-hex blob id and a
64-hex file digest cannot be pasted into each other's slot, which is a type
rule, not provenance. The builder now hashes the blob and the executing script
and refuses when they differ, and this file takes both values from the record --
``builder_script_blob_oid`` is no longer something a human types.

*After the rename there is no such thing as "nothing published".* Failing the
directory ``fsync`` that follows ``os.replace`` produced exit 2 and the message
``nothing published`` while a complete, valid attestation sat on disk --
measured at 4626 bytes. That state now has its own exit code.

Two facts can never appear: this file cannot state its own GitHub asset id or
its own digest, because both come into being when it is uploaded. Those, and the
post-publication immutable read-back, belong to GitHub's generated release
attestation and to the external execution evidence -- which is why the status
below says only what is true *before* this asset is uploaded.

Standard library only. No network access, no GitHub write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "square-riesz-publication-attestation.v3"
BUILD_RECORD_SCHEMA = "square-riesz-release-asset-build.v4"
PROJECT = "square-riesz-polarization-certificates"
VERSION = "1.0.2"
TAG = f"v{VERSION}"
TAG_REF = f"refs/tags/{TAG}"
PREFIX = f"{PROJECT}-v{VERSION}/"
ZIP_NAME = f"{PROJECT}-v{VERSION}.zip"
SIDECAR_NAME = f"{ZIP_NAME}.sha256"
RECORD_NAME = "build-record.json"
ATTESTATION_NAME = f"{PROJECT}-v{VERSION}.publication-attestation.json"
REPOSITORY = f"Driedsandwich/{PROJECT}"
STATUS = "PRE_PUBLICATION_DISTRIBUTION_ASSETS_VERIFIED"
BUILDER_PATH_IN_TREE = "scripts/build_release_assets.py"
OUTPUT_INVENTORY = sorted([ZIP_NAME, SIDECAR_NAME, RECORD_NAME])
# What the draft Release must hold when this document is generated: the two
# distribution assets and nothing else. The attestation itself is uploaded
# afterwards, so it cannot appear here.
PRE_ATTESTATION_ASSET_NAMES = sorted([ZIP_NAME, SIDECAR_NAME])
ARCHIVE_CHECKS = ("verify_manifest.py", "check_release.py")

SMOKE_WORKFLOW = "smoke-test"
REPLAY_WORKFLOW = "full-certificate-replay"
REPLAY_ARTIFACT_NAME = "full-replay-logs"
RELEASE_BRANCH = "main"
RELEASE_EVENT = "push"

# Fixed history. These are already published and cannot change; pinning them
# here means a fact sheet from a different repository or a different release
# cannot be passed off as this one.
V1_0_0_TARGET = "2f01c00693a1304b063077238d4e86ba7fae9744"
V1_0_1_TARGET = "d92992101ca45a5cd755b8d962652ab7e4329973"
AUDIT_BRANCH_TARGET = "b57c436bdcdec2e7770f49345255a93c373c44c2"
MERGE_FIRST_PARENT = "2adfffb7dc68f40ea52fd1ed78bc2f11a46de78b"
EXPECTED_REPLAY_COUNT = 88
EXPECTED_RUN_ATTEMPT = 1

# The exact argv the builder must record, with its two local paths redacted.
# `/dev/null` is spelled out rather than taken from ``os.devnull`` so the
# requirement describes the released record, not the machine reading it.
EXPECTED_ARCHIVE_COMMAND = [
    "git", "--no-replace-objects", "-c", "core.attributesFile=/dev/null",
    "-C", "<REPOSITORY>", "archive", "--format=zip", "-9",
    f"--prefix={PREFIX}", "--output=<OUTPUT_ZIP>",
]

HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
# Two separate patterns on purpose. A single case-insensitive pattern made the
# angle-bracket rule match lowercase too, which flagged the builder's own
# `--prefix=… <target>` shorthand as an unfilled field. An unfilled field is
# written in capitals by convention; a lowercase schematic is prose.
PLACEHOLDER_WORD = re.compile(r"(?i)\b(TODO|TBD|FIXME|XXX+|PLACEHOLDER|CHANGEME|REPLACE_ME)\b")
PLACEHOLDER_SLOT = re.compile(r"<[A-Z_]{3,}>")
ALLOWED_REDACTIONS = ("<REPOSITORY>", "<OUTPUT_ZIP>")
SECRET = re.compile(
    r"(?i)(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"\bauthorization\s*:|\bbearer\s+[A-Za-z0-9._\-]{10,}|\bAKIA[0-9A-Z]{16}\b|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)")

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_REFUSED_BEFORE_PUBLISH = EXIT_REFUSED
EXIT_PUBLISHED_DURABILITY_UNCERTAIN = 3

# Facts that can only come from GitHub and CI. Everything the builder knows is
# read from the build record instead, so there is nothing to keep in sync by hand.
REQUIRED_FACTS: dict[str, str] = {
    "generated_at_utc": "utc",
    "repository_full_name": "text",
    "draft_release_id": "posint",
    "draft_release_tag_name": "text",
    "draft_release_is_draft": "bool",
    "tag_target": "sha40",
    "merge_commit": "sha40",
    "merge_tree": "sha40",
    "merge_parent_base": "sha40",
    "merge_parent_release_branch": "sha40",
    "smoke_test_run_id": "posint",
    "smoke_test_workflow_name": "text",
    "smoke_test_event": "text",
    "smoke_test_head_branch": "text",
    "smoke_test_head_sha": "sha40",
    "smoke_test_conclusion": "conclusion",
    "smoke_test_run_attempt": "posint",
    "full_replay_run_id": "posint",
    "full_replay_workflow_name": "text",
    "full_replay_event": "text",
    "full_replay_head_branch": "text",
    "full_replay_head_sha": "sha40",
    "full_replay_conclusion": "conclusion",
    "full_replay_run_attempt": "posint",
    "replay_artifact_id": "posint",
    "replay_artifact_name": "text",
    "replay_artifact_run_id": "posint",
    "replay_artifact_expired": "bool",
    "replay_artifact_sha256": "sha256",
    "replay_artifact_size": "posint",
    "validator_records_checked": "nonneg",
    "validator_script_hashes_verified": "nonneg",
    "validator_proof_output_verified": "nonneg",
    "validator_source_commit_verified": "nonneg",
    "validator_source_clean_verified": "nonneg",
    "validator_problems": "nonneg",
    "validator_exit_code": "nonneg",
    "draft_asset_count_before_attestation": "posint",
    "draft_asset_names_before_attestation": "textlist",
    "draft_asset_ids_before_attestation": "intlist",
    "zip_asset_id": "posint",
    "zip_asset_name": "text",
    "zip_asset_release_id": "posint",
    "zip_sha256_uploaded": "sha256",
    "zip_sha256_redownloaded": "sha256",
    "sidecar_asset_id": "posint",
    "sidecar_asset_name": "text",
    "sidecar_asset_release_id": "posint",
    "sidecar_sha256_redownloaded": "sha256",
    "sidecar_check_passed": "bool",
    "v1_0_0_tag_target": "sha40",
    "v1_0_1_tag_target": "sha40",
    "v1_0_0_assets_unchanged": "bool",
    "v1_0_1_assets_unchanged": "bool",
    "audit_branch_retained": "bool",
    "audit_branch_target": "sha40",
}

FORBIDDEN_FACTS = (
    "attestation_asset_id", "attestation_sha256", "immutable", "immutable_read_back",
    "release_attestation_verified", "published_at",
    # These used to be hand-copied and are now taken from the build record.
    "builder_command", "git_version", "builder_platform",
    "builder_script_blob_oid", "builder_script_sha256", "build_record_sha256",
    "zip_sha256_local", "sidecar_sha256_local", "zip_size", "sidecar_size",
)

# The build record, named field by field. A key that is not here is refused, so
# a record with an extra block cannot smuggle anything into the published
# attestation, and a record missing a block cannot silently skip a check.
RECORD_FIELDS: dict[str, str] = {
    "schema": "text",
    "generated_at_utc": "utc",
    "project": "text",
    "version": "text",
    "head_commit": "sha40",
    "target_commit": "sha40",
    "target_tree": "sha40",
    "require_tag": "text",
    "tag_ref": "text",
    "tag_target": "sha40",
    "committed_version": "text",
    "builder_script": "text",
    "builder_script_blob_oid": "sha40",
    "builder_script_mode": "text",
    "builder_script_target_sha256": "sha256",
    "builder_script_executed_sha256": "sha256",
    "builder_script_matches_target": "bool",
    "archive_command": "textlist",
    "repository": "text",
    "output_zip": "text",
    "generation_semantics": "text",
    "environment": "object",
    "git_version": "text",
    "python_version": "text",
    "platform": "text",
    "asset": "object",
    "sidecar": "object",
    "raw_tree_comparison": "object",
    "archive_self_verification": "object",
    "expected_asset_sha256": "sha256",
    "output_inventory": "textlist",
    "determinism_note": "text",
    "github_writes": "nonneg",
}

RECORD_NESTED: dict[str, dict[str, str]] = {
    "environment": {"timezone": "text", "locale": "text", "inherited": "textlist",
                    "fixed": "object", "dropped": "textlist"},
    "asset": {"name": "text", "sha256": "sha256", "size": "posint", "entry_count": "posint",
              "file_count": "posint", "uncompressed_size": "posint", "archive_comment": "text"},
    "sidecar": {"name": "text", "sha256": "sha256", "size": "posint"},
    "raw_tree_comparison": {"tree_paths": "posint", "compared_paths": "posint",
                            "executable_paths": "nonneg"},
    "archive_self_verification": {"ran": "object", "not_present_in_archive": "textlist"},
}
RECORD_CHECK_FIELDS = {"exit_code": "nonneg", "stdout_tail": "textlist"}

CANONICALISATION = ('json.dumps(build_record, indent=2, sort_keys=True) + "\\n", encoded UTF-8; '
                    "sha256 of those bytes is build_record_sha256")


class Refused(Exception):
    """The facts did not check out. Nothing was written."""


class PublishedDurabilityUncertain(Exception):
    """os.replace succeeded and then a durability step failed.

    The attestation file exists and is complete. It must not be regenerated over
    and must not be uploaded automatically until its state has been checked.
    """


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise Refused(f"input has duplicate keys: {duplicates}")
    return dict(pairs)


def _no_constants(token):
    raise Refused(f"input contains the non-JSON constant {token}")


def reject_nonfinite(value, label: str, path: str = "") -> None:
    """`parse_constant` catches NaN and Infinity by name; 1e999 arrives as a float."""
    if isinstance(value, dict):
        for key, item in value.items():
            reject_nonfinite(item, label, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_nonfinite(item, label, f"{path}[{index}]")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise Refused(f"{label}{path} is a non-finite number")
        raise Refused(f"{label}{path} is a float; every number in this document is a count")


def load_json(path: Path, label: str) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise Refused(f"cannot read {label} {path}: {error}")
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
    except Refused:
        raise
    except json.JSONDecodeError as error:
        raise Refused(f"{label} is not valid JSON: {error}")
    if not isinstance(value, dict):
        raise Refused(f"{label} must be a JSON object")
    reject_nonfinite(value, label)
    return value


def check_scalar(name: str, kind: str, value) -> None:
    if kind in ("posint", "nonneg"):
        # bool is a subclass of int, so a count must reject it explicitly or
        # `true` silently satisfies it.
        if isinstance(value, bool) or not isinstance(value, int):
            raise Refused(f"{name} must be an integer, got {type(value).__name__} {value!r}")
        if kind == "posint" and value <= 0:
            raise Refused(f"{name} must be a positive integer, got {value}")
        if kind == "nonneg" and value < 0:
            raise Refused(f"{name} must be zero or greater, got {value}")
        return
    if kind == "bool":
        if not isinstance(value, bool):
            raise Refused(f"{name} must be a boolean, got {type(value).__name__} {value!r}")
        return
    if kind == "object":
        if not isinstance(value, dict):
            raise Refused(f"{name} must be an object, got {type(value).__name__}")
        return
    if kind == "textlist":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise Refused(f"{name} must be a list of strings")
        return
    if kind == "intlist":
        # bool is a subclass of int here too, so `[true, true]` would otherwise
        # satisfy a list of asset ids.
        if not isinstance(value, list) or not all(
                isinstance(x, int) and not isinstance(x, bool) for x in value):
            raise Refused(f"{name} must be a list of integers")
        if any(x <= 0 for x in value):
            raise Refused(f"{name} must contain positive integers")
        return
    if not isinstance(value, str):
        raise Refused(f"{name} must be a string, got {type(value).__name__} {value!r}")
    if kind == "text" and not value:
        raise Refused(f"{name} must not be empty")
    if kind == "sha40" and not HEX40.match(value):
        raise Refused(f"{name} must be a 40-character lowercase hex sha, got {value!r}")
    if kind == "sha256" and not HEX64.match(value):
        raise Refused(f"{name} must be a 64-character lowercase hex digest, got {value!r}")
    if kind == "conclusion" and value != "success":
        raise Refused(f"{name} must be 'success' before publication, got {value!r}")
    if kind == "utc":
        check_real_utc_timestamp(name, value)


def parse_utc(name: str, value: str) -> datetime:
    """A calendar parse, not a shape match.

    An earlier version used a regex, so ``2026-99-99T99:99:99Z`` passed. The
    round-trip is what rejects a date that parses loosely but does not spell
    back to the same string.
    """
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise Refused(f"{name} is not a real UTC timestamp: {value!r} ({error})")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise Refused(f"{name} does not round-trip to its canonical spelling: {value!r}")
    return parsed


def check_real_utc_timestamp(name: str, value: str) -> None:
    parse_utc(name, value)


def check_facts(facts: dict) -> None:
    for forbidden in FORBIDDEN_FACTS:
        if forbidden in facts:
            raise Refused(
                f"{forbidden!r} must not be supplied: it is either something this asset cannot "
                "know about itself, or a builder fact that must come from the build record "
                "rather than being retyped")
    missing = sorted(set(REQUIRED_FACTS) - set(facts))
    if missing:
        raise Refused(f"missing required fact(s): {missing}")
    unknown = sorted(set(facts) - set(REQUIRED_FACTS))
    if unknown:
        raise Refused(f"unknown fact(s): {unknown}")
    for name, kind in REQUIRED_FACTS.items():
        if facts[name] is None:
            raise Refused(f"{name} is null; every field must be a measured value")
        check_scalar(name, kind, facts[name])


def check_exact_object(block, fields: dict[str, str], label: str) -> None:
    if not isinstance(block, dict):
        raise Refused(f"{label} must be an object")
    missing = sorted(set(fields) - set(block))
    if missing:
        raise Refused(f"{label} is missing {missing}")
    unknown = sorted(set(block) - set(fields))
    if unknown:
        raise Refused(f"{label} has unknown field(s) {unknown}")
    for name, kind in fields.items():
        if block[name] is None:
            raise Refused(f"{label}.{name} is null")
        check_scalar(f"{label}.{name}", kind, block[name])


def check_build_record(record: dict) -> None:
    """The record is checked as a whole document, not field by remembered field."""
    check_exact_object(record, RECORD_FIELDS, "build record")
    for section, fields in RECORD_NESTED.items():
        check_exact_object(record[section], fields, f"build record {section}")

    if record["schema"] != BUILD_RECORD_SCHEMA:
        raise Refused(f"build record schema must be {BUILD_RECORD_SCHEMA!r}, got {record['schema']!r}")
    if record["project"] != PROJECT:
        raise Refused(f"build record project must be {PROJECT!r}, got {record['project']!r}")
    for name, expected in (("version", VERSION), ("committed_version", VERSION),
                           ("require_tag", TAG), ("tag_ref", TAG_REF),
                           ("builder_script", BUILDER_PATH_IN_TREE),
                           ("repository", "<REPOSITORY>"), ("output_zip", "<OUTPUT_ZIP>")):
        if record[name] != expected:
            raise Refused(f"build record {name} must be {expected!r}, got {record[name]!r}")
    if record["github_writes"] != 0:
        raise Refused("build record must report github_writes = 0")

    # one commit, three names for it
    if record["tag_target"] != record["target_commit"]:
        raise Refused("build record tag_target and target_commit disagree")
    if record["head_commit"] != record["target_commit"]:
        raise Refused("the build did not run from a checkout of the commit it archived: "
                      f"head_commit {record['head_commit']} is not target_commit "
                      f"{record['target_commit']}")

    # the builder that ran is the builder in the tree
    if record["builder_script_mode"] not in ("100644", "100755"):
        raise Refused(f"build record builder_script_mode is {record['builder_script_mode']!r}")
    if not record["builder_script_matches_target"]:
        raise Refused("the build record says the executing builder did not match the builder blob "
                      "in the target commit")
    if record["builder_script_target_sha256"] != record["builder_script_executed_sha256"]:
        raise Refused("the build record's target and executed builder digests differ, so the "
                      "release was not built by the script inside the released commit")

    # the pre-tag digest gate was used
    if record["expected_asset_sha256"] != record["asset"]["sha256"]:
        raise Refused("the build record's expected_asset_sha256 does not equal the digest it "
                      "produced. A tagged build must reproduce a digest measured before the tag "
                      "existed, and the tag cannot be moved afterwards.")

    if record["asset"]["name"] != ZIP_NAME:
        raise Refused(f"build record asset name must be {ZIP_NAME!r}")
    if record["sidecar"]["name"] != SIDECAR_NAME:
        raise Refused(f"build record sidecar name must be {SIDECAR_NAME!r}")
    if record["output_inventory"] != OUTPUT_INVENTORY:
        raise Refused(f"build record output_inventory must be {OUTPUT_INVENTORY}, "
                      f"got {record['output_inventory']}")
    if record["asset"]["archive_comment"] != record["target_commit"]:
        raise Refused("the archive comment is not the target commit, so the ZIP does not carry "
                      "the id of the commit it was made from")

    environment = record["environment"]
    if environment["timezone"] != "UTC":
        raise Refused("the build must be made with TZ=UTC; git archive writes DOS member "
                      "timestamps in local time and an inherited timezone changes the digest")
    if environment["locale"] != "C":
        raise Refused("the build must be made with LC_ALL=C")
    for name in ("TZ", "LC_ALL"):
        if name not in environment["fixed"]:
            raise Refused(f"the build record's fixed environment does not pin {name}")
    if environment["fixed"].get("TZ") != "UTC" or environment["fixed"].get("LC_ALL") != "C":
        raise Refused("the build record's fixed environment does not pin TZ=UTC and LC_ALL=C")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_NAMESPACE"):
        if name not in environment["dropped"]:
            raise Refused(f"the build record does not record dropping {name}")

    expected_command = [*EXPECTED_ARCHIVE_COMMAND, record["target_commit"]]
    if record["archive_command"] != expected_command:
        raise Refused(f"the archive command is not the exact expected sequence. "
                      f"expected {expected_command}, got {record['archive_command']}")

    comparison = record["raw_tree_comparison"]
    if not (comparison["tree_paths"] == comparison["compared_paths"]
            == record["asset"]["file_count"]):
        raise Refused("the tree path count, the compared path count and the archive file count "
                      f"must agree: {comparison['tree_paths']}, {comparison['compared_paths']}, "
                      f"{record['asset']['file_count']}")

    verification = record["archive_self_verification"]
    if verification["not_present_in_archive"]:
        raise Refused("the released archive must contain every self-check; the build record "
                      f"reports {verification['not_present_in_archive']} missing")
    ran = verification["ran"]
    if sorted(ran) != sorted(ARCHIVE_CHECKS):
        raise Refused(f"the build record must show {sorted(ARCHIVE_CHECKS)} running inside the "
                      f"archive, got {sorted(ran)}")
    for script in ARCHIVE_CHECKS:
        check_exact_object(ran[script], RECORD_CHECK_FIELDS,
                           f"build record archive_self_verification.ran.{script}")
        if ran[script]["exit_code"] != 0:
            raise Refused(f"scripts/{script} exited {ran[script]['exit_code']} inside the archive")


def check_cross_field(facts: dict, record: dict) -> None:
    # identity of the repository and the draft
    if facts["repository_full_name"] != REPOSITORY:
        raise Refused(f"repository_full_name must be {REPOSITORY!r}, "
                      f"got {facts['repository_full_name']!r}")
    if facts["draft_release_tag_name"] != TAG:
        raise Refused(f"draft_release_tag_name must be {TAG!r}, "
                      f"got {facts['draft_release_tag_name']!r}")
    if not facts["draft_release_is_draft"]:
        raise Refused("draft_release_is_draft is false; the assets are verified while the release "
                      "is still a draft, before publication makes them immutable")

    # identity of the release commit
    if facts["tag_target"] != facts["merge_commit"]:
        raise Refused(f"tag_target {facts['tag_target']} is not the merge commit "
                      f"{facts['merge_commit']}")
    if record["target_commit"] != facts["merge_commit"]:
        raise Refused("the build record's target commit is not the merge commit; the assets were "
                      "built from a different commit than the one being released")
    if record["target_tree"] != facts["merge_tree"]:
        raise Refused("the build record's target tree is not the merge tree")
    if facts["merge_parent_base"] != MERGE_FIRST_PARENT:
        raise Refused(f"the merge's first parent must be {MERGE_FIRST_PARENT}, "
                      f"got {facts['merge_parent_base']}")
    if facts["merge_parent_base"] == facts["merge_parent_release_branch"]:
        raise Refused("the merge commit's two parents are identical; that is not a merge")
    if facts["merge_commit"] in (facts["merge_parent_base"], facts["merge_parent_release_branch"]):
        raise Refused("the merge commit cannot be its own parent")

    # the build happened before this document describes it
    built = parse_utc("build record generated_at_utc", record["generated_at_utc"])
    attested = parse_utc("generated_at_utc", facts["generated_at_utc"])
    if built > attested:
        raise Refused(f"the build record was generated at {record['generated_at_utc']}, after "
                      f"this attestation's {facts['generated_at_utc']}")

    # CI runs belong to this release
    for label, workflow, prefix in (("smoke test", SMOKE_WORKFLOW, "smoke_test"),
                                    ("full replay", REPLAY_WORKFLOW, "full_replay")):
        if facts[f"{prefix}_workflow_name"] != workflow:
            raise Refused(f"the {label} run is from workflow "
                          f"{facts[f'{prefix}_workflow_name']!r}, not {workflow!r}")
        if facts[f"{prefix}_event"] != RELEASE_EVENT:
            raise Refused(f"the {label} run was triggered by {facts[f'{prefix}_event']!r}; the "
                          f"release evidence is the {RELEASE_EVENT} run on {RELEASE_BRANCH}")
        if facts[f"{prefix}_head_branch"] != RELEASE_BRANCH:
            raise Refused(f"the {label} run is on branch {facts[f'{prefix}_head_branch']!r}, "
                          f"not {RELEASE_BRANCH!r}")
        if facts[f"{prefix}_head_sha"] != facts["merge_commit"]:
            raise Refused(f"the {label} run's head sha {facts[f'{prefix}_head_sha']} is not the "
                          f"merge commit {facts['merge_commit']}")
    if facts["smoke_test_run_id"] == facts["full_replay_run_id"]:
        raise Refused("the smoke-test and full-replay run ids are identical; they are different runs")

    # the validated artifact belongs to the full-replay run
    if facts["replay_artifact_name"] != REPLAY_ARTIFACT_NAME:
        raise Refused(f"replay_artifact_name must be {REPLAY_ARTIFACT_NAME!r}, "
                      f"got {facts['replay_artifact_name']!r}")
    if facts["replay_artifact_run_id"] != facts["full_replay_run_id"]:
        raise Refused("the replay artifact belongs to run "
                      f"{facts['replay_artifact_run_id']}, not the full-replay run "
                      f"{facts['full_replay_run_id']}")
    if facts["replay_artifact_expired"]:
        raise Refused("replay_artifact_expired is true; an expired artifact cannot be downloaded "
                      "and re-checked by a reader")

    for name in ("validator_records_checked", "validator_script_hashes_verified",
                 "validator_proof_output_verified"):
        if facts[name] != EXPECTED_REPLAY_COUNT:
            raise Refused(f"{name} must be exactly {EXPECTED_REPLAY_COUNT} for this project, "
                          f"got {facts[name]}")
    if facts["validator_problems"] != 0:
        raise Refused(f"validator_problems is {facts['validator_problems']}; publication requires 0")
    if facts["validator_exit_code"] != 0:
        raise Refused(f"validator_exit_code is {facts['validator_exit_code']}; publication requires 0")
    if facts["validator_source_commit_verified"] != 1:
        raise Refused("validator_source_commit_verified must be 1")
    if facts["validator_source_clean_verified"] != 1:
        raise Refused("validator_source_clean_verified must be 1; the release replay runs on a "
                      "committed tree, unlike the local candidate replay")
    for name in ("smoke_test_run_attempt", "full_replay_run_attempt"):
        if facts[name] != EXPECTED_RUN_ATTEMPT:
            raise Refused(f"{name} must be {EXPECTED_RUN_ATTEMPT}: a re-run means the first "
                          f"attempt did not pass, got {facts[name]}")

    # the two distribution assets are on this draft, under their canonical names
    if facts["zip_asset_id"] == facts["sidecar_asset_id"]:
        raise Refused("the ZIP and sidecar asset ids are identical; they are different assets")
    if facts["zip_asset_name"] != ZIP_NAME:
        raise Refused(f"zip_asset_name must be {ZIP_NAME!r}, got {facts['zip_asset_name']!r}")
    if facts["sidecar_asset_name"] != SIDECAR_NAME:
        raise Refused(f"sidecar_asset_name must be {SIDECAR_NAME!r}, "
                      f"got {facts['sidecar_asset_name']!r}")
    for name in ("zip_asset_release_id", "sidecar_asset_release_id"):
        if facts[name] != facts["draft_release_id"]:
            raise Refused(f"{name} is {facts[name]}, not the draft release "
                          f"{facts['draft_release_id']}; the asset is attached to another release")

    # The draft must hold exactly the two distribution assets at the moment this
    # document is generated. An extra asset would be published by the same
    # `publish` call and would never appear in any inventory this file records.
    names = facts["draft_asset_names_before_attestation"]
    ids = facts["draft_asset_ids_before_attestation"]
    count = facts["draft_asset_count_before_attestation"]
    if count != 2:
        raise Refused(f"draft_asset_count_before_attestation must be 2 before the attestation is "
                      f"uploaded, got {count}")
    if len(names) != count or len(ids) != count:
        raise Refused(f"the pre-attestation inventory lists {len(names)} name(s) and {len(ids)} "
                      f"id(s) but declares {count}")
    if len(set(names)) != len(names):
        raise Refused(f"the pre-attestation inventory has a duplicate asset name: {names}")
    if len(set(ids)) != len(ids):
        raise Refused(f"the pre-attestation inventory has a duplicate asset id: {ids}")
    if names != PRE_ATTESTATION_ASSET_NAMES:
        raise Refused(f"the pre-attestation inventory must be exactly {PRE_ATTESTATION_ASSET_NAMES} "
                      f"in that order, got {names}")
    if set(ids) != {facts["zip_asset_id"], facts["sidecar_asset_id"]}:
        raise Refused(f"the pre-attestation inventory ids {sorted(ids)} are not the ZIP and "
                      f"sidecar asset ids {sorted({facts['zip_asset_id'], facts['sidecar_asset_id']})}")
    if ATTESTATION_NAME in names:
        raise Refused("the attestation asset cannot be in the inventory measured before it is "
                      "uploaded; this document cannot describe its own upload")

    local_zip = record["asset"]["sha256"]
    digests = {"built": local_zip, "uploaded": facts["zip_sha256_uploaded"],
               "redownloaded": facts["zip_sha256_redownloaded"]}
    if len(set(digests.values())) != 1:
        raise Refused(f"the ZIP digest differs between build, upload and re-download: {digests}")
    if record["sidecar"]["sha256"] != facts["sidecar_sha256_redownloaded"]:
        raise Refused("the sidecar digest changed between build and re-download")
    if not facts["sidecar_check_passed"]:
        raise Refused("sidecar_check_passed is false; the downloaded ZIP did not match its checksum")

    # The sidecar is small enough to rebuild from first principles, so its
    # digest and size are checked against the bytes they must contain rather
    # than merely against each other.
    canonical_sidecar = f"{local_zip}  {ZIP_NAME}\n".encode()
    if hashlib.sha256(canonical_sidecar).hexdigest() != record["sidecar"]["sha256"]:
        raise Refused("the sidecar digest does not match the canonical "
                      "'<zip-sha256>  <zip-name>\\n' bytes for this ZIP")
    if len(canonical_sidecar) != record["sidecar"]["size"]:
        raise Refused(f"the sidecar size {record['sidecar']['size']} does not match the canonical "
                      f"{len(canonical_sidecar)} bytes")

    # fixed history
    for name, expected in (("v1_0_0_tag_target", V1_0_0_TARGET),
                           ("v1_0_1_tag_target", V1_0_1_TARGET),
                           ("audit_branch_target", AUDIT_BRANCH_TARGET)):
        if facts[name] != expected:
            raise Refused(f"{name} must be {expected}, got {facts[name]}")
    for flag in ("v1_0_0_assets_unchanged", "v1_0_1_assets_unchanged", "audit_branch_retained"):
        if not facts[flag]:
            raise Refused(f"{flag} is false; this release must not disturb existing releases "
                          "or branches")


def check_no_secrets_or_placeholders(*documents) -> None:
    for document in documents:
        blob = json.dumps(document, sort_keys=True)
        scannable = blob
        for allowed in ALLOWED_REDACTIONS:
            scannable = scannable.replace(allowed, "")
        placeholder = PLACEHOLDER_WORD.search(scannable) or PLACEHOLDER_SLOT.search(scannable)
        if placeholder:
            raise Refused(f"input contains a placeholder: {placeholder.group(0)!r}")
        if SECRET.search(blob):
            raise Refused("input appears to contain a credential or authorization header")
        for name, value in document.items():
            if isinstance(value, str) and value.startswith("/") and value != os.devnull:
                raise Refused(f"{name} looks like an absolute path: {value!r}")
            if isinstance(value, str) and re.search(r"/Users/|/home/|C:\\\\", value):
                raise Refused(f"{name} contains a local filesystem path")


def canonical_record_bytes(record: dict) -> bytes:
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render(facts: dict, record: dict, record_digest: str) -> dict:
    return {
        "schema": SCHEMA,
        "repository": REPOSITORY,
        "release_version": VERSION,
        "release_tag": TAG,
        "status": STATUS,
        "generated_at_utc": facts["generated_at_utc"],
        "authority_note": (
            "GitHub's immutable release protects the tag and the release assets, not the release "
            "title or notes, which remain editable after publication. This document is therefore "
            "an asset rather than release-body text. Its status describes the distribution assets "
            "as verified before this file itself is uploaded; its own asset id, its own digest, "
            "the re-download of this file and the post-publication immutable read-back are "
            "carried by GitHub's generated release attestation and by the external execution "
            "evidence, because a file cannot describe its own upload."),
        "release_commit": {
            "tag_target": facts["tag_target"],
            "merge_commit": facts["merge_commit"],
            "merge_tree": facts["merge_tree"],
            "first_parent": facts["merge_parent_base"],
            "second_parent": facts["merge_parent_release_branch"],
        },
        "post_merge_ci": {
            "smoke_test": {"run_id": facts["smoke_test_run_id"],
                           "workflow": facts["smoke_test_workflow_name"],
                           "event": facts["smoke_test_event"],
                           "head_branch": facts["smoke_test_head_branch"],
                           "head_sha": facts["smoke_test_head_sha"],
                           "conclusion": facts["smoke_test_conclusion"],
                           "run_attempt": facts["smoke_test_run_attempt"]},
            "full_certificate_replay": {"run_id": facts["full_replay_run_id"],
                                        "workflow": facts["full_replay_workflow_name"],
                                        "event": facts["full_replay_event"],
                                        "head_branch": facts["full_replay_head_branch"],
                                        "head_sha": facts["full_replay_head_sha"],
                                        "conclusion": facts["full_replay_conclusion"],
                                        "run_attempt": facts["full_replay_run_attempt"]},
            "replay_artifact": {"id": facts["replay_artifact_id"],
                                "name": facts["replay_artifact_name"],
                                "run_id": facts["replay_artifact_run_id"],
                                "expired": facts["replay_artifact_expired"],
                                "sha256": facts["replay_artifact_sha256"],
                                "size": facts["replay_artifact_size"]},
        },
        "replay_validation": {
            "records_checked": facts["validator_records_checked"],
            "script_hashes_verified": facts["validator_script_hashes_verified"],
            "proof_output_verified": facts["validator_proof_output_verified"],
            "source_commit_verified": facts["validator_source_commit_verified"],
            "source_clean_verified": facts["validator_source_clean_verified"],
            "problems": facts["validator_problems"],
            "exit_code": facts["validator_exit_code"],
        },
        "canonical_assets": {
            "builder_script": record["builder_script"],
            "builder_script_blob_oid": record["builder_script_blob_oid"],
            "builder_script_sha256": record["builder_script_executed_sha256"],
            "builder_script_matches_target": record["builder_script_matches_target"],
            "expected_asset_sha256": record["expected_asset_sha256"],
            "build_record_sha256": record_digest,
            "build_record_canonicalisation": CANONICALISATION,
            "build_record": record,
            "distribution": [
                {"name": ZIP_NAME, "asset_id": facts["zip_asset_id"],
                 "sha256": record["asset"]["sha256"], "size": record["asset"]["size"]},
                {"name": SIDECAR_NAME, "asset_id": facts["sidecar_asset_id"],
                 "sha256": record["sidecar"]["sha256"], "size": record["sidecar"]["size"]},
            ],
            "auxiliary_integrity": [{"name": ATTESTATION_NAME, "note": "this document"}],
        },
        "draft_asset_verification": {
            "draft_release_id": facts["draft_release_id"],
            "draft_release_tag_name": facts["draft_release_tag_name"],
            "draft_release_is_draft": facts["draft_release_is_draft"],
            "asset_inventory_before_this_upload": {
                "count": facts["draft_asset_count_before_attestation"],
                "names": facts["draft_asset_names_before_attestation"],
                "ids": facts["draft_asset_ids_before_attestation"],
                "note": ("Measured on the draft Release immediately before this document was "
                         "uploaded, which is why this document is not in it. The inventory after "
                         "the upload must be exactly these two plus this file, and that check "
                         "belongs to the external execution evidence and to GitHub's generated "
                         "release attestation, because a file cannot describe its own upload."),
            },
            "zip_asset_release_id": facts["zip_asset_release_id"],
            "sidecar_asset_release_id": facts["sidecar_asset_release_id"],
            "zip_sha256_uploaded": facts["zip_sha256_uploaded"],
            "zip_sha256_redownloaded": facts["zip_sha256_redownloaded"],
            "sidecar_sha256_redownloaded": facts["sidecar_sha256_redownloaded"],
            "sidecar_check_passed": facts["sidecar_check_passed"],
        },
        "unchanged_by_this_release": {
            "v1_0_0_tag_target": facts["v1_0_0_tag_target"],
            "v1_0_1_tag_target": facts["v1_0_1_tag_target"],
            "v1_0_0_assets_unchanged": facts["v1_0_0_assets_unchanged"],
            "v1_0_1_assets_unchanged": facts["v1_0_1_assets_unchanged"],
            "audit_branch_retained": facts["audit_branch_retained"],
            "audit_branch_target": facts["audit_branch_target"],
        },
        "mathematical_delta_from_v1_0_1": {
            "fixed_configurations_changed": False,
            "certified_lower_bounds_changed": False,
            "certifier_sources_changed": False,
            "witness_points_changed": False,
            "historical_replay_evidence_changed": False,
            "upper_witness_decimal_corrections": 18,
            "interval_width_corrections": 18,
            "provenance_text_corrections": 2,
        },
    }


def check_output_location(output: Path, *inputs: Path) -> None:
    for source in inputs:
        if output.resolve() == source.resolve():
            raise Refused("--output must not be the same file as an input")
    if output.exists():
        raise Refused(f"--output {output} already exists")
    repository = Path(__file__).resolve().parents[1]
    resolved = output.resolve()
    if resolved == repository or repository in resolved.parents:
        raise Refused(f"--output {output} is inside the repository. The attestation is a release "
                      "asset, not a tracked file.")
    if not resolved.parent.is_dir():
        raise Refused(f"--output parent directory does not exist: {resolved.parent}")


def observe_output(output: Path):
    """Does the asset exist? True, False, or None when the check itself failed."""
    try:
        return output.exists()
    except BaseException:  # noqa: BLE001 - an unknown is not a denial
        return None


def fsync_directory(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def report_unexpected_outcome(output: Path, cause: BaseException) -> int:
    """Classify an unexpected failure in `main` by looking at the asset path.

    An interruption delivered after `write_atomically()` returned -- on the
    success report, or on the return itself -- is outside every handler inside
    it. Never raises.
    """
    exists = observe_output(output)
    try:
        reason = f"{type(cause).__name__}: {cause}"
    except BaseException:  # noqa: BLE001
        reason = "an error whose description could not be rendered"
    if exists is not False:
        certainty = "EXISTS" if exists else "may exist -- its existence could not be determined"
        print(f"published-durability-uncertain: interrupted after the publication transaction by "
              f"{reason}. {output.name} {certainty}. Do NOT re-run this command and do NOT upload "
              "this file automatically; check the state by hand first.", file=sys.stderr)
        return EXIT_PUBLISHED_DURABILITY_UNCERTAIN
    print(f"refused: {reason}, nothing published", file=sys.stderr)
    return EXIT_REFUSED_BEFORE_PUBLISH


def describe_published_asset(output: Path, payload: str, cause: BaseException) -> str:
    """Build the exit-3 sentence for the attestation. Never raises.

    The read-back is best effort: three states are distinguished, and "could not
    be verified" is not the same claim as "differs" or "absent".
    """
    size = None
    verification = "could NOT be verified because the read-back itself failed"
    try:
        written = output.read_bytes()
        size = len(written)
        verification = ("byte-identical to what was generated"
                        if written == payload.encode("utf-8")
                        else "DIFFERENT from what was generated")
    except BaseException:  # noqa: BLE001 - the message must exist regardless
        try:
            size = output.stat().st_size
        except BaseException:  # noqa: BLE001
            size = None
    try:
        reason = f"{type(cause).__name__}: {cause}"
    except BaseException:  # noqa: BLE001
        reason = "an error whose description could not be rendered"
    measured = f"{size} bytes" if size is not None else "size unavailable"
    return (f"os.replace succeeded, so {output.name} EXISTS ({measured}, {verification}). A step "
            f"after the publication commit point then failed: {reason}. Whether the directory "
            "entry survives a power loss is unknown. Do NOT re-run this command and do NOT upload "
            "this file automatically; check the state by hand first.")


def write_atomically(output: Path, payload: str) -> None:
    """Write through a sibling temp file and one rename.

    An earlier version wrote straight to the destination, so a failure part way
    through left a truncated file sitting under the asset's name -- measured at
    100 bytes, not valid JSON. ``os.replace`` is the publication commit point:
    once it returns, the file exists, and a later failure is a durability
    question rather than an absence.
    """
    handle, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=str(output.parent))
    temporary = Path(temporary_name)
    committed = False
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # One transaction, from the syscall to the successful return. An earlier
        # version guarded only the `os.replace` call, which left the very next
        # line -- the one recording that the replace happened -- outside every
        # handler: an interruption there produced exit 2 and "nothing published"
        # over a complete asset. Measured with KeyboardInterrupt, SystemExit and
        # a custom BaseException.
        try:
            os.replace(temporary, output)
            committed = True
            temporary = None
            fsync_directory(output.parent)
            return
        except BaseException as error:  # noqa: BLE001 - classified, never swallowed
            exists = observe_output(output)
            # `False` is the only answer that permits claiming absence.
            if exists is not False:
                committed = True
                temporary = None
                raise PublishedDurabilityUncertain(
                    describe_published_asset(output, payload, error)) from error
            raise
    finally:
        if not committed and temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except BaseException:  # noqa: BLE001 - cleanup must not mask the cause
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the publication-attestation release asset.")
    parser.add_argument("--measured-release-facts", required=True,
                        help="JSON file of facts measured from GitHub and CI")
    parser.add_argument("--build-record", required=True,
                        help="build-record.json produced by build_release_assets.py")
    parser.add_argument("--output", required=True,
                        help="path for the attestation asset, outside the repository")
    arguments = parser.parse_args(argv)

    facts_path = Path(arguments.measured_release_facts)
    record_path = Path(arguments.build_record)
    output_path = Path(arguments.output)
    payload = ""
    try:
        check_output_location(output_path, facts_path, record_path)
        facts = load_json(facts_path, "--measured-release-facts")
        record = load_json(record_path, "--build-record")
        raw_record = record_path.read_bytes()
        canonical = canonical_record_bytes(record)
        if canonical != raw_record:
            raise Refused(
                "the build record file is not in its canonical spelling, so the digest published "
                "here would not be recomputable from the embedded object. Expected "
                f"{len(canonical)} bytes of json.dumps(indent=2, sort_keys=True) plus a newline, "
                f"got {len(raw_record)}.")
        record_digest = hashlib.sha256(canonical).hexdigest()
        check_facts(facts)
        check_build_record(record)
        check_cross_field(facts, record)
        check_no_secrets_or_placeholders(facts, record)
        document = render(facts, record, record_digest)
        payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        write_atomically(output_path, payload)
        # Inside the transaction: an interruption on the success report, or on
        # the return, previously escaped as a traceback beside a complete asset.
        print(f"wrote {output_path.name} bytes={len(payload.encode())} status={STATUS}")
        return EXIT_OK
    except PublishedDurabilityUncertain as state:
        print(f"published-durability-uncertain: {state}", file=sys.stderr)
        return EXIT_PUBLISHED_DURABILITY_UNCERTAIN
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return EXIT_REFUSED_BEFORE_PUBLISH
    except BaseException as unexpected:  # noqa: BLE001 - classified by the filesystem
        return report_unexpected_outcome(output_path, unexpected)


if __name__ == "__main__":
    raise SystemExit(main())
