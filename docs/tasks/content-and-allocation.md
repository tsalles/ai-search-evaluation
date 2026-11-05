# Content and Allocation Tasks

Status: T08 to T13 complete  
Executed suite and calibration evidence is in [implementation progress](../implementation-progress.md). Test IDs below remain the behavioral contracts; source/test paths identify their implementations.

## T08 Compose consistent fictional facts

- Stories: US02, US05. Requirements: FR08. Prerequisites: T07.
- Scope: scenario-scoped synthetic ledger, draft fact references, deterministic materialization, typed table assembly, visible entity/validity context, and frozen shared facts. Do not add a retrieval answer-key export.
- Paths: `src\docgen\facts.py`, `src\docgen\composition.py`, `tests\test_fact_composition.py`.
- U08: repeated references materialize identical value/unit/display; unknown facts, contradictory shared values, bad validity intervals, unapproved quantitative additions, or unresolved tokens fail. Different hidden scenario IDs cannot justify contradictory claims about an indistinguishable visible entity.
- I08: two related fixtures use the same frozen scenario correctly; independent scenarios have distinguishable visible labels. Saved accepted JSON has exact typed table values and no unresolved placeholders.
- Acceptance: all business values have a traceable consistency source; free-form plausibility remains a declared human-review responsibility.
- Completion: shared/scenario facts, reference materialization, typed cell associations, visible entities, and invalid/conflicting facts are covered by the composition tests. Pilot regressions cover localized thousands separators and adjacent repeated units.

## T09 Enforce language, length, genre, and profiles

- Stories: US01, US02, US05. Requirements: FR03, FR09. Prerequisites: T08.
- Scope: versioned authoring prompt, audience/terminology controls, exact word counting, fixed-seed local language detection, and baseline/complex structure constraints.
- Paths: `src\docgen\prompts.py`, `src\docgen\profiles.py`, `src\docgen\quality.py`, `tests\test_quality_controls.py`.
- U09: word counts at min/max pass and one below/above fails; tables/lists count and banners/provenance do not. Portuguese fixtures pass and English fixtures fail the base-language gate; confidence boundaries are explicit.
- I09: procedure with four steps, FAQ with three pairs, insufficient comparison table, unknown structure, broken heading order, or missing required term is rejected. Valid fixtures for all four genres and both profiles pass.
- Acceptance: profile controls produce measurable local checks without claiming automated regional-dialect or semantic verification; no provider sampling option is sent without capability support.
- Completion: exact word boundaries, both profiles, all genres, language/confidence controls, required terms, and prompt context pass. Authoring prompt version 3 includes the recorded linguistic QA guidance.

## T10 Enforce acceptance and lexical uniqueness

- Stories: US02, US05. Requirements: FR10, FR11. Prerequisites: T09.
- Scope: exact normalized business-payload fingerprints, five-word shingle similarity, aggregate quality verdicts, and deterministic rejection/retry reasons.
- Paths: `src\docgen\uniqueness.py`, `src\docgen\quality.py`, `tests\test_uniqueness.py`, `tests\test_generate_phase.py`.
- U10: payload copies differing only in IDs/banners/whitespace are exact duplicates; meaningful changed values remain represented in the fingerprint. Fixtures below/at/above Jaccard 0.85 verify the inclusive threshold.
- P10: acceptance matches an independent exhaustive pairwise shingle oracle for small sets; title changes or reordered metadata cannot conceal duplicate business payloads.
- I10: duplicate rejection consumes a quality candidate, never creates a second accepted item, and exhausts with a visible failed slot. A shuffled response-completion order does not change which fixed candidate wins.
- Acceptance: all configured checks must pass; no silent threshold relaxation, blank replacement, or semantic-uniqueness claim.
- Completion: exact normalized and inclusive five-word-shingle Jaccard guards match independent rational/pairwise oracles. Multi-item tests prove deterministic acceptance and visible exhaustion.

## T11 Complete standalone Phase 1

- Stories: US02, US04. Requirements: FR11, FR12. Prerequisites: T10, T05.
- Scope: N-slot orchestration, ordered acceptance, persisted candidate attempts/provenance, content-quality report, and content-ready barrier.
- Paths: `src\docgen\generation.py`, `src\docgen\pipeline.py`, `tests\test_generate_phase.py`.
- U11: success requires exactly N accepted slots; one terminal slot makes the operation incomplete. Attempt/quality/usage summaries retain their documented distinctions.
- I11: multiple topics/genres/lengths produce exact planned margins; restart reuses all accepted hashes and calls the provider only for unfinished slots; Phase 1 creates no final documents or format assignments.
- Acceptance: a fresh invocation can consume the saved run for Phase 2 with generation entirely disconnected.
- Completion: standalone generation, retained accepted hashes, request/candidate exhaustion, cancellation, real-SDK transport wiring, and actual Azure content are verified. No final documents are created by Phase 1.

## T12 Compute exact format quotas

- Stories: US03. Requirements: FR13. Prerequisites: T03.
- Scope: validated format shares and decimal largest-remainder allocation with ascending-key tie-breaking.
- Paths: `src\docgen\allocation.py`, `tests\test_format_quotas.py`.
- U12: N=7 and PDF/DOCX/MD shares 0.5/0.3/0.2 produce 4/2/1; N=1 at PDF=0.6, DOCX=0.4 produces 1/0; an exact tie follows the canonical key rule.
- P12: for generated valid mixes and N=1..1000, quotas are nonnegative, sum to N, match floor/ceiling ideals, and give zero to zero shares. Reject all-zero, bad totals, unknown keys, Boolean, NaN/infinite/negative/over-one values.
- I12: dry-run and actual allocation use the same quota result and report representation warnings.
- Acceptance: no probabilistic count drift or arbitrary normalization; accepted tolerance-only normalization is visible in the report.
- Completion: 14 initial format-quota cases/properties passed, including a 150-example independent rational oracle and N up to 1,000. All 128 then-implemented tests passed before T06. Later T13 tests extend this module with the balanced assignment solver.

## T13 Balance and freeze format assignment

- Stories: US03, US05. Requirements: FR14. Prerequisites: T12, T11.
- Scope: topic/length strata, exact global margins, integer-scaled minimum-cost transportation, seeded tie resolution, immutable assignments, and balance report.
- Paths: `src\docgen\allocation.py`, `src\docgen\store.py`, `tests\test_stratified_assignment.py`.
- U13: sparse/empty strata, one format, one item, highly skewed shares, and solver failure produce the documented result or explicit failure without creating artifacts.
- P13: every item appears once; row sums and format margins are exact; objective equals exhaustive optimal assignments for small N; same seed/version/content plan reproduces assignments. Multiple seeds may change ties, never quotas or the optimal primary objective.
- I13: persist then reopen an allocation; changed weights/content hash/semantic configuration are rejected. Balance reports expose per-cell deviations and unrepresented groups rather than creating duplicate content.
- Acceptance: assignments are frozen before any renderer executes; there is no random fallback if the balance solver fails.
- Completion: two-/three-format exhaustive optimality oracles, seeded exact margins, sparse diagnostics, solver failures, and immutable persisted-allocation tests pass.
