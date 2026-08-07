# Reproducibility

## Scope

The release reproduces and verifies the certificates, not the original exploratory search process. Optimization/search code, random seeds, and complete search transcripts are not included in v1.0.0.

## Integrity layers

`SHA256SUMS` covers the exact certificate and reproducibility corpus defined by `MANIFEST_POLICY.json`: certifiers, mathematical data, replay evidence, verification scripts, version metadata, and license files. Human-facing documentation and GitHub automation are intentionally outside that internal manifest.

The complete published Release ZIP, including documentation and automation files, is protected separately by the ZIP's external SHA-256 checksum. See `docs/manifest-policy.md`.

Regenerate and verify the internal manifest with:

```bash
python scripts/regenerate_manifest.py
python scripts/verify_manifest.py
```

## Exact certifiers

The exact lower-bound certifiers require Python 3.13 and the standard library only. Each script embeds the exact finite-decimal source coordinates as rational numbers and performs a rational branch-and-bound proof.

```bash
python -B scripts/verify_manifest.py
python -B scripts/verify_one.py --n 32 --method both
python -B scripts/verify_all.py --all --jobs 2 --output-dir replay-output
```

`verify_all.py` records one stdout file, one stderr file, one metadata JSON file per verifier, plus CSV/JSON summaries when `--output-dir` is supplied.

A run counts as certified only when the child process exits with code 0, does not time out, prints exactly one `status: CERTIFIED` line with no contradicting claim elsewhere in its output, **and reports the proof it performed**. A file whose entire content is `status: CERTIFIED` satisfies everything before that clause, so each successful run must also carry exactly one `target_decimal`, `splits`, `leaf_count`, `maximum_depth` and `minimum_leaf_lower_bound_decimal` line and one upper witness value line. The target must equal the certifier's `TARGET` as an exact rational, the three counts must be canonical non-negative integers with at least one leaf, the minimum leaf bound must be at least the target, and the upper witness value must reproduce the exact potential at that certifier's witness point, printed at that certifier's own precision. `certificate_lib.validate_proof_output` defines this once and every path that judges certifier output uses it, live or stored. Both replay scripts refuse to start under `python -O` or `PYTHONOPTIMIZE`, and remove `PYTHONOPTIMIZE` from the child environment, because optimisation would drop the `assert` statements with which each certifier re-checks its own certificate.

## Semantic checks

Beyond file counts and hashes, the following verify that every representation of the corpus says the same thing:

```bash
python -B scripts/check_frozen_corpus.py \
  --expect-base-version v1.0.1 \
  --expect-base-commit d92992101ca45a5cd755b8d962652ab7e4329973 \
  --require-git-anchor
python -B scripts/check_semantic_consistency.py
python -B scripts/regenerate_certified_results.py --check
python -B scripts/audit_upper_witness.py
python -B -m unittest discover -s tests
```

`check_semantic_consistency.py` compares the two certifiers of each configuration against each other and against `data/configurations/`, compares the CSV and JSON tables field by field as strings, recomputes every upper witness value in exact rational arithmetic, and re-derives the stored replay aggregates from the individual records. It reads the certifier constants by parsing the sources with a fail-closed AST allow-list; it never imports, executes or `eval`s a certifier. `check_frozen_corpus.py` reads the frozen file set out of the `v1.0.1` commit with `git ls-tree` and `git cat-file`, **with object replacement disabled** (`git --no-replace-objects`, `GIT_NO_REPLACE_OBJECTS=1`, `GIT_REPLACE_REF_BASE` dropped) and every batch response matched to the object id, type and size requested — `git replace` otherwise serves different bytes under an unchanged commit or blob name. It requires the raw release blobs, the in-tree baseline and the working tree to agree in content *and* in file mode, inventories the working tree with `lstat` so a symlink to an identical copy is not read through, and refuses a frozen root that is not a real directory. `--require-git-anchor` refuses to fall back to a baseline-only comparison, and treats an existing `refs/replace/` as a failure. `-B` keeps the tree free of `__pycache__`, which `check_release.py` treats as a packaging defect.

## What each layer does and does not establish

These are different claims and are worth keeping apart:

| Layer | Establishes | Does not establish |
| --- | --- | --- |
| **fixed-configuration lower-bound certificate** | for the exact published coordinates, the minimum of the potential over the whole unit square is at least the stated bound | anything about other configurations, or global optimality |
| **upper witness enclosure** | the minimum is at most the potential at one published point of `[0,1]^2` | that the point is optimal, or that the enclosure is tight |
| **historical replay evidence** (`evidence/`) | that a specific past run of specific bytes produced 88/88 `CERTIFIED` | that today's sources still behave that way |
| **fresh CI replay** | that today's sources, whose SHA-256 each record carries, produce 88/88 `CERTIFIED` now | anything about a source that was not run |
| **frozen corpus anchor** | that the 88 certifiers, the 44 configurations and the stored evidence are byte-identical, and mode-identical, to the **raw** objects of the `v1.0.1` commit — read with `git replace` disabled, from regular files only | that they were correct then — it pins the bytes, not the mathematics. In an archive with no `.git` it degrades to a baseline comparison and says so |
| **static source consistency checks** | that the sources, the data and the evidence still describe the same corpus, and that each certifier still has an entry point that runs its proof and asserts its own result | that the mathematics is correct — no static check verifies a bound |
| **runtime proof execution** | the certificates themselves | reproducibility of the original search |
| **non-normative descriptive metadata** | nothing; it is provenance prose | — |

The static entry-point check is a structural check against an inventory of the 88 certifiers in this repository, not a count of `certify()` calls somewhere in the tree. `main()` must open with `<name> = certify()` as a direct call with no arguments, compute the upper witness value at that certifier's own witness point as its second statement, bind nothing else, contain no `return`, `raise`, `try`, loop, lambda, nested definition or walrus, print its status as the proof's own verdict, and end with the four final assertions with nothing after them; `certify` and `main` must each be defined once at module level and never rebound. The module is also required to do nothing on import beyond binding values this checker can evaluate: no decorator anywhere, no `async`, no lambda, every function default a bare name or a plain constant, one `NamedTuple` class whose body is annotations only, and every module-level binding evaluable. Every clause is there because its absence was exploitable. A `certify()` call parked on the unexecuted arm of a conditional, a module-level `certify = lambda: ...` with `main()` untouched, a second `def certify`, an early `return` after printing the status, and a result variable overwritten after the call each ran to exit code 0 printing `status: CERTIFIED` while proving nothing — four of them in under 0.03 seconds against the real certifier's 14. So did `@skip_proof` on `certify`, a decorator on an unrelated helper that writes into `globals()`, a function default that calls `globals().__setitem__`, and a module-level assignment whose value the reader could not evaluate.

What this check does **not** establish is the mathematics. It confirms that `main()` calls `certify()`, keeps the result, and reaches the known output and assertion shapes; it does not confirm that `certify()` computes a valid bound. A body rewritten to `return CertificateResult(True, 0, 1, 0, TARGET, None, None)` satisfies all four final assertions, because `TARGET >= TARGET`. The immutability of the certifier's own bytes is what rules that out, and that is established by the frozen-corpus anchor against the **raw** `v1.0.1` objects — the entry-point check is defence in depth behind it, not the primary defence. A Git commit id is only a trust root when the objects under it are read with replacement disabled; naming the commit while following `git replace` establishes nothing.

## Validating a fresh replay

`verify_all.py --output-dir` refuses to write into a directory that already contains files, so stale logs cannot join a new run's evidence, and records `repo_relative_script` and `script_sha256` for every job. `validate_replay_output.py` re-derives the conclusion from those files rather than trusting the summary:

```bash
python -B scripts/verify_all.py --all --jobs 2 --output-dir <new-empty-dir>
python -B scripts/validate_replay_output.py <new-empty-dir> --expect-all
```

It recomputes each certifier's SHA-256, re-classifies each stdout/stderr pair through the same success contract, recomputes the aggregates from the individual records, compares every `summary.csv` cell with the corresponding `summary.json` value field by field, and requires the directory to hold exactly the expected files. A replay directory therefore contains only the files the run produced: a console transcript belongs beside it, not inside it.

The validator also reads what the run says about itself. `selection` names a
fixed configuration list — `all` means the 44 published sizes, `quick` means the
five in `certificate_lib.QUICK_NS` — and `expected_configurations` must be that
list, so a five-configuration run cannot be relabelled as a full one.
`generated_at_utc` is parsed as a real instant and re-rendered, not merely
matched against a pattern; `2026-99-99T99:99:99Z` matched the pattern.
`source_git_commit` must be null or 40 lowercase hex characters, and when the
source tree has a readable `.git`, it must be that tree's `HEAD`.

CI can say more than a local run can, and does:

```bash
python -B scripts/validate_replay_output.py ci-full-replay \
  --expect-all \
  --expect-source-commit "$GITHUB_SHA" \
  --expect-source-clean
```

`--expect-source-clean` is deliberately not applied to local evidence, which is
produced from an uncommitted working tree.

`source_git_commit` and `source_git_dirty` describe the **source tree before the run started**. They are read before the output directory is created, because an output directory inside a repository is untracked and would make every clean checkout report as dirty from its first written file onwards. A missing `.git`, a missing `git` binary or a failing command gives `null`, which is not the same as clean.

## A legacy boundary in the historical evidence

The published historical replay records store an empty string in
`minimum_leaf_lower_bound`, while the corresponding stdout log does carry a
`minimum_leaf_lower_bound_decimal:` line. That evidence is frozen and is not
rewritten to match the checker.

The checks therefore treat the two sides separately: the record's field is
required to be the empty string that the historical schema uses, and the log is
required to contain exactly one such line holding a valid finite decimal. The
two are never compared to each other, because an empty string and a number are
not the same value and pretending otherwise would be the kind of implicit
conversion these checks exist to prevent.

Everything else in a historical record *is* bound to its log: the record must
name `logs/nNN_<method>.stdout.txt` and `logs/nNN_<method>.stderr.txt` exactly —
not merely a file that exists — and its `status`, `splits` and `maximum_depth`
must be the values in that log. The `target_decimal` in the log is checked
against the certifier's `TARGET`, and the upper-bound line against the exact
potential recomputed at that configuration's witness point.

## Expected cost

In the v1.0.0 release replay, all 88 verifiers completed successfully. Individual runtimes varied from roughly one second to about one minute on the release-preparation environment. Parallel execution changes wall-clock time but not the proof result.

## Numerical analysis data

Candidate generation and local-minimum enumeration used optional scientific-Python dependencies listed in `requirements-analysis.txt`. These numerical analyses are not proof dependencies. The result table includes numerical local-minimum counts where available; full local-minimum coordinate lists are not included in v1.0.0. The exact lower-bound certificates do not rely on those counts.
