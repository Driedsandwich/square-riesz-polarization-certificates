# Errata for v1.0.0 and v1.0.1

**Status: implemented on `main` by merge commit
`2adfffb7dc68f40ea52fd1ed78bc2f11a46de78b`, and carried by the `v1.0.2`
corrective patch release.** Whether that Release exists is answered by GitHub,
not by this file: if GitHub reports the `v1.0.2` Release as published and
immutable, the corrected values below are the published ones; otherwise the
values published under `v1.0.0` and `v1.0.1` are still the ones in circulation.
The `v1.0.0` and `v1.0.1` tags, Releases and assets are unchanged either way.

This errata has two independent items:

1. **an arithmetic correction** to the published upper witness decimals of 18
   configurations, and the `interval_width` that follows from them;
2. **a wording clarification** of the descriptive `symmetry_or_family` field of
   two configurations, which is not a bound and changes no number.

They are separate: item 1 is a defect in a value that a reader may rely on,
item 2 is a defect in prose that was never load-bearing.

---

# Item 1 — arithmetic correction to the upper witness decimals

## What was wrong

`rigorous_upper_witness` is documented as an upper bound for the minimum of the
potential: the exact rational value of the potential at the configuration's upper
witness point, presented as a decimal. In `v1.0.0` and `v1.0.1` that decimal was
produced by rounding **to nearest** rather than outward. Whenever the first
dropped digit was below 5, the published decimal came out *below* the exact
value, and a number below the exact value is not an upper bound.

Recomputing all 44 rows in exact rational arithmetic from the published
coordinates shows **18 of 44** rows were affected. In every affected
row the published decimal was short by less than one unit in its last place, so
the correction is `+1` in the final digit and nothing else.

## What was *not* wrong

- The fixed configuration coordinates are unchanged, byte for byte.
- The certified lower bounds are unchanged.
- The branch-and-bound logic of both certifier families is unchanged.
- The upper witness points are unchanged.
- The exact potential at each witness point was, and remains, a valid upper
  bound. The defect was confined to its decimal presentation.
- The stored clean-room replay evidence is unchanged and still reproduces.

Raising the published upper value widens the enclosure
`[certified_lower_bound, rigorous_upper_witness]` by less than one unit in the
last published place. Stated precisely: the correction **slightly weakens the
tightness of the upper enclosure**, **restores its rigour** — the previous
decimal was not an upper bound at all — and **leaves the lower-bound
certificate unchanged**.

## Affected configurations

n = 8, 15, 18, 19, 20, 24, 26, 27, 29, 30, 32, 35, 36, 39, 43, 45, 46, 47

| n | published in v1.0.0 / v1.0.1 | corrected | published value fell short by |
| --- | --- | --- | --- |
| 8 | `47.83910647844590952575099945479720352076697462477898666567915612063995` | `47.83910647844590952575099945479720352076697462477898666567915612063996` | 4.8733e-69 |
| 15 | `115.163545738140865425310886989792958990774562099421856468660672334475379483037735242850051` | `115.163545738140865425310886989792958990774562099421856468660672334475379483037735242850052` | 4.3344e-88 |
| 18 | `147.3404290637407826582944090544740390291630269181014741302042218693484` | `147.3404290637407826582944090544740390291630269181014741302042218693485` | 3.6453e-69 |
| 19 | `159.3798180108150558420404929931202685738003114741025154348296294288467` | `159.3798180108150558420404929931202685738003114741025154348296294288468` | 1.8342e-68 |
| 20 | `174.6555982593057947522924944089833286212830318071207571654947266038656` | `174.6555982593057947522924944089833286212830318071207571654947266038657` | 1.8704e-68 |
| 24 | `219.1523530495103096312892454588488799213178617070040809399843047120468` | `219.1523530495103096312892454588488799213178617070040809399843047120469` | 4.1185e-70 |
| 26 | `241.2679935270798353656508510373240714930662120471231004394166441389775` | `241.2679935270798353656508510373240714930662120471231004394166441389776` | 4.1123e-68 |
| 27 | `252.6452424116921305057358483145704448905819403893050567017529679123275` | `252.6452424116921305057358483145704448905819403893050567017529679123276` | 2.0546e-68 |
| 29 | `272.4959736464727481429440086732123476578222047663233015745527693010757` | `272.4959736464727481429440086732123476578222047663233015745527693010758` | 3.5693e-68 |
| 30 | `285.3267423835499873642554058977523665598752655409914105986540815282276` | `285.3267423835499873642554058977523665598752655409914105986540815282277` | 1.3090e-68 |
| 32 | `304.2807991298781185957603711717828645387668450389000369132224171444483590605624390003441085898303778` | `304.2807991298781185957603711717828645387668450389000369132224171444483590605624390003441085898303779` | 2.5655e-99 |
| 35 | `329.708966808635211631262588136276312845459070035093352818438400983573433466244801198883560` | `329.708966808635211631262588136276312845459070035093352818438400983573433466244801198883561` | 2.0718e-88 |
| 36 | `338.8859072386620636147954953852739303622711913241470814623722274862621226417423947542976411920704403` | `338.8859072386620636147954953852739303622711913241470814623722274862621226417423947542976411920704404` | 2.8623e-98 |
| 39 | `360.2833667511679034078744420016230881172589085477077488799663506802668` | `360.2833667511679034078744420016230881172589085477077488799663506802669` | 2.7200e-68 |
| 43 | `390.6283643450390038676817705483990028464831969997284287475540221010844` | `390.6283643450390038676817705483990028464831969997284287475540221010845` | 2.4398e-68 |
| 45 | `403.2479810710816605323014649212349728136516807409440258426997580492764` | `403.2479810710816605323014649212349728136516807409440258426997580492765` | 3.6641e-68 |
| 46 | `413.3754963758078948106825477009202620960977652363703137817493206121646` | `413.3754963758078948106825477009202620960977652363703137817493206121647` | 2.1282e-68 |
| 47 | `419.3108589936579161885156896545970298008536658723482581683873613485175` | `419.3108589936579161885156896545970298008536658723482581683873613485176` | 2.6540e-68 |

The remaining 26 rows (n = 7, 10, 11, 12, 14, 16, 17, 21, 22, 23, 25, 28, 31, 33, 34, 37, 38, 40, 41, 42, 44, 48, 49, 50, 51, 52)
were already at or above the exact value and are unchanged.

`interval_width` changes in exactly the same 18 rows, by the same amount, because
it is the difference of the corrected upper bound and the unchanged lower bound.
**The arithmetic correction changed no other column**: `symmetry_or_family` in
two rows is changed by item 2 below, and nothing else in the table moved.

---

# Item 2 — wording clarification of `symmetry_or_family`

`symmetry_or_family` is **non-normative provenance prose**. It records where a
configuration came from. It is not a claim the certificates rest on, and no
check has ever derived anything from it.

Read as an exact statement about the published finite decimals, two entries
were wrong. The exact invariance of every configuration under the eight
symmetries of the square was recomputed in rational arithmetic
(`certificate_lib.exact_square_symmetries`):

| n | published in v1.0.0 / v1.0.1 | exact invariance of the published decimals |
| --- | --- | --- |
| 15 | `left-right reflection only` | identity only — the decimals are **not** exactly invariant under the left-right reflection |
| 16 | `none/full square (retained verifier)` | identity, `x -> 1-x`, `y -> 1-y` and 180-degree rotation — neither "none" nor "full square" |

Both entries now describe the provenance and the exact fact separately. No
coordinate, bound, witness point or certifier changed: this item changes two
strings in `data/results-metadata.json`, from which the result tables are
regenerated.

For n=15 the difference is small but real: the two members of each mirrored
pair sum to `0.99999999999999994` rather than to 1, so the reflection maps the
point set to a different set of rationals. The n=15 certifiers assert no
symmetry, so nothing in the proof relied on the claim.

The remaining 42 entries were checked against the same computation and are not
contradicted by it. `symmetry_or_family` remains prose, and no check enforces
it; `tests/test_followup_hardening.py` pins the exact classification of n=15
and n=16 so the two corrected statements cannot silently drift back.

## How this is prevented from recurring

- `scripts/regenerate_certified_results.py` is now the only way these tables are
  produced. The upper bound is computed, rounded outward with integer arithmetic,
  and never typed in.
- `scripts/audit_upper_witness.py` recomputes all 44 rows exactly and exits
  non-zero if any published decimal is below its exact value.
- `scripts/check_semantic_consistency.py` enforces the same inequality, and
  `tests/test_upper_witness.py` pins the n=15 case in both directions: the old
  decimal must be rejected and the corrected one accepted.
- Both checks run in CI on every push and pull request.

See [data-schema.md](data-schema.md) for the full rounding policy.
