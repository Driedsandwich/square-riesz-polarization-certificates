#!/usr/bin/env python3
from __future__ import annotations
import csv, datetime, hashlib, json, math, re, sys
from pathlib import Path
sys.dont_write_bytecode=True
from certificate_lib import EXPECTED_NS, METHODS, certifier_relpath  # noqa: E402
ROOT=Path(__file__).resolve().parents[1]
issues=[]
TEXT=object()
COUNT=object()
IDENTIFIER=re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
HEX_TOKEN=re.compile(r"(?<![0-9A-Za-z])(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![0-9A-Za-z])")
DATE_TOKEN=re.compile(r"\d{4}-\d{2}-\d{2}")
CONTRACT_FORBIDDEN_KEYS={'source_git_commit','source_git_dirty','source_git_clean','verifiers','certified','failed','timed_out','validator_problems','unit_tests','python_version','run_id','artifact_id','release_id','asset_id','sha256','digest','timestamp','commit','entry_count'}
def _strict_object(pairs):
 out={}
 for key,value in pairs:
  if key in out:raise ValueError(f"duplicate JSON key {key!r}")
  out[key]=value
 return out
def _reject_constant(value):raise ValueError(f"non-finite JSON constant {value}")
def _strict_float(value):
 number=float(value)
 if not math.isfinite(number):raise ValueError(f"non-finite JSON number {value}")
 return number
def _child(path,key):return f"{path}.{key}" if IDENTIFIER.fullmatch(key) else f"{path}[{key!r}]"
def _diag(out,check_id,subject_path,message):
 """One diagnostic, carrying what it is and what it is about.

 R17 emitted prose only. Replacing one line's wording with a generic sentence
 left the gate still exiting non-zero while the thirty-nine controls could no
 longer tell which field they had falsified -- and the record they had already
 written still said thirty-nine out of thirty-nine. A diagnostic now names its
 check and its subject, and the subject is the whole path, not its last
 component: matching on a basename makes `$.status` and `$.a.b.status` the same
 claim.
 """
 out.append({'check_id':check_id,'subject_path':subject_path,'message':message})
def _render_diag(diagnostic):
 #: The path is JSON-quoted because a JSON path may itself contain ']' --
 #: $['changes_from_v1.0.1'] does -- and a reader looking for the first closing
 #: bracket silently truncates it to something that still looks like a path.
 #: Quoted, where the value ends is unambiguous.
 return (f"{diagnostic['message']} "
         f"[check_id={diagnostic['check_id']} "
         f"subject_path={json.dumps(diagnostic['subject_path'],ensure_ascii=False)}]")
def _check_node(value,spec,path,out):
 """Exact-schema walk. Types are matched with `type(...) is`, so a bool never satisfies an int."""
 if spec is TEXT:
  if type(value) is not str or not value.strip():_diag(out,'audit.schema.text',path,f'{path} must be a non-empty string, got {value!r}')
  return
 if spec is COUNT:
  if type(value) is not int or value<0:_diag(out,'audit.schema.count',path,f'{path} must be a non-negative integer, got {value!r}')
  return
 if isinstance(spec,tuple):
  kind,item,exact=spec
  if kind!='list':raise AssertionError(kind)
  if type(value) is not list:_diag(out,'audit.schema.list_type',path,f'{path} must be an array, got {type(value).__name__}');return
  if exact is not None and value!=exact:_diag(out,'audit.schema.list_value',path,f'{path}={value!r} expected={exact!r}')
  if not value:_diag(out,'audit.schema.list_empty',path,f'{path} must not be empty')
  for index,element in enumerate(value):_check_node(element,item,f'{path}[{index}]',out)
  return
 if isinstance(spec,dict):
  if type(value) is not dict:_diag(out,'audit.schema.object_type',path,f'{path} must be an object, got {type(value).__name__}');return
  unknown=sorted(set(value)-set(spec))
  missing=sorted(set(spec)-set(value))
  # One diagnostic per key rather than one per object. An aggregate complaint
  # can only name the parent, so a control that deleted $.schema_version was
  # attributed to $ -- true, and useless for telling the thirty-nine apart.
  for key in unknown:_diag(out,'audit.schema.unknown_keys',_child(path,key),f'{path} has unknown keys [{key!r}]')
  for key in missing:_diag(out,'audit.schema.missing_keys',_child(path,key),f'{path} is missing keys [{key!r}]')
  for key in sorted(set(spec)&set(value)):_check_node(value[key],spec[key],_child(path,key),out)
  return
 if type(value) is not type(spec) or value!=spec:_diag(out,'audit.schema.value',path,f'{path}={value!r} expected={spec!r}')
def _calendar_date(text,label):
 try:
  parsed=datetime.date.fromisoformat(text)
 except (TypeError,ValueError):issues.append(f'{label}={text!r} is not a real calendar date');return None
 if parsed.isoformat()!=text:issues.append(f'{label}={text!r} does not round-trip as a calendar date');return None
 return parsed
#: CITATION.cff with its date line replaced by the placeholder below. Pinned as
#: bytes because parsing it line by line is what let a second date-released hide
#: behind U+2028 in a comment.
#: The profile is versioned the way the verification contract is, and for the
#: same reason: without a version boundary the only enforceable rule is "never
#: change CITATION.cff", which is a freeze rather than a profile. The digest is
#: stated once per version here and CFF_NORMALIZED_SHA256 derives from it, so
#: there is one carrier instead of two equal ones that can drift apart.
#:
#: Publishing does not need a migration. The date line is replaced by the
#: placeholder before hashing, so moving date-released leaves the digest where
#: it is. Every other edit -- an author, the title, the abstract -- produces a
#: different normalized file and needs an appended entry recording what it was,
#: what it became and why. Entries are appended, never rewritten: rewriting one
#: is how a change disguises itself as the thing that was always there.
CFF_PROFILE_VERSION='1'
CFF_PROFILE_MIGRATIONS={
 '1':{'normalized_sha256':'acd920368815629ef8fdb7cc65148f657e4cc476047a6a0b97715d017aba16f3',
      'previous_normalized_sha256':None,
      'reason':'initial byte profile: printable ASCII and LF only, exactly one date-released line, whole-file digest with the date placeheld'},
}
#: .get rather than [] on purpose: a version with no entry has to be reported
#: by the history check below, and a KeyError at import time is a crash, which
#: is not a refusal -- it says nothing about the file it was asked to check.
CFF_NORMALIZED_SHA256=(CFF_PROFILE_MIGRATIONS.get(CFF_PROFILE_VERSION) or {}).get('normalized_sha256')
def _cff_profile_history_violations():
 """The chain has to link, and the version in force has to be in it.

 This cannot stop someone rewriting an entry and CITATION.cff together; nothing
 inside the candidate can, which is why the auditor's requirements file holds
 the current digest. What it does stop is cheaper and still worth stopping: a
 history that no longer describes a path from the first profile to this one.
 """
 out=[]
 versions=sorted(CFF_PROFILE_MIGRATIONS,key=int)
 if CFF_PROFILE_VERSION not in CFF_PROFILE_MIGRATIONS:
  out.append(f'CFF_PROFILE_VERSION={CFF_PROFILE_VERSION!r} has no entry in CFF_PROFILE_MIGRATIONS')
 if versions!=[str(n) for n in range(1,len(versions)+1)]:
  out.append(f'CFF profile versions are not 1..n without gaps: {versions}')
 previous=None
 for version in versions:
  entry=CFF_PROFILE_MIGRATIONS[version]
  if entry.get('previous_normalized_sha256')!=previous:
   out.append(f'CFF profile version {version} does not chain: '
              f'previous={entry.get("previous_normalized_sha256")} expected={previous}')
  if not entry.get('reason'):out.append(f'CFF profile version {version} records no reason')
  previous=entry.get('normalized_sha256')
 return out
issues.extend(_cff_profile_history_violations())
CFF_DATE_LINE=re.compile(rb'^date-released: "(\d{4}-\d{2}-\d{2})"$',re.M)
CFF_PLACEHOLDER=b'date-released: "<PUBLICATION_DATE>"'
def _cff_date_released(raw,out):
 """The publication date this file publishes, or None with the reason recorded.

 U+0085, U+2028 and U+2029 end a line for a YAML reader and not for one that
 splits on LF, so a comment could carry a second date-released that a reader
 honours and a line-based check does not see. Rejecting every byte that is not
 LF or printable ASCII removes that class outright, and pinning the rest of the
 file by digest removes the need to understand the nested structure at all: a
 malformed authors list is a different file, which is enough.
 """
 before=len(out)
 if raw.startswith(b'\xef\xbb\xbf'):out.append('CITATION.cff starts with a UTF-8 BOM')
 if not raw.endswith(b'\n'):out.append('CITATION.cff does not end with a newline')
 unusual=sorted({b for b in raw if b!=10 and not 0x20<=b<=0x7e})
 if unusual:out.append(f'CITATION.cff carries bytes outside printable ASCII and LF: {unusual[:8]}')
 dates=CFF_DATE_LINE.findall(raw)
 if len(dates)!=1:out.append(f'CITATION.cff date-released lines={len(dates)} expected=1')
 parsed=None
 if len(dates)==1:
  text=dates[0].decode('ascii')
  try:
   parsed=datetime.datetime.strptime(text,'%Y-%m-%d').date()
   if parsed.strftime('%Y-%m-%d')!=text:
    out.append(f'CITATION.cff date-released={text!r} does not round-trip');parsed=None
  except ValueError:out.append(f'CITATION.cff date-released={text!r} is not a real calendar date')
 normalized=CFF_DATE_LINE.sub(CFF_PLACEHOLDER,raw)
 digest=hashlib.sha256(normalized).hexdigest()
 if digest!=CFF_NORMALIZED_SHA256:
  out.append(f'CITATION.cff normalized sha256={digest} expected={CFF_NORMALIZED_SHA256}')
 return parsed if len(out)==before else None
def _contract_violations(node,path,allowed_identities,out):
 """verification_contract records commands and conditions. It records no outcome."""
 if isinstance(node,dict):
  for key,item in node.items():
   if key.lower() in CONTRACT_FORBIDDEN_KEYS:out.append(f'{_child(path,key)} is a measured outcome and must not appear in verification_contract')
   _contract_violations(item,_child(path,key),allowed_identities,out)
  return
 if isinstance(node,list):
  for index,item in enumerate(node):_contract_violations(item,f'{path}[{index}]',allowed_identities,out)
  return
 if type(node) is str:
  for token in HEX_TOKEN.findall(node):
   if token.lower() not in allowed_identities:out.append(f'{path} carries digest-shaped text {token!r} that the audit does not pin as a fixed identity')
  for token in DATE_TOKEN.findall(node):out.append(f'{path} carries a date {token!r}; verification_contract records no measured timestamp')
  return
 out.append(f'{path}={node!r} is a {type(node).__name__}; verification_contract carries no measured value')
CANONICAL_ZIP='square-riesz-polarization-certificates-v1.0.2.zip'
CANONICAL_ATTESTATION='square-riesz-polarization-certificates-v1.0.2.publication-attestation.json'
FROZEN_ANCHOR_COMMIT='d92992101ca45a5cd755b8d962652ab7e4329973'
CANDIDATE_BASE_COMMIT='2adfffb7dc68f40ea52fd1ed78bc2f11a46de78b'
MERGE_FIRST_PARENT_PIN='2146eba2e3cf8ac7dd873365856b58c5cee0d362'
# The exact text verification_contract must carry. A field pinned to its own
# literal cannot grow a measured count in the middle of a sentence, which is
# what a type-only rule allowed.
CONTRACT_WHAT_THIS_IS='The checks that must be run against this candidate and the condition each one must meet. It records no result. Whether they passed is a measurement, and a measurement of a working tree cannot be stated by a file inside that tree without changing it.'
CONTRACT_WHERE_RESULTS_LIVE="The external execution evidence carries the raw log of every command below and a machine-readable summary derived from those logs. Release-time facts are carried by the publication-attestation asset and by GitHub's generated release attestation."
CONTRACT_WHY_NO_COUNTS='A count written here is not checked by anything that runs. Recording verifiers, certified corpus files, configurations or unit tests in this file produced numbers that stayed true only until the next change, and every gate accepted them once they were wrong. The commands below already fail closed on the conditions those numbers were standing in for.'
CONTRACT_REQUIRED_PYTHON='3.13'
CONTRACT_ENFORCED_BY='scripts/check_release.py'
#: The command list is stated once, in CONTRACT_COMMANDS below, and everything
#: else derives from it. REQUIRED_COMMANDS used to be a second copy: two lists of
#: one boundary, where editing one and not the other changed nothing visible.
#: CONTRACT_MIGRATIONS records the canonical digest of the list at each version,
#: so a change without a version bump is a silent rewrite and is refused, while a
#: change with one is an ordinary migration.
CONTRACT_VERSION='1'
#: R17 kept a bare {version: digest} map, which made the map itself rewritable:
#: changing the command list and the digest under the same version left nothing
#: to disagree with. Each version now records what it came from and why, so a
#: rewrite has to falsify the chain as well as the entry, and the auditor's
#: requirements hold the digest for the version in force.
CONTRACT_MIGRATIONS={
 '1':{'commands_sha256':'bf97571fd46e80b183cf3c2232065b5c83752c1f60b37a1d194e6b449d5ac7a7',
      'previous_commands_sha256':None,
      'command_count':12,
      'reason':'initial verification contract: twelve commands recorded with their success conditions and no measured outcome'},
}
def _contract_history_violations():
 """The contract history must be append-only and must chain.

 Same shape as the CFF profile history, and for the same reason: a version
 boundary that can be rewritten is not a boundary. This cannot stop a rewrite
 of the entry and the list together -- the auditor's requirements do that --
 but it does stop a history that no longer describes how this list came to be.
 """
 out=[]
 versions=sorted(CONTRACT_MIGRATIONS,key=int)
 if CONTRACT_VERSION not in CONTRACT_MIGRATIONS:
  out.append(f'CONTRACT_VERSION={CONTRACT_VERSION!r} has no entry in CONTRACT_MIGRATIONS')
 if versions!=[str(n) for n in range(1,len(versions)+1)]:
  out.append(f'contract versions are not 1..n without gaps: {versions}')
 previous=None
 for version in versions:
  entry=CONTRACT_MIGRATIONS[version]
  if not isinstance(entry,dict):
   out.append(f'contract version {version} is not an object');break
  if entry.get('previous_commands_sha256')!=previous:
   out.append(f'contract version {version} does not chain: '
              f'previous={entry.get("previous_commands_sha256")} expected={previous}')
  if not entry.get('reason'):out.append(f'contract version {version} records no reason')
  previous=entry.get('commands_sha256')
 return out
issues.extend(_contract_history_violations())
def _canonical_commands(commands):
 return json.dumps(commands,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
CONTRACT_COMMANDS=[
  {'command':'python3 -B -m unittest discover -s tests -v','success':'exit 0 with no failure, error or unexpected success'},
  {'command':'python3 -B scripts/check_frozen_corpus.py --expect-base-version v1.0.1 --expect-base-commit d92992101ca45a5cd755b8d962652ab7e4329973 --require-git-anchor','success':'exit 0; every frozen-corpus path agrees with the anchored blob in file type, Git mode and content, and the anchor is verified rather than reported unverifiable'},
  {'command':'python3 -B scripts/verify_manifest.py','success':'exit 0 with no missing, unexpected or bad-hash entry'},
  {'command':'python3 -B scripts/check_release.py','success':'exit 0 with no issue reported'},
  {'command':'python3 -B scripts/check_semantic_consistency.py','success':'exit 0 with no problem reported'},
  {'command':'python3 -B scripts/regenerate_certified_results.py --check','success':'exit 0 with no difference between the regenerated and the committed tables'},
  {'command':'python3 -B scripts/audit_upper_witness.py --quiet','success':'exit 0 with no published decimal below the exact potential at its witness point'},
  {'command':'python3 -B scripts/verify_one.py --n 15 --method both','success':'exit 0 and both methods certify'},
  {'command':'python3 -B scripts/verify_all.py --quick --jobs 2','success':'exit 0 and every verifier in the quick set certifies'},
  {'command':'python3 -B scripts/verify_all.py --all --jobs 2 --output-dir <SCRATCH>','success':'exit 0; the discovered configurations equal the published set exactly and every verifier certifies with none failed and none timed out'},
  {'command':'python3 -B scripts/validate_replay_output.py <SCRATCH> --expect-all','success':'exit 0 with no problem reported and the full expected file inventory present'},
  {'command':'git --no-replace-objects diff --check','success':'exit 0 with no whitespace error'},
 ]
REQUIRED_COMMANDS=[entry['command'] for entry in CONTRACT_COMMANDS]
CONTRACT_FORBIDDEN_OUTCOMES=[
  'source_git_dirty',
  'source_git_clean',
  'verifiers',
  'certified',
  'failed',
  'timed_out',
  'validator_problems',
  'unit_tests',
  'run, artifact, Release and asset identifiers',
  'measured digests and measured timestamps',
 ]
# One statement of the manifest-binding boundary, read by AUDIT_SCHEMA and by
# the field-by-field comparison further down.
BINDING_VALUES={'authoritative_field':'internal_manifest.sha256','carrier_scope':'all_release_paths_file_bytes_and_decoded_json_keys_and_strings','digest_text_equivalence':'case_insensitive_hex','duplicate_current_digest_fields':'forbidden','production_gate':'scripts/check_release.py'}
# The builder's environment policy is machine-readable: these are the variables
# and settings the archive build fixes and drops, not a description of them. A
# type-only rule let the audit drift from the builder it describes.
BUILDER_ATTRIBUTE_SOURCES=[
  "GIT_ATTR_NOSYSTEM=1",
  "core.attributesFile=/dev/null",
  "GIT_CONFIG_GLOBAL=/dev/null",
  "GIT_CONFIG_SYSTEM=/dev/null",
  "GIT_CONFIG_* removed",
  "GIT_ATTR_SOURCE removed",
  "non-empty .git/info/attributes refused",
 ]
BUILDER_ENVIRONMENT_FIXED=[
  "TZ=UTC",
  "LC_ALL=C",
  "LANG=C",
  "GIT_NO_REPLACE_OBJECTS=1",
  "GIT_ATTR_NOSYSTEM=1",
  "GIT_CONFIG_GLOBAL=/dev/null",
  "GIT_CONFIG_SYSTEM=/dev/null",
 ]
BUILDER_ENVIRONMENT_DROPPED=[
  "GIT_DIR",
  "GIT_WORK_TREE",
  "GIT_INDEX_FILE",
  "GIT_OBJECT_DIRECTORY",
  "GIT_ALTERNATE_OBJECT_DIRECTORIES",
  "GIT_COMMON_DIR",
  "GIT_NAMESPACE",
  "GIT_SHALLOW_FILE",
  "GIT_REPLACE_REF_BASE",
  "GIT_ATTR_SOURCE",
  "all GIT_CONFIG_*",
 ]
BUILDER_RECORD_ADDED_IN_V4=[
  "head_commit, required to equal target_commit",
  "builder_script_blob_oid and builder_script_mode",
  "builder_script_target_sha256 and builder_script_executed_sha256",
  "builder_script_matches_target",
  "output_inventory, the exact three published file names",
 ]
AUDIT_SCHEMA={
 'schema_version':3,
 'release_version':TEXT,
 'audit_type':'static_release_candidate',
 'status':'PASS_LOCAL_CANDIDATE_NOT_PUBLICATION_ATTESTATION',
 'what_this_file_is':TEXT,
 'what_this_file_cannot_contain':TEXT,
 'candidate_date_utc':'2026-08-08',
 'candidate_base_commit':CANDIDATE_BASE_COMMIT,
 'frozen_anchor_commit':FROZEN_ANCHOR_COMMIT,
 'frozen_anchor_version':'v1.0.1',
 'internal_manifest':{'policy':'MANIFEST_POLICY.json','entry_count':COUNT,'sha256':TEXT,'note':TEXT},
 'verification_contract':{
  'what_this_is':CONTRACT_WHAT_THIS_IS,
  'where_the_results_live':CONTRACT_WHERE_RESULTS_LIVE,
  'why_no_counts_here':CONTRACT_WHY_NO_COUNTS,
  'verification_contract_version':CONTRACT_VERSION,
  'required_python':CONTRACT_REQUIRED_PYTHON,
  'commands':('list',{'command':TEXT,'success':TEXT},CONTRACT_COMMANDS),
  'outcomes_that_must_not_appear_here':('list',TEXT,CONTRACT_FORBIDDEN_OUTCOMES),
  'enforced_by':CONTRACT_ENFORCED_BY},
 'dynamic_publication_attestation':{
  'location':TEXT,'generator':'scripts/build_publication_attestation.py',
  'embedded_in_source_tree':False,'not_the_release_body':TEXT,'reason':TEXT,
  'fields_recorded_there':('list',TEXT,None),'not_recordable_even_there':TEXT,
  'release_assets':{'distribution':('list',TEXT,[CANONICAL_ZIP,CANONICAL_ZIP+'.sha256']),
                    'auxiliary_integrity':('list',TEXT,[CANONICAL_ATTESTATION])},
  'build_record_embedded':True,'build_record_preimage':TEXT},
 'canonical_asset_builder':{
  'path':'scripts/build_release_assets.py','tests':'tests/test_release_assets.py',
  'generation_semantics':TEXT,'exact_tag_binding':TEXT,'archive_equals_tree':TEXT,
  'attribute_sources_neutralised':('list',TEXT,BUILDER_ATTRIBUTE_SOURCES),'transactional':TEXT,
  'public_record_redaction':TEXT,'determinism_boundary':TEXT,'target_sensitivity':TEXT,
  'environment_fixed':('list',TEXT,BUILDER_ENVIRONMENT_FIXED),'environment_dropped':('list',TEXT,BUILDER_ENVIRONMENT_DROPPED),
  'atomic_publication':TEXT,'expected_digest_gate':TEXT,
  'build_record':{'path':TEXT,'schema':'square-riesz-release-asset-build.v4','note':TEXT,
                  'added_in_v4':('list',TEXT,BUILDER_RECORD_ADDED_IN_V4),'archive_command_source':TEXT},
  'builder_source_binding':TEXT,
  'exit_codes':{'0':TEXT,'2':TEXT,'3':TEXT},
  'commit_point_boundary':TEXT,'renamed_directory_identity':TEXT},
 'repository_url':'https://github.com/Driedsandwich/square-riesz-polarization-certificates',
 'excluded_from_internal_manifest':('list',TEXT,['PUBLICATION_AUDIT.json','SHA256SUMS','human-facing documentation','GitHub automation']),
 'publication_attestation_generator':{
  'path':'scripts/build_publication_attestation.py','tests':'tests/test_publication_attestation.py',
  'output_asset':CANONICAL_ATTESTATION,'inputs':('list',TEXT,None),
  'status_emitted':'PRE_PUBLICATION_DISTRIBUTION_ASSETS_VERIFIED','note':TEXT,
  'record_contract':TEXT,'release_relations':TEXT,
  'exit_codes':{'0':TEXT,'2':TEXT,'3':TEXT},
  'draft_asset_inventory':TEXT,'commit_point_boundary':TEXT},
 'candidate_scope_and_date':{'changed_paths':TEXT,'candidate_date':TEXT,'publication_date':TEXT},
 'release_engineering_remediation':{
  'date_utc':TEXT,'base_commit':MERGE_FIRST_PARENT_PIN,
  'scope':'Release-engineering-only follow-up after the substantive candidate audit; no mathematical corpus, result table, certifier, configuration or historical evidence changed.',
  'finding':TEXT,'merge_first_parent_pin':MERGE_FIRST_PARENT_PIN,
  'obsolete_pin_refused':CANDIDATE_BASE_COMMIT,'candidate_date_note':TEXT,
  'manifest_binding':dict(BINDING_VALUES)},
}
def _digest_text_occurrences(value,target):
 return value.lower().count(target) if type(value) is str else 0
def _matching_digest_paths(value,target,path='$'):
 out=[]
 if isinstance(value,dict):
  for key,item in value.items():
   child=f"{path}.{key}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key) else f"{path}[{key!r}]"
   key_count=_digest_text_occurrences(key,target)
   if key_count:out.append(f'{path}<key:{key!r}>:{key_count}')
   out.extend(_matching_digest_paths(item,target,child))
 elif isinstance(value,list):
  for index,item in enumerate(value):out.extend(_matching_digest_paths(item,target,f"{path}[{index}]") )
 else:
  count=_digest_text_occurrences(value,target)
  if count:out.append(f'{path}:{count}')
 return out
def _manifest_digest_carriers(target):
 marker=target.encode('ascii')
 carriers=[]
 for candidate in sorted(ROOT.rglob('*')):
  relative=candidate.relative_to(ROOT)
  if '.git' in relative.parts:continue
  relative_text=relative.as_posix()
  path_count=relative_text.lower().count(target)
  if path_count:carriers.append(f'path:{relative_text}:{path_count}')
  if relative_text=='PUBLICATION_AUDIT.json' or not candidate.is_file():continue
  try:data=candidate.read_bytes()
  except OSError as exc:
   issues.append(f'could not inspect manifest-digest carrier {relative}: {exc}')
   continue
  count=data.lower().count(marker)
  if count:carriers.append(f'bytes:{relative_text}:{count}')
 return carriers
manifest_bytes=(ROOT/'SHA256SUMS').read_bytes()
actual_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest()
actual_manifest_entries=sum(1 for line in manifest_bytes.decode('utf-8').splitlines() if line.strip())
declared_version=(ROOT/'VERSION').read_text().strip()
citation_day=_cff_date_released((ROOT/'CITATION.cff').read_bytes(),issues)
changelog_dates=re.findall(r'^## '+re.escape(declared_version)+r' — ([0-9-]+)\s*$',(ROOT/'CHANGELOG.md').read_text(),re.MULTILINE)
if len(changelog_dates)!=1:issues.append(f'CHANGELOG.md "## {declared_version}" headings={len(changelog_dates)} expected=1')
changelog_day=_calendar_date(changelog_dates[0],f'CHANGELOG.md {declared_version} heading') if len(changelog_dates)==1 else None
if citation_day is None:issues.append('CITATION.cff publishes no readable date-released; the publication date cannot be compared')
elif changelog_day and citation_day!=changelog_day:issues.append(f'publication date disagrees: CITATION.cff date-released={citation_day.isoformat()} CHANGELOG.md heading={changelog_day.isoformat()}')
try:
 audit=json.loads((ROOT/'PUBLICATION_AUDIT.json').read_text(),object_pairs_hook=_strict_object,parse_constant=_reject_constant,parse_float=_strict_float)
except (OSError,UnicodeError,json.JSONDecodeError,ValueError) as exc:
 issues.append(f'PUBLICATION_AUDIT.json is not strict JSON: {exc}')
else:
 if not isinstance(audit,dict):issues.append('PUBLICATION_AUDIT.json top level is not an object')
 else:
  schema_issues=[]
  _check_node(audit,AUDIT_SCHEMA,'$',schema_issues)
  for problem in schema_issues:issues.append(f'PUBLICATION_AUDIT schema: {_render_diag(problem)}')
  contract=audit.get('verification_contract')
  if contract is None:issues.append('PUBLICATION_AUDIT verification_contract is absent')
  else:
   pinned={value.lower() for value in (audit.get('candidate_base_commit'),audit.get('frozen_anchor_commit')) if type(value) is str}
   remediation_block=audit.get('release_engineering_remediation')
   if isinstance(remediation_block,dict):
    pinned|={value.lower() for key,value in remediation_block.items() if type(value) is str and key in ('base_commit','merge_first_parent_pin','obsolete_pin_refused')}
   contract_issues=[]
   _contract_violations(contract,'$.verification_contract',pinned,contract_issues)
   for problem in contract_issues:issues.append(f'PUBLICATION_AUDIT contract: {problem}')
   entries=contract.get('commands') if isinstance(contract,dict) else None
   declared_commands=[entry.get('command') for entry in entries if isinstance(entry,dict)] if isinstance(entries,list) else None
   if declared_commands!=REQUIRED_COMMANDS:issues.append(f'PUBLICATION_AUDIT verification_contract.commands={declared_commands!r} expected={REQUIRED_COMMANDS!r}')
   # Named for what it is. An earlier spelling of this reused declared_version,
   # which further down holds the contents of the VERSION file, and the release
   # version comparison started reporting an integer.
   declared_contract_version=contract.get('verification_contract_version') if isinstance(contract,dict) else None
   if declared_contract_version!=CONTRACT_VERSION:issues.append(f'PUBLICATION_AUDIT verification_contract_version={declared_contract_version!r} expected={CONTRACT_VERSION}')
   pinned_entry=CONTRACT_MIGRATIONS.get(CONTRACT_VERSION) or {}
   pinned_digest=pinned_entry.get('commands_sha256')
   if pinned_entry.get('command_count')!=len(CONTRACT_COMMANDS):issues.append(f'verification_contract command_count={len(CONTRACT_COMMANDS)} expected={pinned_entry.get("command_count")} for version {CONTRACT_VERSION}')
   actual_digest=hashlib.sha256(_canonical_commands(CONTRACT_COMMANDS)).hexdigest()
   if actual_digest!=pinned_digest:issues.append(f'verification_contract command list digest={actual_digest} expected={pinned_digest} for version {CONTRACT_VERSION}; a changed list needs a new version and a migration entry')
   declared_digest=hashlib.sha256(_canonical_commands(entries if isinstance(entries,list) else [])).hexdigest()
   if declared_digest!=pinned_digest:issues.append(f'PUBLICATION_AUDIT verification_contract.commands digest={declared_digest} expected={pinned_digest}')
  if audit.get('release_version')!=declared_version:
   # Outside the schema walk, so it had no machine-readable half at all and a
   # control that falsified it could not be attributed to anything.
   _release=[]
   _diag(_release,'audit.release_version','$.release_version',
         f'PUBLICATION_AUDIT release_version={audit.get("release_version")!r} VERSION={declared_version!r}')
   issues.append(_render_diag(_release[0]))
  candidate_day=_calendar_date(audit.get('candidate_date_utc'),'PUBLICATION_AUDIT candidate_date_utc')
  remediation=audit.get('release_engineering_remediation')
  if isinstance(remediation,dict):
   remediation_day=_calendar_date(remediation.get('date_utc'),'PUBLICATION_AUDIT release_engineering_remediation.date_utc')
   if candidate_day and remediation_day and remediation_day<candidate_day:issues.append(f'PUBLICATION_AUDIT release_engineering_remediation.date_utc={remediation.get("date_utc")!r} precedes candidate_date_utc={audit.get("candidate_date_utc")!r}')
  internal=audit.get('internal_manifest')
  if not isinstance(internal,dict):issues.append('PUBLICATION_AUDIT internal_manifest is not an object')
  else:
   if internal.get('sha256')!=actual_manifest_sha256:issues.append(f'PUBLICATION_AUDIT internal_manifest.sha256 does not match SHA256SUMS: recorded={internal.get("sha256")!r} actual={actual_manifest_sha256}')
   if type(internal.get('entry_count')) is not int or internal.get('entry_count')!=actual_manifest_entries:issues.append(f'PUBLICATION_AUDIT internal_manifest.entry_count={internal.get("entry_count")!r} actual={actual_manifest_entries}')
   if internal.get('policy')!='MANIFEST_POLICY.json':issues.append(f'PUBLICATION_AUDIT internal_manifest.policy={internal.get("policy")!r} expected=MANIFEST_POLICY.json')
  if not isinstance(remediation,dict):issues.append('PUBLICATION_AUDIT release_engineering_remediation is not an object')
  else:
   binding=remediation.get('manifest_binding')
   if not isinstance(binding,dict):issues.append('PUBLICATION_AUDIT release_engineering_remediation.manifest_binding is not an object')
   else:
    # Kept for R14-comparable diagnostics. AUDIT_SCHEMA already refuses all five
    # falsifications on its own; both layers read BINDING_VALUES, so there is one
    # statement of the boundary and two places that enforce it.
    if set(binding)!=set(BINDING_VALUES):issues.append(f'PUBLICATION_AUDIT manifest_binding keys={sorted(binding)!r} expected={sorted(BINDING_VALUES)!r}')
    for field,expected in BINDING_VALUES.items():
     if binding.get(field)!=expected:issues.append(f'PUBLICATION_AUDIT manifest_binding.{field}={binding.get(field)!r} expected={expected}')
    if 'finalized_manifest_sha256' in binding:issues.append('PUBLICATION_AUDIT manifest_binding.finalized_manifest_sha256 must not duplicate internal_manifest.sha256')
  authority_paths=_matching_digest_paths(audit,actual_manifest_sha256)
  if authority_paths!=['$.internal_manifest.sha256:1']:issues.append(f'PUBLICATION_AUDIT manifest digest authority paths={authority_paths!r} expected=["$.internal_manifest.sha256:1"]')
  audit_digest_occurrences=(ROOT/'PUBLICATION_AUDIT.json').read_bytes().lower().count(actual_manifest_sha256.encode('ascii'))
  if audit_digest_occurrences!=1:issues.append(f'PUBLICATION_AUDIT manifest digest case-insensitive byte occurrences={audit_digest_occurrences} expected=1')
  other_carriers=_manifest_digest_carriers(actual_manifest_sha256)
  if other_carriers:issues.append(f'manifest digest appears outside PUBLICATION_AUDIT authority: {other_carriers!r}')
rows=list(csv.DictReader((ROOT/'data'/'certified-results.csv').open()))
if len(rows)!=44:issues.append(f'certified-results rows={len(rows)} expected=44')
cert_dirs=sorted((ROOT/'certifiers').glob('n*'))
if len(cert_dirs)!=44:issues.append(f'certifier dirs={len(cert_dirs)} expected=44')
for d in cert_dirs:
 for m in ('spectral','componentwise'):
  if not (d/f'{m}.py').is_file():issues.append(f'missing {d.name}/{m}.py')
rep=json.loads((ROOT/'evidence'/'full-cleanroom-replay'/'PUBLIC_REPO_FULL_REPLAY.json').read_text())
if rep.get('verifier_count')!=88 or rep.get('certified_count')!=88 or rep.get('failed_count')!=0:issues.append('full clean-room replay is not 88/88')
# The three counters above are only what the replay says about itself; the
# records must each be a success, and together exactly the 88 published scripts.
expected_scripts={certifier_relpath(n,m) for n in EXPECTED_NS for m in METHODS}
if len(expected_scripts)!=88:issues.append(f'expected script set has {len(expected_scripts)} entries, expected 88')
if len(rep['results'])!=88:issues.append(f'full clean-room replay has {len(rep["results"])} records, expected 88')
recorded=[r.get('repo_relative_script') for r in rep['results']]
for s in sorted({s for s in recorded if recorded.count(s)>1}):issues.append(f'duplicate replay record {s}')
for s in sorted(expected_scripts-set(recorded)):issues.append(f'no replay record for {s}')
for s in sorted(set(recorded)-expected_scripts,key=str):issues.append(f'unexpected replay record {s}')
for r in rep['results']:
 name=r.get('repo_relative_script')
 if r.get('status')!='CERTIFIED':issues.append(f'replay record {name} status={r.get("status")!r}, expected CERTIFIED')
 if type(r.get('return_code')) is not int or r.get('return_code')!=0:issues.append(f'replay record {name} return_code={r.get("return_code")!r}, expected 0')
 if r.get('timed_out') is not False:issues.append(f'replay record {name} timed_out={r.get("timed_out")!r}, expected false')
for r in rep['results']:
 p=ROOT/r['repo_relative_script']
 if not p.is_file():issues.append(f'missing replay script {p.relative_to(ROOT)}');continue
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 if h!=r['script_sha256']:issues.append(f'replay script hash mismatch {p.relative_to(ROOT)}')
for bad in ROOT.rglob('*'):
 if bad.is_file() and (bad.suffix=='.pyc' or '__pycache__' in bad.parts):issues.append(f'bytecode present: {bad.relative_to(ROOT)}')
print(f'certified_rows={len(rows)} certifier_dirs={len(cert_dirs)} replay={rep.get("certified_count")}/88 issues={len(issues)}')
if issues:
 print('\n'.join(issues));sys.exit(1)
