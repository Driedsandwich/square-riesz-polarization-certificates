# Proposed certifier changes (not applied)

The 88 certifiers under `certifiers/` and the stored evidence under `evidence/`
are frozen: their bytes are pinned by the v1.0.1 commit and tag objects
(`docs/frozen-corpus.md`), by the script SHA-256 values recorded in every replay,
and by the saved and clean-room replay logs. The defect below can only be
fixed by changing certifiers, so it is recorded here as a proposal for a
future research release rather than fixed in place. What this release does
instead is stated with it.

## P1 — reflection symmetry must not depend on `assert`

**Defect.** The certifiers for n=18, 20 and 22–52 (both methods, 66 files)
search only `[0,1/2]^2`. The extension to the unit square rests on

```python
assert {(ONE-x,y) for x,y in LIGHT_SET} == LIGHT_SET
assert {(x,ONE-y) for x,y in LIGHT_SET} == LIGHT_SET
```

which `python -O` and `PYTHONOPTIMIZE` remove. The positivity precondition in
`divide_by_positive_interval` (38 componentwise certifiers) and the closing
re-checks are `assert` statements too.

**Proposal.** Replace each of these with an explicit test that raises, e.g.

```python
if {(ONE-x,y) for x,y in LIGHT_SET} != LIGHT_SET:
    raise SystemExit("configuration is not left-right symmetric")
```

and have `main()` exit non-zero, without printing `status: CERTIFIED`, when a
closing check fails.

**Coordinated changes required.**
- New script SHA-256 values for every edited certifier, a new frozen-corpus
  baseline and release anchor, and a fresh full replay to replace the stored
  evidence that names the old hashes.
- `certificate_lib._CertifierReader` evaluates module-level `assert` statements
  and accepts only an allow-listed set of module statements; an `if ...: raise`
  at module level is currently rejected as "module-level `if` other than the
  __main__ guard". It would have to learn the new form, the entry-point check
  (`_EntryPointChecker`) is likely to need the same review for any change to
  `main()`, and `check_semantic_consistency.py`'s assertion count would change.

**In this release instead.** `verify_one.py` and `verify_all.py` refuse to start
under `-O` or `PYTHONOPTIMIZE` and strip `PYTHONOPTIMIZE` from the child
environment (tested in `tests/test_success_contract.py` and
`tests/test_round7_hardening.py`); `check_semantic_consistency.py` evaluates the
module-level reflection statements statically; and README and
`docs/reproducibility.md` say not to run a certifier directly under `-O`.
