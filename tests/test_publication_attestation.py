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
import copy
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import REPO_ROOT, SCRIPTS, copy_repository  # noqa: E402

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_publication_attestation as attestation  # noqa: E402

GENERATOR = SCRIPTS / "build_publication_attestation.py"
CHECK_RELEASE = SCRIPTS / "check_release.py"

#: What each leaf of PUBLICATION_AUDIT.json is meant to be, written here and
#: maintained here rather than read out of the gate's own AUDIT_SCHEMA. Deriving
#: the classification from the schema made the coverage report agree with the
#: gate by construction: a normative field quietly demoted to a free-text slot
#: was reported as prose and the measurement agreed, and nothing objected.
#: PINNED -- the gate must refuse a falsified value and a deletion.
#: RECOMPUTED -- the gate recomputes it from the tree.
#: PROSE -- explanatory English; the gate fixes its type, not its wording.
#: PROSE_LIST_ITEM -- an item of a descriptive inventory whose membership is open.
EXPECTED_CLAIM_CLASSIFICATION = {
    "schema_version": "PINNED",
    "release_version": "PINNED",
    "audit_type": "PINNED",
    "status": "PINNED",
    "what_this_file_is": "PROSE",
    "what_this_file_cannot_contain": "PROSE",
    "candidate_date_utc": "PINNED",
    "candidate_base_commit": "PINNED",
    "frozen_anchor_commit": "PINNED",
    "frozen_anchor_version": "PINNED",
    "internal_manifest.policy": "PINNED",
    "internal_manifest.entry_count": "RECOMPUTED",
    "internal_manifest.sha256": "RECOMPUTED",
    "internal_manifest.note": "PROSE",
    "verification_contract.verification_contract_version": "PINNED",
    "verification_contract.what_this_is": "PINNED",
    "verification_contract.where_the_results_live": "PINNED",
    "verification_contract.why_no_counts_here": "PINNED",
    "verification_contract.required_python": "PINNED",
    "verification_contract.commands.0.command": "PINNED",
    "verification_contract.commands.0.success": "PINNED",
    "verification_contract.commands.1.command": "PINNED",
    "verification_contract.commands.1.success": "PINNED",
    "verification_contract.commands.2.command": "PINNED",
    "verification_contract.commands.2.success": "PINNED",
    "verification_contract.commands.3.command": "PINNED",
    "verification_contract.commands.3.success": "PINNED",
    "verification_contract.commands.4.command": "PINNED",
    "verification_contract.commands.4.success": "PINNED",
    "verification_contract.commands.5.command": "PINNED",
    "verification_contract.commands.5.success": "PINNED",
    "verification_contract.commands.6.command": "PINNED",
    "verification_contract.commands.6.success": "PINNED",
    "verification_contract.commands.7.command": "PINNED",
    "verification_contract.commands.7.success": "PINNED",
    "verification_contract.commands.8.command": "PINNED",
    "verification_contract.commands.8.success": "PINNED",
    "verification_contract.commands.9.command": "PINNED",
    "verification_contract.commands.9.success": "PINNED",
    "verification_contract.commands.10.command": "PINNED",
    "verification_contract.commands.10.success": "PINNED",
    "verification_contract.commands.11.command": "PINNED",
    "verification_contract.commands.11.success": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.0": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.1": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.2": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.3": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.4": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.5": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.6": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.7": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.8": "PINNED",
    "verification_contract.outcomes_that_must_not_appear_here.9": "PINNED",
    "verification_contract.enforced_by": "PINNED",
    "dynamic_publication_attestation.location": "PROSE",
    "dynamic_publication_attestation.generator": "PINNED",
    "dynamic_publication_attestation.embedded_in_source_tree": "PINNED",
    "dynamic_publication_attestation.not_the_release_body": "PROSE",
    "dynamic_publication_attestation.reason": "PROSE",
    "dynamic_publication_attestation.fields_recorded_there.0": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.1": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.2": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.3": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.4": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.5": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.6": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.7": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.8": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.9": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.fields_recorded_there.10": "PROSE_LIST_ITEM",
    "dynamic_publication_attestation.not_recordable_even_there": "PROSE",
    "dynamic_publication_attestation.release_assets.distribution.0": "PINNED",
    "dynamic_publication_attestation.release_assets.distribution.1": "PINNED",
    "dynamic_publication_attestation.release_assets.auxiliary_integrity.0": "PINNED",
    "dynamic_publication_attestation.build_record_embedded": "PINNED",
    "dynamic_publication_attestation.build_record_preimage": "PROSE",
    "canonical_asset_builder.path": "PINNED",
    "canonical_asset_builder.tests": "PINNED",
    "canonical_asset_builder.generation_semantics": "PROSE",
    "canonical_asset_builder.exact_tag_binding": "PROSE",
    "canonical_asset_builder.archive_equals_tree": "PROSE",
    "canonical_asset_builder.attribute_sources_neutralised.0": "PINNED",
    "canonical_asset_builder.attribute_sources_neutralised.1": "PINNED",
    "canonical_asset_builder.attribute_sources_neutralised.2": "PINNED",
    "canonical_asset_builder.attribute_sources_neutralised.3": "PINNED",
    "canonical_asset_builder.attribute_sources_neutralised.4": "PINNED",
    "canonical_asset_builder.attribute_sources_neutralised.5": "PINNED",
    "canonical_asset_builder.attribute_sources_neutralised.6": "PINNED",
    "canonical_asset_builder.transactional": "PROSE",
    "canonical_asset_builder.public_record_redaction": "PROSE",
    "canonical_asset_builder.determinism_boundary": "PROSE",
    "canonical_asset_builder.target_sensitivity": "PROSE",
    "canonical_asset_builder.environment_fixed.0": "PINNED",
    "canonical_asset_builder.environment_fixed.1": "PINNED",
    "canonical_asset_builder.environment_fixed.2": "PINNED",
    "canonical_asset_builder.environment_fixed.3": "PINNED",
    "canonical_asset_builder.environment_fixed.4": "PINNED",
    "canonical_asset_builder.environment_fixed.5": "PINNED",
    "canonical_asset_builder.environment_fixed.6": "PINNED",
    "canonical_asset_builder.environment_dropped.0": "PINNED",
    "canonical_asset_builder.environment_dropped.1": "PINNED",
    "canonical_asset_builder.environment_dropped.2": "PINNED",
    "canonical_asset_builder.environment_dropped.3": "PINNED",
    "canonical_asset_builder.environment_dropped.4": "PINNED",
    "canonical_asset_builder.environment_dropped.5": "PINNED",
    "canonical_asset_builder.environment_dropped.6": "PINNED",
    "canonical_asset_builder.environment_dropped.7": "PINNED",
    "canonical_asset_builder.environment_dropped.8": "PINNED",
    "canonical_asset_builder.environment_dropped.9": "PINNED",
    "canonical_asset_builder.environment_dropped.10": "PINNED",
    "canonical_asset_builder.atomic_publication": "PROSE",
    "canonical_asset_builder.expected_digest_gate": "PROSE",
    "canonical_asset_builder.build_record.path": "PROSE",
    "canonical_asset_builder.build_record.schema": "PINNED",
    "canonical_asset_builder.build_record.note": "PROSE",
    "canonical_asset_builder.build_record.added_in_v4.0": "PINNED",
    "canonical_asset_builder.build_record.added_in_v4.1": "PINNED",
    "canonical_asset_builder.build_record.added_in_v4.2": "PINNED",
    "canonical_asset_builder.build_record.added_in_v4.3": "PINNED",
    "canonical_asset_builder.build_record.added_in_v4.4": "PINNED",
    "canonical_asset_builder.build_record.archive_command_source": "PROSE",
    "canonical_asset_builder.builder_source_binding": "PROSE",
    "canonical_asset_builder.exit_codes.0": "PROSE",
    "canonical_asset_builder.exit_codes.2": "PROSE",
    "canonical_asset_builder.exit_codes.3": "PROSE",
    "canonical_asset_builder.commit_point_boundary": "PROSE",
    "canonical_asset_builder.renamed_directory_identity": "PROSE",
    "repository_url": "PINNED",
    "excluded_from_internal_manifest.0": "PINNED",
    "excluded_from_internal_manifest.1": "PINNED",
    "excluded_from_internal_manifest.2": "PINNED",
    "excluded_from_internal_manifest.3": "PINNED",
    "publication_attestation_generator.path": "PINNED",
    "publication_attestation_generator.tests": "PINNED",
    "publication_attestation_generator.output_asset": "PINNED",
    "publication_attestation_generator.inputs.0": "PROSE_LIST_ITEM",
    "publication_attestation_generator.inputs.1": "PROSE_LIST_ITEM",
    "publication_attestation_generator.status_emitted": "PINNED",
    "publication_attestation_generator.note": "PROSE",
    "publication_attestation_generator.record_contract": "PROSE",
    "publication_attestation_generator.release_relations": "PROSE",
    "publication_attestation_generator.exit_codes.0": "PROSE",
    "publication_attestation_generator.exit_codes.2": "PROSE",
    "publication_attestation_generator.exit_codes.3": "PROSE",
    "publication_attestation_generator.draft_asset_inventory": "PROSE",
    "publication_attestation_generator.commit_point_boundary": "PROSE",
    "candidate_scope_and_date.changed_paths": "PROSE",
    "candidate_scope_and_date.candidate_date": "PROSE",
    "candidate_scope_and_date.publication_date": "PROSE",
    "release_engineering_remediation.date_utc": "PINNED",
    "release_engineering_remediation.base_commit": "PINNED",
    "release_engineering_remediation.scope": "PINNED",
    "release_engineering_remediation.finding": "PROSE",
    "release_engineering_remediation.merge_first_parent_pin": "PINNED",
    "release_engineering_remediation.obsolete_pin_refused": "PINNED",
    "release_engineering_remediation.candidate_date_note": "PROSE",
    "release_engineering_remediation.manifest_binding.authoritative_field": "PINNED",
    "release_engineering_remediation.manifest_binding.carrier_scope": "PINNED",
    "release_engineering_remediation.manifest_binding.digest_text_equivalence": "PINNED",
    "release_engineering_remediation.manifest_binding.duplicate_current_digest_fields": "PINNED",
    "release_engineering_remediation.manifest_binding.production_gate": "PINNED",
}
STALE_AUDIT_MANIFEST_SHA256 = "09125bc8a0a985c93e8ce33bb91eb570146f4c0f02726f9aaf74cb39a4e9d3e6"

MERGE = "a1" * 20
TREE = "b2" * 20
PARENT_BASE = attestation.MERGE_FIRST_PARENT
EXPECTED_PUBLICATION_MERGE_FIRST_PARENT = "4a8eb084eafb099952b3b9efb799e1208e74302e"
OBSOLETE_PRE_DATE_MERGE_FIRST_PARENT = "2adfffb7dc68f40ea52fd1ed78bc2f11a46de78b"
# The August 2026 candidate pinned the release-prep merge; once the gate fixes
# were merged on top of it, that is no longer the release merge's first parent.
OBSOLETE_RELEASE_PREP_MERGE_FIRST_PARENT = "2146eba2e3cf8ac7dd873365856b58c5cee0d362"
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


class StaticAuditManifestBinding(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )

    def run_release_check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def test_the_public_audit_is_bound_to_the_current_manifest(self) -> None:
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        audit = json.loads((self.repo / "PUBLICATION_AUDIT.json").read_text())
        actual = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        self.assertEqual(audit["internal_manifest"]["sha256"], actual)

    def test_the_stale_pre_r9_manifest_digest_is_refused(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        audit["internal_manifest"]["sha256"] = STALE_AUDIT_MANIFEST_SHA256
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("does not match SHA256SUMS", completed.stdout)

    def test_the_binding_block_names_the_single_authority(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        binding = audit["release_engineering_remediation"]["manifest_binding"]
        self.assertEqual(
            binding,
            {
                "authoritative_field": "internal_manifest.sha256",
                "carrier_scope": "all_release_paths_file_bytes_and_decoded_json_keys_and_strings",
                "digest_text_equivalence": "case_insensitive_hex",
                "duplicate_current_digest_fields": "forbidden",
                "production_gate": "scripts/check_release.py",
            },
        )
        binding["authoritative_field"] = "release_engineering_remediation.manifest_binding.finalized_manifest_sha256"
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("authoritative_field", completed.stdout)

    def test_a_redundant_current_manifest_digest_is_refused(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        audit["release_engineering_remediation"]["manifest_binding"][
            "finalized_manifest_sha256"
        ] = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("must not duplicate internal_manifest.sha256", completed.stdout)

    def test_the_current_digest_under_an_unrelated_audit_field_is_refused(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        audit["alternate_manifest_digest"] = current
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest authority paths", completed.stdout)

    def test_the_current_digest_in_another_release_file_is_refused(self) -> None:
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        path = self.repo / "CHANGELOG.md"
        path.write_text(path.read_text() + f"\nR12 carrier control: {current}\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest appears outside PUBLICATION_AUDIT authority", completed.stdout)

    def test_an_uppercase_copy_in_the_audit_is_refused(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        audit["alternate_manifest_digest_upper"] = current.upper()
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest authority paths", completed.stdout)
        self.assertIn("case-insensitive byte occurrences=2", completed.stdout)

    def test_a_mixed_case_copy_in_another_release_file_is_refused(self) -> None:
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        letter_index = 0
        characters = []
        for character in current:
            if character in "abcdef":
                characters.append(character.upper() if letter_index % 2 == 0 else character)
                letter_index += 1
            else:
                characters.append(character)
        mixed = "".join(characters)
        self.assertNotEqual(mixed, current)
        self.assertNotEqual(mixed, current.upper())
        path = self.repo / "CHANGELOG.md"
        path.write_text(path.read_text() + f"\nR13 mixed-case carrier control: {mixed}\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest appears outside PUBLICATION_AUDIT authority", completed.stdout)
        self.assertIn("bytes:CHANGELOG.md:1", completed.stdout)

    def test_a_dot_ds_store_carrier_is_refused(self) -> None:
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        (self.repo / ".DS_Store").write_bytes(current.encode("ascii"))
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("bytes:.DS_Store:1", completed.stdout)

    def test_a_case_variant_digest_in_a_release_path_is_refused(self) -> None:
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        (self.repo / current.upper()).write_text("R13 path carrier control\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest appears outside PUBLICATION_AUDIT authority", completed.stdout)
        self.assertIn("path:", completed.stdout)

    def test_a_unicode_escaped_digest_inside_a_longer_audit_string_is_refused(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest().upper()
        carrier = f"prefix:{current}:suffix"
        audit["escaped_semantic_manifest_carrier"] = carrier
        text = json.dumps(audit, ensure_ascii=True, indent=2) + "\n"
        plain = json.dumps(carrier)
        escaped = '"' + "".join(f"\\u{ord(character):04x}" for character in carrier) + '"'
        self.assertIn(plain, text)
        text = text.replace(plain, escaped, 1)
        path.write_text(text, encoding="utf-8")
        self.assertEqual(path.read_bytes().lower().count(current.lower().encode("ascii")), 1)
        self.assertIn(current.lower(), json.loads(path.read_text())["escaped_semantic_manifest_carrier"].lower())
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest authority paths", completed.stdout)
        self.assertIn("escaped_semantic_manifest_carrier", completed.stdout)

    def test_a_unicode_escaped_digest_inside_a_longer_audit_key_is_refused(self) -> None:
        path = self.repo / "PUBLICATION_AUDIT.json"
        audit = json.loads(path.read_text())
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest().upper()
        carrier = f"prefix_{current}_suffix"
        audit[carrier] = "R14 escaped-key carrier control"
        text = json.dumps(audit, ensure_ascii=True, indent=2) + "\n"
        plain = json.dumps(carrier)
        escaped = '"' + "".join(f"\\u{ord(character):04x}" for character in carrier) + '"'
        self.assertIn(plain, text)
        text = text.replace(plain, escaped, 1)
        path.write_text(text, encoding="utf-8")
        self.assertEqual(path.read_bytes().lower().count(current.lower().encode("ascii")), 1)
        self.assertIn(carrier, json.loads(path.read_text()))
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("manifest digest authority paths", completed.stdout)
        self.assertIn("<key:", completed.stdout)

    def test_an_unrelated_64_hex_value_remains_allowed(self) -> None:
        """Control: the carrier scan matches the manifest digest, not every 64-hex string.

        R14 planted the unrelated digest under a new key of PUBLICATION_AUDIT.json. R15 fixes
        the audit's key set exactly, so an added key is refused for being unknown and could no
        longer show what this control is about. The unrelated digest therefore goes into another
        release file, which is the same carrier scan over file bytes.
        """
        current = hashlib.sha256((self.repo / "SHA256SUMS").read_bytes()).hexdigest()
        unrelated = "0" * 64 if current != "0" * 64 else "1" * 64
        path = self.repo / "CHANGELOG.md"
        path.write_text(path.read_text() + f"\nUnrelated digest control: {unrelated}\n", encoding="utf-8")
        completed = self.run_release_check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)



class PublicationMergeFirstParentPin(GeneratorCase):
    def test_the_pin_is_the_current_pre_publication_main(self) -> None:
        self.assertEqual(
            attestation.MERGE_FIRST_PARENT,
            EXPECTED_PUBLICATION_MERGE_FIRST_PARENT,
        )

    def test_the_obsolete_pre_date_merge_parent_is_refused(self) -> None:
        facts = measured()
        facts["merge_parent_base"] = OBSOLETE_PRE_DATE_MERGE_FIRST_PARENT
        completed, output = self.run_generator(facts)
        self.assert_refused(
            completed,
            f"first parent must be {EXPECTED_PUBLICATION_MERGE_FIRST_PARENT}",
            output,
        )

    def test_the_obsolete_release_prep_merge_parent_is_refused(self) -> None:
        facts = measured()
        facts["merge_parent_base"] = OBSOLETE_RELEASE_PREP_MERGE_FIRST_PARENT
        completed, output = self.run_generator(facts)
        self.assert_refused(
            completed,
            f"first parent must be {EXPECTED_PUBLICATION_MERGE_FIRST_PARENT}",
            output,
        )


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


class StaticAuditExactSchema(unittest.TestCase):
    """PUBLICATION_AUDIT.json is validated as a whole document.

    Before this, ``check_release.py`` read three blocks of the audit and treated the rest as
    prose. Thirty-nine single-field falsifications -- the schema version, the audit type, the
    status, the candidate base, the frozen anchor, the repository URL, the generator status,
    every recorded count and every recorded boolean -- were accepted by the production gate and
    by the evidence validator together, so the file could say anything about itself and still
    ship. The cases below are those falsifications expressed against the R15 contract, plus the
    structural ones: an unknown key, a missing key, a wrong type, a bool in an integer slot, a
    duplicate key and a non-finite number.
    """

    REMOVED_BLOCKS = ("local_candidate_replay", "static_checks", "changes_from_v1.0.1")

    TOP_LEVEL_LITERALS = {
        "schema_version": 4,
        "release_version": "1.0.3",
        "audit_type": "dynamic_release_record",
        "status": "PASS",
        "candidate_date_utc": "2026-08-09",
        "candidate_base_commit": "0" * 40,
        "frozen_anchor_commit": "0" * 40,
        "frozen_anchor_version": "v1.0.0",
        "repository_url": "https://github.com/Driedsandwich/some-other-repository",
    }

    NESTED_LITERALS = (
        (("internal_manifest", "policy"), "OTHER_POLICY.json"),
        (("verification_contract", "required_python"), "3.12"),
        (("verification_contract", "enforced_by"), "scripts/build_release_assets.py"),
        (("dynamic_publication_attestation", "generator"), "scripts/somewhere_else.py"),
        (("dynamic_publication_attestation", "embedded_in_source_tree"), True),
        (("dynamic_publication_attestation", "build_record_embedded"), False),
        (("canonical_asset_builder", "path"), "scripts/somewhere_else.py"),
        (("canonical_asset_builder", "tests"), "tests/somewhere_else.py"),
        (("canonical_asset_builder", "build_record", "schema"), "square-riesz-release-asset-build.v3"),
        (("publication_attestation_generator", "path"), "scripts/somewhere_else.py"),
        (("publication_attestation_generator", "tests"), "tests/somewhere_else.py"),
        (("publication_attestation_generator", "status_emitted"), "PUBLISHED_AND_VERIFIED"),
        (("release_engineering_remediation", "scope"), "Widened to the mathematical corpus."),
        (("release_engineering_remediation", "base_commit"), "0" * 40),
        (("release_engineering_remediation", "merge_first_parent_pin"), "0" * 40),
        (("release_engineering_remediation", "obsolete_pin_refused"), "0" * 40),
    )

    WRONG_TYPES = (
        (("schema_version",), "3"),
        (("schema_version",), True),
        (("release_version",), 102),
        (("internal_manifest",), "not an object"),
        (("internal_manifest", "entry_count"), True),
        (("internal_manifest", "entry_count"), "568"),
        (("verification_contract",), []),
        (("verification_contract", "commands"), {}),
        (("verification_contract", "outcomes_that_must_not_appear_here"), "none"),
        (("dynamic_publication_attestation", "embedded_in_source_tree"), 0),
        (("dynamic_publication_attestation", "release_assets"), []),
        (("excluded_from_internal_manifest",), "PUBLICATION_AUDIT.json"),
        (("canonical_asset_builder", "exit_codes"), []),
        (("release_engineering_remediation", "manifest_binding"), "internal_manifest.sha256"),
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        shutil.copytree(
            REPO_ROOT,
            self.repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        self.audit_path = self.repo / "PUBLICATION_AUDIT.json"
        self.original = self.audit_path.read_bytes()

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def restore(self) -> None:
        self.audit_path.write_bytes(self.original)

    def load(self) -> dict:
        return json.loads(self.audit_path.read_text(encoding="utf-8"))

    def save(self, audit: dict) -> None:
        self.audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def place(self, audit: dict, path: tuple[str, ...], value: object) -> None:
        node = audit
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value

    def assert_refused(self, needle: str) -> str:
        completed = self.check()
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn(needle, completed.stdout)
        return completed.stdout

    def test_the_unmodified_candidate_passes(self) -> None:
        """Control: every refusal below is attributable to its own change."""
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_every_removed_measurement_block_is_refused_on_reintroduction(self) -> None:
        values: dict[str, object] = {
            "local_candidate_replay": {"verifiers": 88, "source_git_dirty": True},
            "static_checks": {"unit_tests": 485},
            "changes_from_v1.0.1": {},
        }
        for block in self.REMOVED_BLOCKS:
            with self.subTest(block=block):
                self.restore()
                audit = self.load()
                self.assertNotIn(block, audit)
                audit[block] = values[block]
                self.save(audit)
                self.assert_refused(f"has unknown keys ['{block}']")

    def test_a_removed_block_reintroduced_as_a_scalar_is_refused(self) -> None:
        audit = self.load()
        audit["local_candidate_replay"] = "no longer an object"
        self.save(audit)
        self.assert_refused("has unknown keys ['local_candidate_replay']")

    def test_an_unknown_top_level_key_is_refused(self) -> None:
        audit = self.load()
        audit["unexpected_top_level_control"] = {"injected": True}
        self.save(audit)
        self.assert_refused("has unknown keys ['unexpected_top_level_control']")

    def test_every_required_top_level_key_is_required(self) -> None:
        for key in sorted(self.load()):
            with self.subTest(field=key):
                self.restore()
                audit = self.load()
                del audit[key]
                self.save(audit)
                self.assert_refused(f"is missing keys ['{key}']")

    def test_every_normative_top_level_literal_is_pinned(self) -> None:
        for key, wrong in self.TOP_LEVEL_LITERALS.items():
            with self.subTest(field=key):
                self.restore()
                audit = self.load()
                self.assertNotEqual(audit[key], wrong)
                audit[key] = wrong
                self.save(audit)
                completed = self.check()
                self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
                self.assertIn(key, completed.stdout)

    def test_every_normative_nested_literal_is_pinned(self) -> None:
        for path, wrong in self.NESTED_LITERALS:
            with self.subTest(field=".".join(path)):
                self.restore()
                audit = self.load()
                audit_value = audit
                for part in path:
                    audit_value = audit_value[part]
                self.assertNotEqual(audit_value, wrong)
                self.place(audit, path, wrong)
                self.save(audit)
                completed = self.check()
                self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
                self.assertIn(path[-1], completed.stdout)

    def test_every_wrong_type_is_refused(self) -> None:
        for path, wrong in self.WRONG_TYPES:
            with self.subTest(field=".".join(path), value=repr(wrong)):
                self.restore()
                audit = self.load()
                self.place(audit, path, wrong)
                self.save(audit)
                completed = self.check()
                self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
                self.assertIn("PUBLICATION_AUDIT schema:", completed.stdout)

    def test_an_unknown_nested_key_is_refused(self) -> None:
        audit = self.load()
        audit["internal_manifest"]["extra_note"] = "injected"
        self.save(audit)
        self.assert_refused("$.internal_manifest has unknown keys ['extra_note']")

    def test_a_missing_nested_key_is_refused(self) -> None:
        audit = self.load()
        del audit["canonical_asset_builder"]["build_record"]["schema"]
        self.save(audit)
        self.assert_refused("$.canonical_asset_builder.build_record is missing keys ['schema']")

    def test_a_renamed_canonical_asset_is_refused(self) -> None:
        for group in ("distribution", "auxiliary_integrity"):
            with self.subTest(group=group):
                self.restore()
                audit = self.load()
                assets = audit["dynamic_publication_attestation"]["release_assets"][group]
                assets[0] = assets[0].replace("v1.0.2", "v1.0.3")
                self.save(audit)
                self.assert_refused(f"release_assets.{group}")

    def test_a_duplicate_top_level_key_is_refused(self) -> None:
        line = '  "audit_type": "static_release_candidate",\n'
        text = self.audit_path.read_text(encoding="utf-8")
        self.assertEqual(text.count(line), 1)
        self.audit_path.write_text(text.replace(line, line * 2, 1), encoding="utf-8")
        self.assert_refused("duplicate JSON key 'audit_type'")

    def test_a_non_finite_number_is_refused(self) -> None:
        text = self.audit_path.read_text(encoding="utf-8")
        self.assertIn('"schema_version": 3', text)
        self.audit_path.write_text(text.replace('"schema_version": 3', '"schema_version": NaN', 1),
                                   encoding="utf-8")
        self.assert_refused("non-finite JSON constant NaN")

    def test_the_release_version_must_equal_the_version_file(self) -> None:
        (self.repo / "VERSION").write_text("1.0.3\n", encoding="utf-8")
        self.assert_refused("PUBLICATION_AUDIT release_version=")

    def test_a_measured_count_in_the_verification_contract_is_refused(self) -> None:
        audit = self.load()
        audit["verification_contract"]["commands"][0]["command"] = 88
        self.save(audit)
        self.assert_refused("verification_contract carries no measured value")

    def test_a_measured_outcome_name_in_the_verification_contract_is_refused(self) -> None:
        audit = self.load()
        audit["verification_contract"]["verifiers"] = "88"
        self.save(audit)
        self.assert_refused("is a measured outcome and must not appear in verification_contract")

    def test_an_unpinned_digest_in_the_verification_contract_is_refused(self) -> None:
        audit = self.load()
        audit["verification_contract"]["what_this_is"] += " digest " + "a" * 64
        self.save(audit)
        self.assert_refused("carries digest-shaped text")

    def test_dropping_a_required_command_from_the_contract_is_refused(self) -> None:
        audit = self.load()
        audit["verification_contract"]["commands"].pop(3)
        self.save(audit)
        self.assert_refused("verification_contract.commands=")

    def test_rewriting_a_required_command_is_refused(self) -> None:
        audit = self.load()
        audit["verification_contract"]["commands"][0]["command"] = "true"
        self.save(audit)
        self.assert_refused("verification_contract.commands=")

    def test_reordering_the_required_commands_is_refused(self) -> None:
        audit = self.load()
        commands = audit["verification_contract"]["commands"]
        commands[0], commands[1] = commands[1], commands[0]
        self.save(audit)
        self.assert_refused("verification_contract.commands=")

    def test_a_pinned_identity_in_the_verification_contract_remains_allowed(self) -> None:
        """Control: the contract may name the fixed history the audit already pins."""
        audit = self.load()
        anchor = audit["frozen_anchor_commit"]
        self.assertTrue(any(anchor in entry["command"] for entry in audit["verification_contract"]["commands"]))
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_a_timestamp_in_the_verification_contract_is_refused(self) -> None:
        audit = self.load()
        audit["verification_contract"]["where_the_results_live"] += " Measured 2026-08-12."
        self.save(audit)
        self.assert_refused("verification_contract records no measured timestamp")

    def test_the_remediation_date_must_be_a_real_calendar_date(self) -> None:
        audit = self.load()
        audit["release_engineering_remediation"]["date_utc"] = "2026-99-99"
        self.save(audit)
        self.assert_refused("is not a real calendar date")

    def test_the_remediation_date_may_not_precede_the_candidate_date(self) -> None:
        audit = self.load()
        audit["release_engineering_remediation"]["date_utc"] = "2026-08-07"
        self.save(audit)
        self.assert_refused("precedes candidate_date_utc")

    def test_the_publication_dates_must_agree(self) -> None:
        path = self.repo / "CITATION.cff"
        text = path.read_text(encoding="utf-8")
        replaced = re.sub(r'^date-released:.*$', 'date-released: "2026-08-13"', text,
                          count=1, flags=re.MULTILINE)
        self.assertNotEqual(replaced, text)
        path.write_text(replaced, encoding="utf-8")
        self.assert_refused("publication date disagrees")

    def test_moving_both_publication_dates_together_remains_allowed(self) -> None:
        """Control: the dates are compared with each other, not pinned to one day."""
        citation = self.repo / "CITATION.cff"
        changelog = self.repo / "CHANGELOG.md"
        citation.write_text(
            re.sub(r'^date-released:.*$', 'date-released: "2026-08-13"',
                   citation.read_text(encoding="utf-8"), count=1, flags=re.MULTILINE),
            encoding="utf-8")
        changelog.write_text(
            re.sub(r'^## 1\.0\.2 — .*$', '## 1.0.2 — 2026-08-13',
                   changelog.read_text(encoding="utf-8"), count=1, flags=re.MULTILINE),
            encoding="utf-8")
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class CitationSemanticParser(unittest.TestCase):
    """CITATION.cff refuses these injections. R17 refuses them for a different reason.

    These cases were written against the R16 reader, which enumerated the top
    level and named the offending key. R17 pins the file's bytes instead, so the
    same injections are refused because the normalized digest moved, because the
    date line count is not one, or because a byte outside printable ASCII and LF
    is present. The cases and their ids are kept -- they record what was tried --
    and the expected reasons were re-measured from the gate rather than guessed.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repository(Path(self.temp.name))
        self.citation = self.repo / "CITATION.cff"

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo, capture_output=True, text=True)

    def assert_unmodified_passes(self) -> None:
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def refuse(self, body: bytes, expected: str) -> None:
        """The injected file must change bytes and must then be refused."""
        before = self.citation.read_bytes()
        self.assertNotEqual(before, body, "the injection did not change CITATION.cff")
        self.citation.write_bytes(body)
        completed = self.check()
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn(expected, output, output)

    def append(self, text: str, expected: str) -> None:
        self.refuse(self.citation.read_bytes() + text.encode("utf-8"), expected)

    def substitute(self, old: str, new: str, expected: str) -> None:
        body = self.citation.read_text(encoding="utf-8")
        self.assertEqual(body.count(old), 1, f"anchor {old!r} is not unique")
        self.refuse(body.replace(old, new).encode("utf-8"), expected)

    def test_the_unmodified_citation_file_passes(self) -> None:
        self.assert_unmodified_passes()

    def test_plain_duplicate_date_released(self) -> None:
        self.append("date-released: 2026-01-01\n", "normalized sha256")

    def test_double_quoted_duplicate_date_released(self) -> None:
        self.append('"date-released": "2026-01-01"\n', "normalized sha256")

    def test_single_quoted_duplicate_date_released(self) -> None:
        self.append("'date-released': '2026-01-01'\n", "normalized sha256")

    def test_unicode_escaped_key_spelling_date_released(self) -> None:
        self.append('"date-\\u002Dreleased": "2026-01-01"\n', "normalized sha256")

    def test_yaml_merge_key_injection(self) -> None:
        self.append("<<: *base\n", "normalized sha256")

    def test_anchor_on_the_date(self) -> None:
        self.substitute('date-released: "2026-08-12"', 'date-released: &d "2026-08-12"',
                        "date-released lines=0")

    def test_alias_injection(self) -> None:
        self.append("other: *d\n", "normalized sha256")

    def test_tag_on_the_date(self) -> None:
        self.substitute('date-released: "2026-08-12"', 'date-released: !!str "2026-01-01"',
                        "date-released lines=0")

    def test_multiple_yaml_documents(self) -> None:
        self.append('---\ndate-released: "2026-01-01"\n', "date-released lines=2")

    def test_flow_mapping_at_the_top_level(self) -> None:
        self.refuse(b'{date-released: "2026-01-01"}\n', "date-released lines=0")

    def test_invalid_calendar_date(self) -> None:
        self.substitute('"2026-08-12"', '"2026-02-30"', "is not a real calendar date")

    def test_date_that_does_not_round_trip(self) -> None:
        self.substitute('"2026-08-12"', '"2026-8-12"', "date-released lines=0")

    def test_citation_and_changelog_disagree(self) -> None:
        self.substitute('"2026-08-12"', '"2026-08-11"', "publication date disagrees")

    def test_a_missing_date_released_is_refused(self) -> None:
        body = self.citation.read_text(encoding="utf-8")
        stripped = "".join(line + "\n" for line in body.split("\n")
                           if not line.startswith("date-released:"))
        self.refuse(stripped.encode("utf-8"), "date-released lines=0")

    def test_carriage_returns_are_refused(self) -> None:
        body = self.citation.read_text(encoding="utf-8")
        self.refuse(body.replace("\n", "\r\n").encode("utf-8"), "outside printable ASCII and LF")


class VerificationContractExactPin(unittest.TestCase):
    """verification_contract carries exactly the text the gate pins, not merely strings.

    Pinning the *type* of a field let a measured count come back as a sentence
    inside it. Every field is pinned to its literal value, so a contract that
    grew a result is a different document.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repository(Path(self.temp.name))
        self.audit_path = self.repo / "PUBLICATION_AUDIT.json"

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo, capture_output=True, text=True)

    def mutate(self, change) -> subprocess.CompletedProcess[str]:
        before = self.audit_path.read_bytes()
        document = json.loads(before.decode("utf-8"))
        change(document["verification_contract"])
        after = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.assertNotEqual(before, after, "the mutation did not change PUBLICATION_AUDIT.json")
        self.audit_path.write_bytes(after)
        return self.check()

    def assert_refused(self, change) -> None:
        completed = self.mutate(change)
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("verification_contract", output, output)

    def appended(self, sentence: str):
        def change(contract: dict) -> None:
            contract["what_this_is"] += " " + sentence
        return change

    def test_the_unmodified_contract_passes(self) -> None:
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_unit_test_count_in_prose(self) -> None:
        self.assert_refused(self.appended("Measured outcome: 511 unit tests passed."))

    def test_verifier_count_in_prose(self) -> None:
        self.assert_refused(self.appended("88 of 88 verifiers certified."))

    def test_slashed_count_in_prose(self) -> None:
        self.assert_refused(self.appended("Replay came back 88/88."))

    def test_zero_failed_in_prose(self) -> None:
        self.assert_refused(self.appended("zero failed in the last run."))

    def test_zero_timed_out_in_prose(self) -> None:
        self.assert_refused(self.appended("0 timed out."))

    def test_all_checks_passed_in_prose(self) -> None:
        self.assert_refused(self.appended("all checks passed."))

    def test_spelled_out_counts_in_prose(self) -> None:
        self.assert_refused(self.appended(
            "Five hundred and eleven unit tests passed and eighty-eight verifiers certified."))

    def test_required_python_cannot_drift(self) -> None:
        def change(contract: dict) -> None:
            contract["required_python"] = "3.12"
        self.assert_refused(change)

    def test_enforced_by_cannot_drift(self) -> None:
        def change(contract: dict) -> None:
            contract["enforced_by"] = "scripts/other.py"
        self.assert_refused(change)

    def test_forbidden_outcome_list_order_is_pinned(self) -> None:
        def change(contract: dict) -> None:
            items = list(contract["outcomes_that_must_not_appear_here"])
            items[0], items[1] = items[1], items[0]
            contract["outcomes_that_must_not_appear_here"] = items
        self.assert_refused(change)

    def test_forbidden_outcome_list_cannot_lose_an_item(self) -> None:
        def change(contract: dict) -> None:
            contract["outcomes_that_must_not_appear_here"] = \
                contract["outcomes_that_must_not_appear_here"][:-1]
        self.assert_refused(change)

    def test_a_command_success_condition_cannot_drift(self) -> None:
        def change(contract: dict) -> None:
            contract["commands"][0]["success"] = "exit 0"
        self.assert_refused(change)


class ManifestBindingSchemaAlone(unittest.TestCase):
    """AUDIT_SCHEMA refuses all five manifest_binding falsifications by itself.

    The audit claimed two layers guarded these values. Only one did: the schema
    declared them ``TEXT`` and the field-by-field comparison carried the whole
    boundary. Both layers now read one constant, and this class measures the
    schema with the other layer removed.
    """

    FIELDS = ("authoritative_field", "carrier_scope", "digest_text_equivalence",
              "duplicate_current_digest_fields", "production_gate")

    #: The block this class takes out. Deleting the matching lines instead left a
    #: `for` with no body, and every case then failed on an IndentationError --
    #: which is indistinguishable from the schema refusing the value.
    OTHER_LAYER = (
        "    if set(binding)!=set(BINDING_VALUES):issues.append("
        "f'PUBLICATION_AUDIT manifest_binding keys={sorted(binding)!r} "
        "expected={sorted(BINDING_VALUES)!r}')\n"
        "    for field,expected in BINDING_VALUES.items():\n"
        "     if binding.get(field)!=expected:issues.append("
        "f'PUBLICATION_AUDIT manifest_binding.{field}={binding.get(field)!r} "
        "expected={expected}')\n"
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repository(Path(self.temp.name))
        self.gate = self.repo / "scripts" / "check_release.py"
        self.audit_path = self.repo / "PUBLICATION_AUDIT.json"

    def remove_the_other_layer(self) -> None:
        source = self.gate.read_text(encoding="utf-8")
        self.assertEqual(source.count(self.OTHER_LAYER), 1,
                         "the field-by-field comparison block is not where this test expects it")
        patched = source.replace(self.OTHER_LAYER, "    pass\n")
        compile(patched, "check_release.py", "exec")
        self.gate.write_text(patched, encoding="utf-8")

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.gate)],
            cwd=self.repo, capture_output=True, text=True)

    def test_removing_the_other_layer_alone_still_passes(self) -> None:
        """The control: with the comparisons gone and nothing falsified, the gate passes.

        Without this, a syntax error introduced by the removal would look
        exactly like the schema doing its job.
        """
        self.remove_the_other_layer()
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def falsify(self, field: str) -> None:
        self.remove_the_other_layer()
        before = self.audit_path.read_bytes()
        document = json.loads(before.decode("utf-8"))
        document["release_engineering_remediation"]["manifest_binding"][field] = "FALSIFIED"
        after = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.assertNotEqual(before, after, "the falsification did not change any bytes")
        self.audit_path.write_bytes(after)
        completed = self.check()
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn(f"manifest_binding.{field}", output, output)

    def test_schema_alone_refuses_authoritative_field(self) -> None:
        self.falsify("authoritative_field")

    def test_schema_alone_refuses_carrier_scope(self) -> None:
        self.falsify("carrier_scope")

    def test_schema_alone_refuses_digest_text_equivalence(self) -> None:
        self.falsify("digest_text_equivalence")

    def test_schema_alone_refuses_duplicate_current_digest_fields(self) -> None:
        self.falsify("duplicate_current_digest_fields")

    def test_schema_alone_refuses_production_gate(self) -> None:
        self.falsify("production_gate")

    def test_all_five_fields_are_covered_by_this_class(self) -> None:
        """The list of fields here must equal the ones the gate states.

        A sixth field added to the audit with no test here would otherwise be
        pinned by the schema and never measured.
        """
        source = self.gate.read_text(encoding="utf-8")
        module = ast.parse(source)
        values = None
        for node in module.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "BINDING_VALUES" for t in node.targets):
                values = ast.literal_eval(node.value)
        self.assertIsNotNone(values, "BINDING_VALUES is not a literal in check_release.py")
        self.assertEqual(sorted(values), sorted(self.FIELDS))
        tested = {name.split("refuses_", 1)[1] for name in dir(self)
                  if name.startswith("test_schema_alone_refuses_")}
        self.assertEqual(tested, set(self.FIELDS))


class AuditClaimPolicy(unittest.TestCase):
    """The policy names every leaf of the audit, and says what each one is for.

    Reading the classification out of ``AUDIT_SCHEMA`` made the coverage report
    agree with the gate by construction: a normative field demoted to a free-text
    slot was reported as prose, the measurement agreed, and nothing objected. The
    policy is written here instead, so a demotion becomes a disagreement.

    The full behavioural sweep -- every leaf falsified, retyped and deleted -- is
    carried by ``audit_claim_coverage.py`` in the external evidence, because it
    runs the gate 480 times. The cases below are the structural properties plus
    one named leaf from each pinned block; nothing here is sampled silently.
    """

    CLASSES = ("PINNED", "RECOMPUTED", "PROSE", "PROSE_LIST_ITEM")
    #: A value with no whitespace is a token, an identifier or a setting -- not a
    #: sentence -- and may not be filed under a class whose wording is free.
    MACHINE_READABLE = re.compile(r"^[A-Za-z0-9_.\-/=:+*]+$")
    #: One leaf per pinned block, exercised against the live gate here.
    REPRESENTATIVES = (
        "verification_contract.enforced_by",
        "release_engineering_remediation.manifest_binding.authoritative_field",
        "canonical_asset_builder.environment_fixed.0",
        "canonical_asset_builder.build_record.added_in_v4.0",
        "excluded_from_internal_manifest.0",
        "dynamic_publication_attestation.release_assets.distribution.0",
    )

    @staticmethod
    def leaves(node, path=()):
        out = []
        if isinstance(node, dict):
            for key, value in node.items():
                out.extend(AuditClaimPolicy.leaves(value, path + (key,)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                out.extend(AuditClaimPolicy.leaves(value, path + (index,)))
        else:
            out.append((".".join(str(p) for p in path), node))
        return out

    def setUp(self) -> None:
        self.document = json.loads((REPO_ROOT / "PUBLICATION_AUDIT.json").read_text(encoding="utf-8"))
        self.pairs = self.leaves(self.document)

    def test_policy_names_every_leaf_and_only_those(self) -> None:
        actual = {path for path, _value in self.pairs}
        declared = set(EXPECTED_CLAIM_CLASSIFICATION)
        self.assertEqual(sorted(actual - declared), [], "leaves with no policy entry")
        self.assertEqual(sorted(declared - actual), [], "policy entries naming no leaf")

    def test_every_class_is_one_of_the_four(self) -> None:
        unknown = sorted({v for v in EXPECTED_CLAIM_CLASSIFICATION.values()
                          if v not in self.CLASSES})
        self.assertEqual(unknown, [])

    def test_no_machine_readable_value_is_classified_as_prose(self) -> None:
        offenders = []
        for path, value in self.pairs:
            declared = EXPECTED_CLAIM_CLASSIFICATION[path]
            if declared not in ("PROSE", "PROSE_LIST_ITEM"):
                continue
            machine = (isinstance(value, bool) or isinstance(value, (int, float))
                       or (isinstance(value, str) and self.MACHINE_READABLE.fullmatch(value)))
            if machine:
                offenders.append((path, declared, value))
        self.assertEqual(offenders, [], "machine-readable values filed as prose")

    def test_the_policy_is_a_literal_and_not_read_from_the_gate(self) -> None:
        """The point of the policy is that it is not the schema restated."""
        source = (REPO_ROOT / "tests/test_publication_attestation.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        found = None
        for node in module.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "EXPECTED_CLAIM_CLASSIFICATION"
                    for t in node.targets):
                found = node
        self.assertIsNotNone(found, "the policy is not a module-level assignment")
        ast.literal_eval(found.value)
        gate = (REPO_ROOT / "scripts/check_release.py").read_text(encoding="utf-8")
        self.assertNotIn("EXPECTED_CLAIM_CLASSIFICATION", gate,
                         "the gate must not import or restate the policy")

    def test_each_pinned_block_has_a_representative_that_the_gate_refuses(self) -> None:
        for path in self.REPRESENTATIVES:
            with self.subTest(leaf=path):
                self.assertEqual(EXPECTED_CLAIM_CLASSIFICATION[path], "PINNED")
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                repo = copy_repository(Path(temp.name))
                target = repo / "PUBLICATION_AUDIT.json"
                before = target.read_bytes()
                document = json.loads(before.decode("utf-8"))
                node = document
                parts = path.split(".")
                for part in parts[:-1]:
                    node = node[int(part)] if part.isdigit() else node[part]
                last = parts[-1]
                key = int(last) if last.isdigit() else last
                node[key] = node[key] + "_FALSIFIED" if isinstance(node[key], str) else "FALSIFIED"
                after = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                self.assertNotEqual(before, after, "the falsification changed nothing")
                target.write_bytes(after)
                completed = subprocess.run(
                    [sys.executable, "-B", str(repo / "scripts" / "check_release.py")],
                    cwd=repo, capture_output=True, text=True)
                self.assertNotEqual(completed.returncode, 0,
                                    completed.stdout + completed.stderr)


class CitationCanonicalByteProfile(unittest.TestCase):
    """CITATION.cff is pinned as bytes, so a reader and the gate cannot disagree.

    R16 enumerated the top level and refused anything that was not a plain,
    unique, unadorned key. That is still a reader splitting on LF, and U+0085,
    U+2028 and U+2029 end a line for a YAML parser without being LF: a comment
    could carry a second `date-released` that a real reader honours and the gate
    never saw. A broken nested flow collection slipped through for the same
    reason -- only column-zero entries were being looked at.

    Every byte outside printable ASCII and LF is now refused, and the file with
    its date line replaced by a placeholder must hash to one known value. A byte
    changed in an author, the title or the abstract is a different file.
    """

    NORMALIZED_SHA256 = "acd920368815629ef8fdb7cc65148f657e4cc476047a6a0b97715d017aba16f3"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repository(Path(self.temp.name))
        self.citation = self.repo / "CITATION.cff"
        self.changelog = self.repo / "CHANGELOG.md"
        self.original = self.citation.read_bytes()

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo, capture_output=True, text=True)

    def assert_accepted(self) -> None:
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def refuse(self, body: bytes, expected: str) -> None:
        """The variant must differ in bytes, and must then be refused by name."""
        self.assertNotEqual(self.original, body, "the variant changed no bytes")
        self.citation.write_bytes(body)
        completed = self.check()
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn(expected, output, output)

    def append(self, text: str, expected: str) -> None:
        self.refuse(self.original + text.encode("utf-8"), expected)

    def substitute(self, old: str, new: str, expected: str) -> None:
        text = self.original.decode("utf-8")
        self.assertEqual(text.count(old), 1, f"anchor {old!r} is not unique")
        self.refuse(text.replace(old, new).encode("utf-8"), expected)

    # ---- the file as it stands ----------------------------------------------

    def test_the_current_citation_file_is_accepted(self) -> None:
        self.assert_accepted()

    def test_the_normalized_form_hashes_to_the_pinned_value(self) -> None:
        import re as _re
        normalized = _re.sub(rb'^date-released: "(\d{4}-\d{2}-\d{2})"$',
                             b'date-released: "<PUBLICATION_DATE>"',
                             self.original, flags=_re.M)
        self.assertEqual(hashlib.sha256(normalized).hexdigest(), self.NORMALIZED_SHA256)
        self.assertNotEqual(hashlib.sha256(self.original).hexdigest(), self.NORMALIZED_SHA256,
                            "the placeholder substitution changed nothing")

    # ---- the three Unicode line terminators ---------------------------------

    def test_next_line_u0085_hiding_a_second_date(self) -> None:
        self.append('\n# harmless\u0085date-released: "2026-01-01"\n',
                    "outside printable ASCII and LF")

    def test_line_separator_u2028_hiding_a_second_date(self) -> None:
        self.append('\n# harmless\u2028date-released: "2026-01-01"\n',
                    "outside printable ASCII and LF")

    def test_paragraph_separator_u2029_hiding_a_second_date(self) -> None:
        self.append('\n# harmless\u2029date-released: "2026-01-01"\n',
                    "outside printable ASCII and LF")

    # ---- structure a line-based reader never looked at -----------------------

    def test_unterminated_nested_flow_collection(self) -> None:
        self.substitute('  - family-names: "Kishimoto"', "  - family-names: [unterminated",
                        "normalized sha256")

    def test_one_byte_changed_in_an_author_name(self) -> None:
        self.substitute('family-names: "Kishimoto"', 'family-names: "Kishimoyo"',
                        "normalized sha256")

    def test_one_byte_changed_in_the_title(self) -> None:
        self.substitute("Certified lower bounds", "Certified lower bound5",
                        "normalized sha256")

    def test_one_byte_changed_in_the_abstract(self) -> None:
        self.substitute("Exact-rational branch-and-bound", "Exact-rational branch-and-bounds",
                        "normalized sha256")

    # ---- bytes that must not appear at all ----------------------------------

    def test_nul_inside_a_comment(self) -> None:
        self.append("\n# harmless\x00\n", "outside printable ASCII and LF")

    def test_utf8_bom(self) -> None:
        self.refuse(b"\xef\xbb\xbf" + self.original, "UTF-8 BOM")

    def test_carriage_returns(self) -> None:
        self.refuse(self.original.replace(b"\n", b"\r\n"), "outside printable ASCII and LF")

    def test_a_tab(self) -> None:
        self.append("\n#\tharmless\n", "outside printable ASCII and LF")

    def test_non_ascii_in_a_nested_value(self) -> None:
        self.substitute('given-names: "Satoshi"', 'given-names: "Satoshí"',
                        "outside printable ASCII and LF")

    def test_missing_final_newline(self) -> None:
        self.refuse(self.original.rstrip(b"\n"), "does not end with a newline")

    # ---- the date line itself ------------------------------------------------

    def test_block_scalar_date(self) -> None:
        self.substitute('date-released: "2026-08-12"', "date-released: >-\n  2026-08-12",
                        "date-released lines=0")

    def test_inline_comment_after_the_date(self) -> None:
        self.substitute('date-released: "2026-08-12"',
                        'date-released: "2026-08-12" # published',
                        "date-released lines=0")

    def test_quoted_key_duplicate_date(self) -> None:
        self.append('"date-released": "2026-01-01"\n', "normalized sha256")

    def test_plain_duplicate_date_line(self) -> None:
        self.append('date-released: "2026-01-01"\n', "date-released lines=2")

    def test_the_date_line_removed(self) -> None:
        text = self.original.decode("utf-8")
        stripped = "".join(line + "\n" for line in text.split("\n")
                           if not line.startswith("date-released:"))
        self.refuse(stripped.encode("utf-8"), "date-released lines=0")

    def test_an_impossible_calendar_date(self) -> None:
        self.substitute('date-released: "2026-08-12"', 'date-released: "2026-02-30"',
                        "is not a real calendar date")

    def test_a_date_that_does_not_round_trip(self) -> None:
        self.substitute('date-released: "2026-08-12"', 'date-released: "2026-8-12"',
                        "date-released lines=0")

    # ---- the relation with the changelog -------------------------------------

    def test_a_new_date_on_both_sides_is_accepted(self) -> None:
        """The date is the one thing that legitimately moves at publication."""
        self.citation.write_bytes(
            self.original.replace(b'date-released: "2026-08-12"',
                                  b'date-released: "2026-09-01"'))
        text = self.changelog.read_text(encoding="utf-8")
        self.assertEqual(text.count("## 1.0.2 — 2026-08-12"), 1)
        self.changelog.write_text(text.replace("## 1.0.2 — 2026-08-12",
                                               "## 1.0.2 — 2026-09-01"), encoding="utf-8")
        self.assert_accepted()

    def test_a_new_date_on_one_side_only_is_refused(self) -> None:
        self.substitute('date-released: "2026-08-12"', 'date-released: "2026-09-01"',
                        "publication date disagrees")


class VersionedHistories(unittest.TestCase):
    """The CFF profile and the verification contract are versioned, not frozen.

    A single pinned constant makes the only enforceable rule "never change this",
    which is a freeze. Each version now records the digest it replaced and why,
    so a change can be a migration and a rewrite of an existing entry cannot
    pretend to be one. Nothing here stops a rewrite of an entry and the thing it
    fixes together -- the auditing party holds the digest of the version in force
    for that -- but a history that no longer describes how this file came to be
    is refused.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repository(Path(self.temp.name))
        self.gate = self.repo / "scripts" / "check_release.py"
        self.original = self.gate.read_text(encoding="utf-8")

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(self.gate)],
            cwd=self.repo, capture_output=True, text=True)

    def substitute(self, old: str, new: str, expected: str) -> None:
        """Change one literal, prove the source still compiles, then require refusal.

        Compiling first matters: a mutation that breaks the syntax is refused for
        a reason that has nothing to do with the rule under test, and counting it
        as a refusal is how a control stops being a control.
        """
        self.assertEqual(self.original.count(old), 1, f"anchor {old!r} is not unique")
        mutated = self.original.replace(old, new, 1)
        self.assertNotEqual(self.original, mutated, "the variant changed no bytes")
        compile(mutated, str(self.gate), "exec")
        self.gate.write_text(mutated, encoding="utf-8")
        completed = self.check()
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn(expected, output, output)

    def test_the_untouched_repository_is_accepted(self) -> None:
        completed = self.check()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_the_pinned_cff_digest_has_exactly_one_carrier(self) -> None:
        """The property, not the spelling.

        Asserting the exact right-hand side pinned how the derivation was
        written, so changing `[...]` to `.get(...)` -- which was needed so a
        missing version is reported instead of raising -- broke a test that had
        nothing to say about the property. What matters is that the digest is
        written once and that the name derives from the history.
        """
        history = re.search(r"'normalized_sha256':'(?P<digest>[0-9a-f]{64})'", self.original)
        self.assertIsNotNone(history, "the profile history states no digest")
        self.assertEqual(self.original.count(history.group("digest")), 1,
                         "two equal carriers is how the R11 duplicate stayed invisible")
        assignment = re.search(r"^CFF_NORMALIZED_SHA256\s*=\s*(?P<rhs>.+)$",
                               self.original, re.M)
        self.assertIsNotNone(assignment, "the pin is not assigned at column zero")
        self.assertNotRegex(assignment.group("rhs"), r"[0-9a-f]{64}",
                            "the pin restates the digest instead of deriving it")
        self.assertIn("CFF_PROFILE_MIGRATIONS", assignment.group("rhs"),
                      "the pin does not come from the profile history")

    def test_the_required_commands_are_derived_from_the_contract(self) -> None:
        assignment = re.search(r"^REQUIRED_COMMANDS\s*=\s*(?P<rhs>.+)$", self.original, re.M)
        self.assertIsNotNone(assignment, "REQUIRED_COMMANDS is not assigned at column zero")
        self.assertIn("CONTRACT_COMMANDS", assignment.group("rhs"),
                      "the command list would be stated twice")

    def test_a_cff_profile_chain_that_does_not_link_is_refused(self) -> None:
        self.substitute("'previous_normalized_sha256':None,",
                        "'previous_normalized_sha256':'" + "0" * 64 + "',",
                        "does not chain")

    def test_a_cff_profile_entry_without_a_reason_is_refused(self) -> None:
        self.substitute(
            "'reason':'initial byte profile: printable ASCII and LF only, exactly one "
            "date-released line, whole-file digest with the date placeheld'",
            "'reason':''", "records no reason")

    def test_a_cff_profile_version_with_no_entry_is_refused(self) -> None:
        self.substitute("CFF_PROFILE_VERSION='1'", "CFF_PROFILE_VERSION='2'",
                        "has no entry in CFF_PROFILE_MIGRATIONS")

    def test_a_contract_chain_that_does_not_link_is_refused(self) -> None:
        self.substitute("'previous_commands_sha256':None,",
                        "'previous_commands_sha256':'" + "0" * 64 + "',",
                        "does not chain")

    def test_a_contract_entry_without_a_reason_is_refused(self) -> None:
        self.substitute(
            "'reason':'initial verification contract: twelve commands recorded with "
            "their success conditions and no measured outcome'",
            "'reason':''", "records no reason")

    def test_a_contract_command_count_that_disagrees_is_refused(self) -> None:
        self.substitute("'command_count':12,", "'command_count':11,",
                        "command_count=12 expected=11")


class MachineReadableDiagnostics(unittest.TestCase):
    """A complaint says which check objected and which path it was about.

    R17 printed prose. Replacing one line's wording with a generic sentence left
    the gate still exiting non-zero while nothing downstream could tell which
    field had been falsified, and the controls that were supposed to notice
    matched on the last component of a path found anywhere in the text -- so
    `$.status` and `$.a.b.status` were the same claim.
    """

    #: The path is JSON-quoted in the output. A reader that stops at the first
    #: closing bracket truncates $['changes_from_v1.0.1'] to something that
    #: still looks like a path, which is how nine controls lost their subject.
    STRUCTURED = re.compile(
        r'\[check_id=(?P<check_id>[^\s\]]+)\s+'
        r'subject_path=(?P<subject_path>"(?:[^"\\\\]|\\\\.)*")\]')

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repository(Path(self.temp.name))
        self.audit = self.repo / "PUBLICATION_AUDIT.json"
        self.original = json.loads(self.audit.read_text(encoding="utf-8"))

    def run_gate(self, document) -> str:
        self.audit.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0, "the falsification was not refused")
        return completed.stdout + completed.stderr

    def subjects(self, output: str) -> set[str]:
        return {json.loads(m.group("subject_path"))
                for m in self.STRUCTURED.finditer(output)}

    def test_a_falsified_scalar_names_its_full_path(self) -> None:
        document = copy.deepcopy(self.original)
        document["status"] = "PASS"
        output = self.run_gate(document)
        self.assertIn("check_id=audit.schema.value", output)
        self.assertIn("$.status", self.subjects(output))

    def test_a_deleted_key_names_the_key_and_not_its_parent(self) -> None:
        document = copy.deepcopy(self.original)
        del document["schema_version"]
        output = self.run_gate(document)
        self.assertIn("$.schema_version", self.subjects(output))
        self.assertNotIn("$", self.subjects(output) - {"$.schema_version"})

    def test_an_added_key_names_the_key_and_not_its_parent(self) -> None:
        document = copy.deepcopy(self.original)
        document["unexpected_top_level_control"] = {"injected": True}
        output = self.run_gate(document)
        self.assertIn("$.unexpected_top_level_control", self.subjects(output))

    def test_a_nested_falsification_names_the_whole_path(self) -> None:
        document = copy.deepcopy(self.original)
        document["internal_manifest"]["extra_note"] = "injected"
        output = self.run_gate(document)
        self.assertIn("$.internal_manifest.extra_note", self.subjects(output))

    def test_the_prose_half_of_a_complaint_is_unchanged(self) -> None:
        document = copy.deepcopy(self.original)
        del document["schema_version"]
        output = self.run_gate(document)
        self.assertIn("is missing keys ['schema_version']", output)

    def test_a_key_containing_a_bracket_survives_the_round_trip(self) -> None:
        """The regression for the reader that stopped at the first ']'.

        `changes_from_v1.0.1` is not an identifier, so its path is rendered
        `$['changes_from_v1.0.1']` -- and a subject_path read up to the first
        closing bracket becomes `$['changes_from_v1.0.1'`, which is not equal to
        anything a control expects. Nine of the thirty-nine lost their subject
        that way, while still refusing and still looking attributed.
        """
        document = copy.deepcopy(self.original)
        document["changes_from_v1.0.1"] = {"reintroduced": True}
        output = self.run_gate(document)
        self.assertIn("$['changes_from_v1.0.1']", self.subjects(output))

    def test_a_check_outside_the_schema_walk_still_names_its_subject(self) -> None:
        """release_version is compared against VERSION, not against the schema.

        It had no machine-readable half at all, so the control that falsified it
        was refused with nothing to attribute the refusal to.
        """
        document = copy.deepcopy(self.original)
        document["release_version"] = "9.9.9"
        output = self.run_gate(document)
        self.assertIn("$.release_version", self.subjects(output))

    def test_an_untouched_document_emits_no_diagnostics(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(self.repo / "scripts" / "check_release.py")],
            cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.subjects(completed.stdout + completed.stderr), set())


if __name__ == "__main__":
    unittest.main()
