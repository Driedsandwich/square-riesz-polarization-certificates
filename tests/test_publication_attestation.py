"""Tests for the publication-attestation generator.

The generator stands between a measured release and an asset that becomes
immutable, so the rejection paths matter more than the happy one. Each test
starts from a pair of fixtures that pass together and breaks exactly one thing,
which is what makes a refusal attributable to that change rather than to a
generally malformed fixture.

Many cases here are counterexamples an earlier version accepted: an impossible
calendar date, validator counters of 1/1/1, a second CI attempt, a builder
command that had nothing to do with the release, a build whose builder was never
bound to the target commit, a tagged build with no expected digest, and a
fixture record in which ``check_release.py`` had never run. The record is now
checked as a whole document -- every field named, unknown fields refused -- and
embedded in the output so a reader can recompute the digest that is published.

No test touches the network, GitHub, or the repository's own files.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import REPO_ROOT, SCRIPTS  # noqa: E402

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_publication_attestation as attestation  # noqa: E402

GENERATOR = SCRIPTS / "build_publication_attestation.py"

MERGE = "a1" * 20
TREE = "b2" * 20
PARENT_BASE = attestation.MERGE_FIRST_PARENT
PARENT_BRANCH = "d4" * 20
BLOB_OID = "e5" * 20
ZIP_DIGEST = "12" * 32
ARTIFACT_DIGEST = "34" * 32
BUILDER_SHA256 = "56" * 32
SIDECAR_BYTES = f"{ZIP_DIGEST}  {attestation.ZIP_NAME}\n".encode()
SIDECAR_DIGEST = hashlib.sha256(SIDECAR_BYTES).hexdigest()
FILE_COUNT = 606

ARCHIVE_COMMAND = [*attestation.EXPECTED_ARCHIVE_COMMAND, MERGE]


def build_record() -> dict:
    """A record shaped like one build_release_assets.py actually writes."""
    return {
        "schema": attestation.BUILD_RECORD_SCHEMA,
        "generated_at_utc": "2026-08-07T11:59:00Z",
        "project": attestation.PROJECT,
        "version": attestation.VERSION,
        "head_commit": MERGE,
        "target_commit": MERGE,
        "target_tree": TREE,
        "require_tag": attestation.TAG,
        "tag_ref": attestation.TAG_REF,
        "tag_target": MERGE,
        "committed_version": attestation.VERSION,
        "builder_script": "scripts/build_release_assets.py",
        "builder_script_blob_oid": BLOB_OID,
        "builder_script_mode": "100644",
        "builder_script_target_sha256": BUILDER_SHA256,
        "builder_script_executed_sha256": BUILDER_SHA256,
        "builder_script_matches_target": True,
        "archive_command": list(ARCHIVE_COMMAND),
        "repository": "<REPOSITORY>",
        "output_zip": "<OUTPUT_ZIP>",
        "generation_semantics": (
            "git archive --format=zip -9 "
            "--prefix=square-riesz-polarization-certificates-v1.0.2/ <target>"),
        "environment": {"timezone": "UTC", "locale": "C",
                        "inherited": ["PATH", "HOME"],
                        "fixed": {"TZ": "UTC", "LC_ALL": "C"},
                        "dropped": ["GIT_DIR", "GIT_WORK_TREE", "GIT_NAMESPACE"]},
        "git_version": "git version 2.51.0",
        "python_version": "3.13.14",
        "platform": "macOS-26.5.2-arm64",
        "asset": {"name": attestation.ZIP_NAME, "sha256": ZIP_DIGEST, "size": 700000,
                  "entry_count": 760, "file_count": FILE_COUNT, "uncompressed_size": 1800000,
                  "archive_comment": MERGE},
        "sidecar": {"name": attestation.SIDECAR_NAME, "sha256": SIDECAR_DIGEST,
                    "size": len(SIDECAR_BYTES)},
        "raw_tree_comparison": {"tree_paths": FILE_COUNT, "compared_paths": FILE_COUNT,
                                "executable_paths": 0},
        "archive_self_verification": {
            "ran": {"verify_manifest.py": {"exit_code": 0, "stdout_tail": ["manifest ok"]},
                    "check_release.py": {"exit_code": 0, "stdout_tail": ["issues=0"]}},
            "not_present_in_archive": []},
        "expected_asset_sha256": ZIP_DIGEST,
        "output_inventory": attestation.OUTPUT_INVENTORY,
        "determinism_note": "Byte-identical for repeated builds of the same commit under TZ=UTC.",
        "github_writes": 0,
    }


def measured() -> dict:
    """Facts that only GitHub and CI can supply."""
    return {
        "generated_at_utc": "2026-08-07T12:00:00Z",
        "repository_full_name": attestation.REPOSITORY,
        "draft_release_id": 400000001,
        "draft_release_tag_name": attestation.TAG,
        "draft_release_is_draft": True,
        "tag_target": MERGE,
        "merge_commit": MERGE,
        "merge_tree": TREE,
        "merge_parent_base": PARENT_BASE,
        "merge_parent_release_branch": PARENT_BRANCH,
        "smoke_test_run_id": 31000000001,
        "smoke_test_workflow_name": attestation.SMOKE_WORKFLOW,
        "smoke_test_event": "push",
        "smoke_test_head_branch": "main",
        "smoke_test_head_sha": MERGE,
        "smoke_test_conclusion": "success",
        "smoke_test_run_attempt": 1,
        "full_replay_run_id": 31000000002,
        "full_replay_workflow_name": attestation.REPLAY_WORKFLOW,
        "full_replay_event": "push",
        "full_replay_head_branch": "main",
        "full_replay_head_sha": MERGE,
        "full_replay_conclusion": "success",
        "full_replay_run_attempt": 1,
        "replay_artifact_id": 9000000001,
        "replay_artifact_name": attestation.REPLAY_ARTIFACT_NAME,
        "replay_artifact_run_id": 31000000002,
        "replay_artifact_expired": False,
        "replay_artifact_sha256": ARTIFACT_DIGEST,
        "replay_artifact_size": 113111,
        "validator_records_checked": 88,
        "validator_script_hashes_verified": 88,
        "validator_proof_output_verified": 88,
        "validator_source_commit_verified": 1,
        "validator_source_clean_verified": 1,
        "validator_problems": 0,
        "validator_exit_code": 0,
        "draft_asset_count_before_attestation": 2,
        "draft_asset_names_before_attestation": list(attestation.PRE_ATTESTATION_ASSET_NAMES),
        "draft_asset_ids_before_attestation": [500000001, 500000002],
        "zip_asset_id": 500000001,
        "zip_asset_name": attestation.ZIP_NAME,
        "zip_asset_release_id": 400000001,
        "zip_sha256_uploaded": ZIP_DIGEST,
        "zip_sha256_redownloaded": ZIP_DIGEST,
        "sidecar_asset_id": 500000002,
        "sidecar_asset_name": attestation.SIDECAR_NAME,
        "sidecar_asset_release_id": 400000001,
        "sidecar_sha256_redownloaded": SIDECAR_DIGEST,
        "sidecar_check_passed": True,
        "v1_0_0_tag_target": attestation.V1_0_0_TARGET,
        "v1_0_1_tag_target": attestation.V1_0_1_TARGET,
        "v1_0_0_assets_unchanged": True,
        "v1_0_1_assets_unchanged": True,
        "audit_branch_retained": True,
        "audit_branch_target": attestation.AUDIT_BRANCH_TARGET,
    }


def canonical(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


class GeneratorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="attestation-test-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def write_inputs(self, facts=None, record=None, raw_facts=None, raw_record=None):
        facts_path = self.scratch / "facts.json"
        facts_path.write_text(
            raw_facts if raw_facts is not None
            else json.dumps(facts if facts is not None else measured(), indent=2),
            encoding="utf-8")
        record_path = self.scratch / "record.json"
        record_path.write_text(
            raw_record if raw_record is not None
            else canonical(record if record is not None else build_record()),
            encoding="utf-8")
        return facts_path, record_path

    def run_generator(self, facts=None, record=None, output_name="out.json",
                      raw_facts=None, raw_record=None, output=None):
        facts_path, record_path = self.write_inputs(facts, record, raw_facts, raw_record)
        target = output or (self.scratch / output_name)
        completed = subprocess.run(
            [sys.executable, "-B", str(GENERATOR),
             "--measured-release-facts", str(facts_path),
             "--build-record", str(record_path), "--output", str(target)],
            capture_output=True, text=True)
        return completed, target

    def assert_refused(self, completed, fragment, output: Path) -> None:
        self.assertEqual(completed.returncode, attestation.EXIT_REFUSED, completed.stderr)
        self.assertIn(fragment, completed.stderr)
        self.assertFalse(output.exists(), "a refusal must not write the asset")


class ValidInput(GeneratorCase):
    def test_a_complete_pair_is_accepted(self) -> None:
        completed, output = self.run_generator()
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)
        self.assertTrue(output.is_file())

    def test_output_is_canonical_json(self) -> None:
        _c, output = self.run_generator()
        text = output.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\r", text)
        document = json.loads(text)
        self.assertEqual(text, json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    def test_two_generations_are_byte_identical(self) -> None:
        _c1, first = self.run_generator(output_name="first.json")
        _c2, second = self.run_generator(output_name="second.json")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_status_is_true_before_this_asset_is_uploaded(self) -> None:
        _c, output = self.run_generator()
        document = json.loads(output.read_text())
        self.assertEqual(document["status"], "PRE_PUBLICATION_DISTRIBUTION_ASSETS_VERIFIED")
        self.assertNotIn("READY_TO_PUBLISH", document["status"])

    def test_document_takes_builder_facts_from_the_record(self) -> None:
        _c, output = self.run_generator()
        assets = json.loads(output.read_text())["canonical_assets"]
        self.assertEqual(assets["builder_script_blob_oid"], BLOB_OID)
        self.assertEqual(assets["builder_script_sha256"], BUILDER_SHA256)
        self.assertTrue(assets["builder_script_matches_target"])

    def test_document_does_not_describe_itself(self) -> None:
        _c, output = self.run_generator()
        blob = output.read_text()
        for absent in ("attestation_asset_id", "attestation_sha256", "immutable_read_back"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, blob)


class EmbeddedBuildRecord(GeneratorCase):
    """A digest without its preimage is not evidence.

    The earlier asset published ``build_record_sha256`` while the record itself
    stayed on the build machine, so a reader of the release could not check what
    the digest was of.
    """

    def test_the_record_is_embedded_in_full(self) -> None:
        _c, output = self.run_generator()
        embedded = json.loads(output.read_text())["canonical_assets"]["build_record"]
        self.assertEqual(embedded, build_record())

    def test_the_published_digest_is_recomputable_from_the_embedded_object(self) -> None:
        _c, output = self.run_generator()
        assets = json.loads(output.read_text())["canonical_assets"]
        recomputed = hashlib.sha256(canonical(assets["build_record"]).encode("utf-8")).hexdigest()
        self.assertEqual(assets["build_record_sha256"], recomputed)

    def test_the_published_digest_is_also_the_digest_of_the_record_file(self) -> None:
        facts_path, record_path = self.write_inputs()
        output = self.scratch / "out.json"
        completed = subprocess.run(
            [sys.executable, "-B", str(GENERATOR), "--measured-release-facts", str(facts_path),
             "--build-record", str(record_path), "--output", str(output)],
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)
        assets = json.loads(output.read_text())["canonical_assets"]
        self.assertEqual(assets["build_record_sha256"],
                         hashlib.sha256(record_path.read_bytes()).hexdigest())

    def test_the_recomputation_recipe_is_stated(self) -> None:
        _c, output = self.run_generator()
        recipe = json.loads(output.read_text())["canonical_assets"]["build_record_canonicalisation"]
        self.assertIn("sort_keys=True", recipe)
        self.assertIn("indent=2", recipe)

    def test_a_non_canonical_record_file_is_refused(self) -> None:
        """Otherwise the published digest would not match the embedded object."""
        completed, output = self.run_generator(
            raw_record=json.dumps(build_record(), indent=4, sort_keys=True) + "\n")
        self.assert_refused(completed, "not in its canonical spelling", output)

    def test_a_record_without_a_trailing_newline_is_refused(self) -> None:
        completed, output = self.run_generator(
            raw_record=json.dumps(build_record(), indent=2, sort_keys=True))
        self.assert_refused(completed, "not in its canonical spelling", output)

    def test_the_canonical_spelling_is_accepted(self) -> None:
        """Control: the refusal is about the spelling, not about the check existing."""
        completed, _o = self.run_generator(raw_record=canonical(build_record()))
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)

    def test_the_builder_writes_that_exact_spelling(self) -> None:
        """The two scripts must agree on what canonical means."""
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import build_release_assets as builder
        self.assertEqual(builder.canonical_record_bytes(build_record()),
                         canonical(build_record()).encode("utf-8"))


class RecordSchemaExactness(GeneratorCase):
    """The record is validated as a whole document, not field by remembered field."""

    def test_an_extra_top_level_field_is_refused(self) -> None:
        record = build_record(); record["surprise"] = "x"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "unknown field(s) ['surprise']", output)

    def test_a_missing_top_level_field_is_refused(self) -> None:
        record = build_record(); del record["git_version"]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "missing ['git_version']", output)

    def test_an_extra_nested_field_is_refused(self) -> None:
        record = build_record(); record["asset"]["extra"] = 1
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "build record asset has unknown field(s)", output)

    def test_a_missing_nested_field_is_refused(self) -> None:
        record = build_record(); del record["asset"]["entry_count"]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "build record asset is missing", output)

    def test_a_boolean_in_a_count_slot_is_refused(self) -> None:
        record = build_record(); record["asset"]["size"] = True
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must be an integer", output)

    def test_a_float_count_is_refused(self) -> None:
        record = build_record(); record["asset"]["size"] = 700000.5
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "is a float", output)

    def test_a_non_finite_number_is_refused(self) -> None:
        """1e999 parses to inf without ever being spelled Infinity."""
        raw = canonical(build_record()).replace('"size": 700000', '"size": 1e999')
        completed, output = self.run_generator(raw_record=raw)
        self.assert_refused(completed, "non-finite", output)

    def test_the_literal_nan_constant_is_refused(self) -> None:
        raw = canonical(build_record()).replace('"size": 700000', '"size": NaN')
        completed, output = self.run_generator(raw_record=raw)
        self.assert_refused(completed, "non-JSON constant", output)

    def test_an_unknown_self_check_is_refused(self) -> None:
        record = build_record()
        record["archive_self_verification"]["ran"]["surprise.py"] = {"exit_code": 0,
                                                                    "stdout_tail": []}
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must show", output)

    def test_an_extra_field_inside_a_self_check_is_refused(self) -> None:
        record = build_record()
        record["archive_self_verification"]["ran"]["check_release.py"]["duration"] = 3
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "has unknown field(s) ['duration']", output)

    def test_a_null_field_is_refused(self) -> None:
        record = build_record(); record["git_version"] = None
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "is null", output)

    def test_an_empty_text_field_is_refused(self) -> None:
        record = build_record(); record["platform"] = ""
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must not be empty", output)

    def test_the_unmodified_record_is_accepted(self) -> None:
        """Control: the schema is not refusing everything."""
        completed, _o = self.run_generator()
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)


class BuilderSourceBinding(GeneratorCase):
    """Reproduced: a build whose builder was not the blob in the target commit."""

    def test_a_record_that_admits_the_mismatch_is_refused(self) -> None:
        record = build_record(); record["builder_script_matches_target"] = False
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "did not match the builder blob", output)

    def test_differing_target_and_executed_digests_are_refused(self) -> None:
        record = build_record(); record["builder_script_executed_sha256"] = "7" * 64
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "target and executed builder digests differ", output)

    def test_a_head_other_than_the_target_is_refused(self) -> None:
        record = build_record(); record["head_commit"] = "9" * 40
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "did not run from a checkout", output)

    def test_a_builder_at_another_path_is_refused(self) -> None:
        record = build_record(); record["builder_script"] = "tools/other.py"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "builder_script must be", output)

    def test_a_symlink_mode_builder_is_refused(self) -> None:
        record = build_record(); record["builder_script_mode"] = "120000"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "builder_script_mode", output)

    def test_a_hand_supplied_blob_oid_is_refused(self) -> None:
        """The value now comes from the record; typing it into the facts is an error."""
        facts = measured(); facts["builder_script_blob_oid"] = BLOB_OID
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must not be supplied", output)

    def test_a_file_digest_pasted_into_the_blob_oid_slot_is_refused(self) -> None:
        record = build_record(); record["builder_script_blob_oid"] = BUILDER_SHA256
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "40-character lowercase hex", output)

    def test_a_blob_oid_pasted_into_a_digest_slot_is_refused(self) -> None:
        record = build_record(); record["builder_script_executed_sha256"] = BLOB_OID
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "64-character lowercase hex", output)


class ExpectedDigestGate(GeneratorCase):
    """Reproduced: a tagged build with no --expect-asset-sha256 was accepted."""

    def test_a_null_expected_digest_is_refused(self) -> None:
        record = build_record(); record["expected_asset_sha256"] = None
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "is null", output)

    def test_an_expected_digest_that_is_not_the_produced_one_is_refused(self) -> None:
        record = build_record(); record["expected_asset_sha256"] = "9" * 64
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "does not equal the digest it produced", output)

    def test_the_matching_gate_is_accepted(self) -> None:
        """Control."""
        completed, _o = self.run_generator()
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)

    def test_the_gate_is_republished(self) -> None:
        _c, output = self.run_generator()
        assets = json.loads(output.read_text())["canonical_assets"]
        self.assertEqual(assets["expected_asset_sha256"], ZIP_DIGEST)


class ArchiveSelfChecks(GeneratorCase):
    """Reproduced: a fixture record in which check_release.py had never run."""

    def test_a_missing_self_check_is_refused(self) -> None:
        record = build_record()
        record["archive_self_verification"]["not_present_in_archive"] = ["check_release.py"]
        del record["archive_self_verification"]["ran"]["check_release.py"]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must contain every self-check", output)

    def test_a_self_check_absent_from_ran_is_refused(self) -> None:
        record = build_record()
        del record["archive_self_verification"]["ran"]["check_release.py"]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must show", output)

    def test_a_failing_release_check_is_refused(self) -> None:
        record = build_record()
        record["archive_self_verification"]["ran"]["check_release.py"]["exit_code"] = 1
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "check_release.py exited 1", output)

    def test_a_failing_manifest_check_is_refused(self) -> None:
        record = build_record()
        record["archive_self_verification"]["ran"]["verify_manifest.py"]["exit_code"] = 1
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "verify_manifest.py exited 1", output)

    def test_both_checks_passing_is_accepted(self) -> None:
        """Control."""
        completed, _o = self.run_generator()
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)


class ArchiveCommandExactness(GeneratorCase):
    def test_every_element_is_load_bearing(self) -> None:
        for index in range(len(ARCHIVE_COMMAND)):
            with self.subTest(index=index, element=ARCHIVE_COMMAND[index]):
                record = build_record()
                record["archive_command"][index] = "tampered"
                completed, output = self.run_generator(record=record,
                                                       output_name=f"o{index}.json")
                self.assert_refused(completed, "not the exact expected sequence", output)

    def test_an_extra_element_is_refused(self) -> None:
        record = build_record(); record["archive_command"].append("--extra")
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "not the exact expected sequence", output)

    def test_a_missing_element_is_refused(self) -> None:
        record = build_record(); record["archive_command"].pop(2)
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "not the exact expected sequence", output)

    def test_a_command_that_is_not_git_archive_is_refused(self) -> None:
        record = build_record(); record["archive_command"] = ["echo", MERGE]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "not the exact expected sequence", output)

    def test_the_exact_command_is_accepted(self) -> None:
        """Control."""
        completed, _o = self.run_generator()
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)


class CountsAgree(GeneratorCase):
    def test_an_incomplete_tree_comparison_is_refused(self) -> None:
        record = build_record(); record["raw_tree_comparison"]["compared_paths"] = FILE_COUNT - 1
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must agree", output)

    def test_an_archive_holding_fewer_files_than_the_tree_is_refused(self) -> None:
        record = build_record(); record["asset"]["file_count"] = FILE_COUNT - 1
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "must agree", output)

    def test_an_archive_comment_that_is_not_the_target_is_refused(self) -> None:
        record = build_record(); record["asset"]["archive_comment"] = "9" * 40
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "archive comment is not the target commit", output)

    def test_a_wrong_output_inventory_is_refused(self) -> None:
        record = build_record(); record["output_inventory"] = [attestation.ZIP_NAME]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "output_inventory must be", output)


class ReleaseRelations(GeneratorCase):
    """API answers from another release or another run must not be mixable."""

    def test_another_repository_is_refused(self) -> None:
        facts = measured(); facts["repository_full_name"] = "someone/else"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "repository_full_name must be", output)

    def test_a_draft_for_another_tag_is_refused(self) -> None:
        facts = measured(); facts["draft_release_tag_name"] = "v1.0.1"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "draft_release_tag_name must be", output)

    def test_an_already_published_release_is_refused(self) -> None:
        facts = measured(); facts["draft_release_is_draft"] = False
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "still a draft", output)

    def test_a_run_from_another_workflow_is_refused(self) -> None:
        facts = measured(); facts["full_replay_workflow_name"] = "smoke-test"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "not 'full-certificate-replay'", output)

    def test_a_scheduled_run_is_refused(self) -> None:
        facts = measured(); facts["full_replay_event"] = "schedule"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "triggered by 'schedule'", output)

    def test_a_run_on_another_branch_is_refused(self) -> None:
        facts = measured(); facts["smoke_test_head_branch"] = "release/v1.0.2-prep"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "is on branch", output)

    def test_a_run_on_another_commit_is_refused(self) -> None:
        facts = measured(); facts["smoke_test_head_sha"] = "9" * 40
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "is not the merge commit", output)

    def test_an_artifact_with_another_name_is_refused(self) -> None:
        facts = measured(); facts["replay_artifact_name"] = "logs"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "replay_artifact_name must be", output)

    def test_an_artifact_from_another_run_is_refused(self) -> None:
        facts = measured(); facts["replay_artifact_run_id"] = 31000000009
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "artifact belongs to run", output)

    def test_an_expired_artifact_is_refused(self) -> None:
        facts = measured(); facts["replay_artifact_expired"] = True
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "expired artifact", output)

    def test_an_asset_under_another_name_is_refused(self) -> None:
        facts = measured(); facts["zip_asset_name"] = "bundle.zip"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "zip_asset_name must be", output)

    def test_an_asset_attached_to_another_release_is_refused(self) -> None:
        facts = measured(); facts["sidecar_asset_release_id"] = 400000009
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "attached to another release", output)

    def test_identical_run_ids_are_refused(self) -> None:
        facts = measured(); facts["full_replay_run_id"] = facts["smoke_test_run_id"]
        facts["replay_artifact_run_id"] = facts["smoke_test_run_id"]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "run ids are identical", output)

    def test_identical_asset_ids_are_refused(self) -> None:
        facts = measured(); facts["sidecar_asset_id"] = facts["zip_asset_id"]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "asset ids are identical", output)


class PreAttestationAssetInventory(GeneratorCase):
    """The draft must hold exactly the two distribution assets at generation time.

    Anything extra sitting on the draft would be frozen by the same `publish`
    call and would never appear in an inventory this document records.
    """

    def test_an_extra_asset_is_refused(self) -> None:
        facts = measured()
        facts["draft_asset_count_before_attestation"] = 3
        facts["draft_asset_names_before_attestation"] = [*attestation.PRE_ATTESTATION_ASSET_NAMES,
                                                         "notes.txt"]
        facts["draft_asset_ids_before_attestation"] = [500000001, 500000002, 500000003]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be 2 before the attestation is uploaded", output)

    def test_a_missing_asset_is_refused(self) -> None:
        facts = measured()
        facts["draft_asset_count_before_attestation"] = 1
        facts["draft_asset_names_before_attestation"] = [attestation.ZIP_NAME]
        facts["draft_asset_ids_before_attestation"] = [500000001]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be 2 before the attestation is uploaded", output)

    def test_a_count_that_disagrees_with_the_lists_is_refused(self) -> None:
        facts = measured()
        facts["draft_asset_names_before_attestation"] = [attestation.ZIP_NAME]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "but declares 2", output)

    def test_a_duplicate_asset_name_is_refused(self) -> None:
        facts = measured()
        facts["draft_asset_names_before_attestation"] = [attestation.ZIP_NAME,
                                                         attestation.ZIP_NAME]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "duplicate asset name", output)

    def test_a_duplicate_asset_id_is_refused(self) -> None:
        facts = measured()
        facts["draft_asset_ids_before_attestation"] = [500000001, 500000001]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "duplicate asset id", output)

    def test_a_foreign_asset_name_is_refused(self) -> None:
        facts = measured()
        facts["draft_asset_names_before_attestation"] = [attestation.ZIP_NAME, "other.sha256"]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be exactly", output)

    def test_ids_that_are_not_the_two_asset_ids_are_refused(self) -> None:
        facts = measured()
        facts["draft_asset_ids_before_attestation"] = [500000001, 500000009]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "are not the ZIP and", output)

    def test_the_attestation_cannot_be_in_its_own_pre_upload_inventory(self) -> None:
        facts = measured()
        facts["draft_asset_count_before_attestation"] = 2
        facts["draft_asset_names_before_attestation"] = sorted(
            [attestation.ZIP_NAME, attestation.ATTESTATION_NAME])
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be exactly", output)

    def test_booleans_are_not_asset_ids(self) -> None:
        facts = measured()
        facts["draft_asset_ids_before_attestation"] = [True, False]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be a list of integers", output)

    def test_the_valid_two_asset_inventory_is_accepted(self) -> None:
        """Control."""
        completed, _o = self.run_generator()
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)

    def test_the_inventory_is_republished(self) -> None:
        _c, output = self.run_generator()
        block = json.loads(output.read_text())["draft_asset_verification"][
            "asset_inventory_before_this_upload"]
        self.assertEqual(block["count"], 2)
        self.assertEqual(block["names"], list(attestation.PRE_ATTESTATION_ASSET_NAMES))
        self.assertNotIn(attestation.ATTESTATION_NAME, block["names"])


class TimestampRefusals(GeneratorCase):
    def test_impossible_calendar_date_is_refused(self) -> None:
        """Measured on an earlier generator: 2026-99-99T99:99:99Z was accepted."""
        facts = measured(); facts["generated_at_utc"] = "2026-99-99T99:99:99Z"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "not a real UTC timestamp", output)

    def test_february_thirtieth_is_refused(self) -> None:
        facts = measured(); facts["generated_at_utc"] = "2026-02-30T00:00:00Z"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "not a real UTC timestamp", output)

    def test_hour_twentyfour_is_refused(self) -> None:
        facts = measured(); facts["generated_at_utc"] = "2026-08-07T24:00:00Z"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "not a real UTC timestamp", output)

    def test_offset_timestamp_is_refused(self) -> None:
        facts = measured(); facts["generated_at_utc"] = "2026-08-07T12:00:00+09:00"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "not a real UTC timestamp", output)

    def test_an_impossible_build_timestamp_is_refused(self) -> None:
        record = build_record(); record["generated_at_utc"] = "2026-02-30T00:00:00Z"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "not a real UTC timestamp", output)

    def test_a_build_made_after_the_attestation_is_refused(self) -> None:
        record = build_record(); record["generated_at_utc"] = "2026-08-07T12:00:01Z"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "after this attestation", output)

    def test_a_build_at_the_same_second_is_accepted(self) -> None:
        """Control: the rule is ordering, not a required gap."""
        record = build_record(); record["generated_at_utc"] = "2026-08-07T12:00:00Z"
        completed, _o = self.run_generator(record=record)
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)

    def test_a_real_date_is_accepted(self) -> None:
        """Control: the parser is not rejecting every timestamp."""
        facts = measured(); facts["generated_at_utc"] = "2026-08-07T23:59:59Z"
        completed, _o = self.run_generator(facts)
        self.assertEqual(completed.returncode, attestation.EXIT_OK, completed.stderr)


class ReleaseSpecificRefusals(GeneratorCase):
    def test_validator_counters_of_one_are_refused(self) -> None:
        """Measured on an earlier generator: 1/1/1 was accepted because they only had to agree."""
        facts = measured()
        for name in ("validator_records_checked", "validator_script_hashes_verified",
                     "validator_proof_output_verified"):
            facts[name] = 1
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be exactly 88", output)

    def test_second_run_attempt_is_refused(self) -> None:
        """Measured on an earlier generator: run_attempt 2 was accepted."""
        facts = measured()
        facts["smoke_test_run_attempt"] = 2
        facts["full_replay_run_attempt"] = 2
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "a re-run means the first", output)

    def test_wrong_first_parent_is_refused(self) -> None:
        facts = measured(); facts["merge_parent_base"] = "9" * 40
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "first parent must be", output)

    def test_wrong_v1_0_1_target_is_refused(self) -> None:
        facts = measured(); facts["v1_0_1_tag_target"] = "9" * 40
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "v1_0_1_tag_target must be", output)

    def test_wrong_audit_branch_target_is_refused(self) -> None:
        facts = measured(); facts["audit_branch_target"] = "9" * 40
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "audit_branch_target must be", output)

    def test_pending_ci_is_refused(self) -> None:
        facts = measured(); facts["full_replay_conclusion"] = "in_progress"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be 'success'", output)

    def test_validator_problems_is_refused(self) -> None:
        facts = measured(); facts["validator_problems"] = 1
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "publication requires 0", output)

    def test_dirty_release_replay_is_refused(self) -> None:
        facts = measured(); facts["validator_source_clean_verified"] = 0
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "source_clean_verified must be 1", output)

    def test_tag_target_that_is_not_the_merge_commit_is_refused(self) -> None:
        facts = measured(); facts["tag_target"] = "9" * 40
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "is not the merge commit", output)

    def test_bool_as_integer_is_refused(self) -> None:
        facts = measured(); facts["validator_records_checked"] = True
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must be an integer", output)

    def test_retyped_builder_command_is_refused(self) -> None:
        """The builder fields come from the record; supplying one by hand is an error."""
        facts = measured(); facts["builder_command"] = ["echo", "not-a-builder"]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "must come from the build record", output)

    def test_unknown_fact_is_refused(self) -> None:
        facts = measured(); facts["surprise"] = "x"
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "unknown fact", output)

    def test_missing_fact_is_refused(self) -> None:
        facts = measured(); del facts["merge_tree"]
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "missing required fact", output)

    def test_duplicate_key_is_refused(self) -> None:
        raw = '{"generated_at_utc": "2026-08-07T12:00:00Z", "generated_at_utc": "2026-08-07T13:00:00Z"}'
        completed, output = self.run_generator(raw_facts=raw)
        self.assert_refused(completed, "duplicate keys", output)

    def test_record_target_that_is_not_the_merge_commit_is_refused(self) -> None:
        record = build_record()
        for field in ("target_commit", "tag_target", "head_commit"):
            record[field] = "9" * 40
        record["archive_command"][-1] = "9" * 40
        record["asset"]["archive_comment"] = "9" * 40
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "built from a different commit", output)

    def test_record_tree_mismatch_is_refused(self) -> None:
        record = build_record(); record["target_tree"] = "9" * 40
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "target tree is not the merge tree", output)

    def test_untagged_build_record_is_refused(self) -> None:
        record = build_record(); record["require_tag"] = "v9.9.9"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "require_tag must be", output)

    def test_wrong_record_schema_is_refused(self) -> None:
        record = build_record(); record["schema"] = "something.else.v1"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "build record schema must be", output)

    def test_non_utc_build_is_refused(self) -> None:
        record = build_record(); record["environment"]["timezone"] = "Pacific/Kiritimati"
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "TZ=UTC", output)

    def test_an_unpinned_timezone_in_the_fixed_block_is_refused(self) -> None:
        record = build_record(); record["environment"]["fixed"] = {"LC_ALL": "C"}
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "does not pin TZ", output)

    def test_a_routing_variable_that_was_not_dropped_is_refused(self) -> None:
        record = build_record(); record["environment"]["dropped"] = ["GIT_WORK_TREE"]
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "does not record dropping GIT_DIR", output)

    def test_uploaded_digest_differing_from_the_built_one_is_refused(self) -> None:
        facts = measured(); facts["zip_sha256_uploaded"] = "7" * 64
        completed, output = self.run_generator(facts)
        self.assert_refused(completed, "differs between build, upload and re-download", output)

    def test_reconstructed_sidecar_mismatch_is_refused(self) -> None:
        """The sidecar is rebuilt from the ZIP digest and the asset name."""
        record = build_record()
        record["sidecar"]["sha256"] = "8" * 64
        facts = measured(); facts["sidecar_sha256_redownloaded"] = "8" * 64
        completed, output = self.run_generator(facts, record)
        self.assert_refused(completed, "canonical", output)

    def test_wrong_sidecar_size_is_refused(self) -> None:
        record = build_record(); record["sidecar"]["size"] = 999
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "sidecar size", output)

    def test_github_writes_in_the_record_is_refused(self) -> None:
        record = build_record(); record["github_writes"] = 1
        completed, output = self.run_generator(record=record)
        self.assert_refused(completed, "github_writes = 0", output)


class PublicationCommitPoint(GeneratorCase):
    """os.replace is the commit point; after it the file exists."""

    def inputs(self):
        return self.write_inputs()

    def test_a_replace_failure_leaves_no_partial_asset(self) -> None:
        """Measured on an earlier generator: a 100-byte truncated file remained."""
        facts_path, record_path = self.inputs()
        output = self.scratch / "out.json"
        real_replace = attestation.os.replace

        def failing(src, dst, *a, **k):
            raise OSError("simulated replace failure")

        attestation.os.replace = failing
        try:
            code = attestation.main(["--measured-release-facts", str(facts_path),
                                     "--build-record", str(record_path), "--output", str(output)])
        finally:
            attestation.os.replace = real_replace
        self.assertEqual(code, attestation.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())
        leftovers = [p.name for p in self.scratch.iterdir() if p.name.startswith(".out.json.")]
        self.assertEqual(leftovers, [], f"temp files left behind: {leftovers}")

    def run_with_failing_directory_fsync(self, output: Path) -> int:
        facts_path, record_path = self.inputs()
        real_fsync = os.fsync

        def injected(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "injected directory fsync failure")
            return real_fsync(fd)

        os.fsync = injected
        try:
            return attestation.main(["--measured-release-facts", str(facts_path),
                                     "--build-record", str(record_path), "--output", str(output)])
        finally:
            os.fsync = real_fsync

    def test_a_failure_after_replace_reports_a_published_file(self) -> None:
        """Measured on an earlier generator: exit 2 and 'nothing published', 4626 valid bytes."""
        output = self.scratch / "out.json"
        code = self.run_with_failing_directory_fsync(output)
        self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertEqual(code, 3)
        self.assertTrue(output.is_file())

    def test_the_published_file_after_that_failure_is_valid(self) -> None:
        output = self.scratch / "out.json"
        self.run_with_failing_directory_fsync(output)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(document["status"], attestation.STATUS)
        self.assertEqual(output.read_text(encoding="utf-8"),
                         json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    def test_that_failure_leaves_no_temp_file(self) -> None:
        output = self.scratch / "out.json"
        self.run_with_failing_directory_fsync(output)
        leftovers = [p.name for p in self.scratch.iterdir() if p.name.startswith(".out.json.")]
        self.assertEqual(leftovers, [])

    def test_rerunning_after_that_failure_is_refused(self) -> None:
        output = self.scratch / "out.json"
        self.run_with_failing_directory_fsync(output)
        before = output.read_bytes()
        completed, _o = self.run_generator(output=output)
        self.assertEqual(completed.returncode, attestation.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertIn("already exists", completed.stderr)
        self.assertEqual(output.read_bytes(), before)

    def run_with_failing_fsync_and_readback(self, output: Path) -> int:
        """Both the durability step and the read-back that describes it fail.

        Measured on an earlier generator: the read-back raised out of the very
        handler that was classifying the state, so a complete 9,414-byte asset
        was reported as exit 2 and `nothing published`.
        """
        facts_path, record_path = self.inputs()
        real_fsync = os.fsync
        real_read_bytes = Path.read_bytes

        def injected_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "injected directory fsync failure")
            return real_fsync(fd)

        def exploding_read_bytes(self):
            if self == output:
                raise OSError(5, "injected post-replace read-back failure")
            return real_read_bytes(self)

        os.fsync = injected_fsync
        Path.read_bytes = exploding_read_bytes
        try:
            return attestation.main(["--measured-release-facts", str(facts_path),
                                     "--build-record", str(record_path), "--output", str(output)])
        finally:
            os.fsync = real_fsync
            Path.read_bytes = real_read_bytes

    def test_a_failing_read_back_after_replace_is_still_exit_three(self) -> None:
        output = self.scratch / "nested.json"
        code = self.run_with_failing_fsync_and_readback(output)
        self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertEqual(code, 3)
        self.assertTrue(output.is_file())

    def test_the_asset_survives_that_nested_failure(self) -> None:
        output = self.scratch / "nested.json"
        self.run_with_failing_fsync_and_readback(output)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(document["status"], attestation.STATUS)

    def test_the_nested_failure_says_verification_was_unavailable(self) -> None:
        output = self.scratch / "nested-message.json"
        real_read_bytes = Path.read_bytes

        def exploding(self):
            if self == output:
                raise OSError(5, "injected read-back failure")
            return real_read_bytes(self)

        Path.read_bytes = exploding
        try:
            output.write_text("{}\n", encoding="utf-8")
            message = attestation.describe_published_asset(
                output, "{}\n", OSError(5, "injected fsync failure"))
        finally:
            Path.read_bytes = real_read_bytes
        self.assertNotIn("nothing published", message)
        self.assertIn("EXISTS", message)
        self.assertIn("could NOT be verified", message)
        self.assertIn("Do NOT", message)

    def test_the_description_helper_never_raises(self) -> None:
        """Even with an unreadable path and a hostile exception, a message comes back."""

        class Hostile(Exception):
            def __str__(self):
                raise RuntimeError("this exception cannot describe itself")

        message = attestation.describe_published_asset(
            self.scratch / "does-not-exist.json", "{}\n", Hostile())
        self.assertIn("EXISTS", message)
        self.assertIn("could NOT be verified", message)

    def run_with_interrupted_replace(self, output: Path, raiser, after_real_replace: bool) -> int:
        """A signal delivered inside the os.replace call itself.

        Measured on an earlier generator: `os.replace` completed and a
        `KeyboardInterrupt` arrived before `temporary = None` ran, so the
        exception escaped every handler while a complete, valid asset sat on
        disk. BaseException is not Exception.
        """
        facts_path, record_path = self.inputs()
        real_replace = attestation.os.replace

        def interrupting(src, dst, *a, **k):
            if after_real_replace:
                real_replace(src, dst, *a, **k)
            raise raiser()

        attestation.os.replace = interrupting
        try:
            return attestation.main(["--measured-release-facts", str(facts_path),
                                     "--build-record", str(record_path), "--output", str(output)])
        finally:
            attestation.os.replace = real_replace

    def test_a_keyboard_interrupt_after_the_replace_is_exit_three(self) -> None:
        output = self.scratch / "interrupted.json"
        code = self.run_with_interrupted_replace(
            output, lambda: KeyboardInterrupt("after replace signal"), after_real_replace=True)
        self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertTrue(output.is_file())
        self.assertEqual(json.loads(output.read_text())["status"], attestation.STATUS)

    def test_a_system_exit_after_the_replace_is_exit_three(self) -> None:
        output = self.scratch / "interrupted-exit.json"
        code = self.run_with_interrupted_replace(
            output, lambda: SystemExit("after replace exit"), after_real_replace=True)
        self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertTrue(output.is_file())

    def test_a_custom_base_exception_after_the_replace_is_exit_three(self) -> None:
        class Signal(BaseException):
            pass

        output = self.scratch / "interrupted-custom.json"
        code = self.run_with_interrupted_replace(output, lambda: Signal("after replace"),
                                                 after_real_replace=True)
        self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
        self.assertTrue(output.is_file())

    def test_an_interrupt_before_the_replace_is_exit_two_with_no_output(self) -> None:
        """Control: the classification follows the filesystem, not the code path."""
        output = self.scratch / "not-written.json"
        code = self.run_with_interrupted_replace(
            output, lambda: KeyboardInterrupt("before replace"), after_real_replace=False)
        self.assertEqual(code, attestation.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertFalse(output.exists())

    def test_an_interrupt_before_the_replace_leaves_no_temp_file(self) -> None:
        output = self.scratch / "not-written-2.json"
        self.run_with_interrupted_replace(
            output, lambda: KeyboardInterrupt("before replace"), after_real_replace=False)
        leftovers = [p.name for p in self.scratch.iterdir()
                     if p.name.startswith(f".{output.name}.")]
        self.assertEqual(leftovers, [])

    def test_no_base_exception_escapes_main(self) -> None:
        for index, (raiser, after) in enumerate((
                (lambda: KeyboardInterrupt("x"), True), (lambda: KeyboardInterrupt("x"), False),
                (lambda: SystemExit("x"), True), (lambda: SystemExit("x"), False))):
            with self.subTest(after_real_replace=after, index=index):
                code = self.run_with_interrupted_replace(
                    self.scratch / f"leak-{index}.json", raiser, after_real_replace=after)
                self.assertIn(code, (attestation.EXIT_REFUSED_BEFORE_PUBLISH,
                                     attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN))

    def test_the_existence_observer_never_raises(self) -> None:
        self.assertIs(attestation.observe_output(self.scratch / "absent.json"), False)
        self.assertIs(attestation.observe_output(self.scratch), True)

    def test_the_two_exit_codes_are_distinct(self) -> None:
        self.assertNotEqual(attestation.EXIT_REFUSED_BEFORE_PUBLISH,
                            attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)

    def test_the_durability_message_does_not_claim_nothing_was_published(self) -> None:
        output = self.scratch / "message.json"
        real_fsync = os.fsync

        def injected(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(5, "injected directory fsync failure")
            return real_fsync(fd)

        os.fsync = injected
        try:
            with self.assertRaises(attestation.PublishedDurabilityUncertain) as caught:
                attestation.write_atomically(output, "{}\n")
        finally:
            os.fsync = real_fsync
        message = str(caught.exception)
        self.assertNotIn("nothing published", message)
        self.assertIn("EXISTS", message)
        self.assertIn("byte-identical to what was generated", message)
        self.assertIn("Do NOT", message)


def statement_after(path: Path, function_name: str, needle: str) -> int:
    """Line of the statement executed immediately after the `needle` call.

    Located through the syntax tree, not by a hard-coded number. Duplicated
    from the builder's suite rather than shared, because a shared helper would
    mean a fifteenth changed file in a release scoped to fourteen.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == function_name)
    guards = []
    for parent in ast.walk(function):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if isinstance(statement, ast.Try):
                dumped = ast.dump(ast.Module(body=statement.body, type_ignores=[]))
                if needle in dumped:
                    guards.append((len(dumped), body, index))
    if not guards:
        raise AssertionError(f"no try guarding {needle!r} in {function_name}")
    _, body, index = min(guards, key=lambda item: item[0])
    guard = body[index]
    for position, statement in enumerate(guard.body):
        if needle in ast.dump(statement) and position + 1 < len(guard.body):
            return guard.body[position + 1].lineno
    if index + 1 < len(body):
        return body[index + 1].lineno
    raise AssertionError(f"nothing follows the {needle!r} call in {function_name}")


def success_report_line(path: Path, function_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == function_name)
    for parent in ast.walk(function):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if (isinstance(statement, ast.Return) and isinstance(statement.value, ast.Name)
                    and statement.value.id == "EXIT_OK"):
                return body[index - 1].lineno if index else statement.lineno
    raise AssertionError(f"no `return EXIT_OK` in {function_name}")


class InterruptAtLine:
    def __init__(self, filename: str, line: int, raiser):
        self.filename, self.line, self.raiser, self.fired = filename, line, raiser, False

    def _local(self, frame, event, arg):
        if event == "line" and frame.f_lineno == self.line and not self.fired:
            self.fired = True
            raise self.raiser()
        return self._local

    def _global(self, frame, event, arg):
        return self._local if frame.f_code.co_filename == self.filename else None

    def __enter__(self):
        sys.settrace(self._global)
        return self

    def __exit__(self, *exc):
        sys.settrace(None)
        return False


class Signal(BaseException):
    """A BaseException that is neither KeyboardInterrupt nor SystemExit."""


INTERRUPTIONS = {"KeyboardInterrupt": lambda: KeyboardInterrupt("interrupt"),
                 "SystemExit": lambda: SystemExit("interrupt"),
                 "custom BaseException": lambda: Signal("interrupt")}


class PostCommitInterruptWindows(GeneratorCase):
    """A signal after `os.replace`, but outside the narrow guard around it.

    Measured on an earlier generator: the line recording that the replace
    happened was unprotected, so an interruption there produced exit 2 and
    "nothing published" over a complete asset; and after `write_atomically()`
    returned, an interruption on the success report escaped as a traceback.
    """

    def interrupt_at(self, output: Path, line: int, raiser):
        facts_path, record_path = self.write_inputs()
        buffer = io.StringIO()
        code = escaped = None
        with InterruptAtLine(str(GENERATOR), line, raiser) as trap:
            try:
                with contextlib.redirect_stderr(buffer):
                    code = attestation.main(
                        ["--measured-release-facts", str(facts_path),
                         "--build-record", str(record_path), "--output", str(output)])
            except BaseException as error:  # noqa: BLE001 - an escape is the defect
                escaped = type(error).__name__
        self.assertTrue(trap.fired, "the traced line never executed")
        return code, escaped, buffer.getvalue()

    def test_an_interrupt_recording_the_replace_is_exit_three(self) -> None:
        line = statement_after(GENERATOR, "write_atomically", "replace")
        for index, (name, raiser) in enumerate(INTERRUPTIONS.items()):
            with self.subTest(interruption=name):
                output = self.scratch / f"post-call-{index}.json"
                code, escaped, err = self.interrupt_at(output, line, raiser)
                self.assertIsNone(escaped)
                self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
                self.assertTrue(output.is_file())
                self.assertEqual(json.loads(output.read_text())["status"], attestation.STATUS)
                self.assertNotIn("nothing published", err)

    def test_an_interrupt_on_the_success_report_is_exit_three(self) -> None:
        line = success_report_line(GENERATOR, "main")
        for index, (name, raiser) in enumerate(INTERRUPTIONS.items()):
            with self.subTest(interruption=name):
                output = self.scratch / f"post-return-{index}.json"
                code, escaped, err = self.interrupt_at(output, line, raiser)
                self.assertIsNone(escaped)
                self.assertEqual(code, attestation.EXIT_PUBLISHED_DURABILITY_UNCERTAIN)
                self.assertTrue(output.is_file())
                self.assertNotIn("nothing published", err)

    def test_the_traced_lines_are_the_intended_statements(self) -> None:
        """Control: the probe points where the test claims it does."""
        source = GENERATOR.read_text(encoding="utf-8").splitlines()
        self.assertIn("committed = True",
                      source[statement_after(GENERATOR, "write_atomically", "replace") - 1])
        self.assertIn("print(", source[success_report_line(GENERATOR, "main") - 1])

    def test_an_interrupt_before_the_replace_is_exit_two(self) -> None:
        """Control: the verdict follows the filesystem, not the code path."""
        facts_path, record_path = self.write_inputs()
        output = self.scratch / "never-written.json"
        real_replace = attestation.os.replace

        def interrupting(src, dst, *a, **k):
            raise KeyboardInterrupt("before the replace")

        attestation.os.replace = interrupting
        try:
            code = attestation.main(["--measured-release-facts", str(facts_path),
                                     "--build-record", str(record_path), "--output", str(output)])
        finally:
            attestation.os.replace = real_replace
        self.assertEqual(code, attestation.EXIT_REFUSED_BEFORE_PUBLISH)
        self.assertFalse(output.exists())

    def test_a_normal_run_is_still_exit_zero(self) -> None:
        facts_path, record_path = self.write_inputs()
        output = self.scratch / "normal.json"
        code = attestation.main(["--measured-release-facts", str(facts_path),
                                 "--build-record", str(record_path), "--output", str(output)])
        self.assertEqual(code, attestation.EXIT_OK)
        self.assertTrue(output.is_file())


class OutputLocation(GeneratorCase):
    def test_existing_output_is_refused(self) -> None:
        target = self.scratch / "already.json"
        target.write_text("keep me\n", encoding="utf-8")
        completed, _o = self.run_generator(output=target)
        self.assertEqual(completed.returncode, attestation.EXIT_REFUSED)
        self.assertIn("already exists", completed.stderr)
        self.assertEqual(target.read_text(), "keep me\n")

    def test_output_inside_the_repository_is_refused(self) -> None:
        target = REPO_ROOT / "should-never-appear.json"
        completed, _o = self.run_generator(output=target)
        self.assertEqual(completed.returncode, attestation.EXIT_REFUSED)
        self.assertIn("inside the repository", completed.stderr)
        self.assertFalse(target.exists())

    def test_output_equal_to_an_input_is_refused(self) -> None:
        facts_path, record_path = self.write_inputs()
        completed = subprocess.run(
            [sys.executable, "-B", str(GENERATOR),
             "--measured-release-facts", str(facts_path),
             "--build-record", str(record_path), "--output", str(facts_path)],
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, attestation.EXIT_REFUSED)
        self.assertIn("same file as an input", completed.stderr)
        self.assertEqual(json.loads(facts_path.read_text()), measured())


if __name__ == "__main__":
    unittest.main()
