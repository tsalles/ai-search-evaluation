# Implementation Plan

Status: Technical implementation and T01 to T27 engineering evidence verified; external human approval is not recorded  
Version: 0.1  
Date: 2026-10-22  
Approved: 2026-10-23

## Approval and sequencing

[T00](tasks/foundation.md#t00-approve-the-implementation-baseline) is complete: the user approved the requirements, contracts, initial quality thresholds, and persistence/rendering ADRs on 2026-10-23. Start with T01 and work on one task at a time, following the dependencies below. List order is the recommended route, not an additional dependency.

Design approval does not assert that technical gates have passed or authorize paid live tests automatically. Keep those tests explicitly opt-in and bounded as documented.

Execution evidence is in [implementation progress](implementation-progress.md). L06, the final 12-document Azure pilot, 372 offline tests, actual Office/model QA, hard-process 1,000-document recovery, isolated installed-package workflows, and documentation traceability passed. Model QA found no blocking defect and disclosed minor linguistic/print-preview findings. Human corpus/release approval is not inferred from these technical results.

No effort estimate or delivery-date commitment is made. Tasks have bounded observable outcomes; a renderer task must not expand into other renderers or retrieval integration.

## Milestones and dependency graph

| Milestone | Tasks | Independently verifiable outcome |
|-----------|-------|---------------------------------|
| M0 | T00 to T04 | Approved baseline, working package, validated plan, one persisted item rendered to Markdown through the public API |
| M1 | T05 to T07 | Durable checkpoints and a bounded, verified Azure provider connection |
| M2 | T08 to T11 | Phase 1 alone produces N distinct accepted content items with quality evidence |
| M3 | T12 to T22 | Exact balanced allocation and an offline, validated six-format Phase 2 |
| M4 | T23 to T27 | Combined/resumable CLI, live pilot, scale evidence, and release documentation |

| Task | Scope | Prerequisites |
|------|-------|---------------|
| T00 | Approve baseline and ADRs | None |
| T01 | Package and executable test gates | T00 |
| T02 | Canonical contracts and fixtures | T01 |
| T03 | Configuration and dry-run planning | T02 |
| T04 | One-item Markdown tracer | T03 |
| T05 | Durable run store and ownership | T04 |
| T06 | Azure adapter and capability doctor | T05 |
| T07 | Bounded transport and resource controls | T06 |
| T08 | Fact-ledger composition | T07 |
| T09 | Language, genre, length, and profiles | T08 |
| T10 | Quality and uniqueness acceptance | T09 |
| T11 | Complete standalone Phase 1 | T10, T05 |
| T12 | Exact format quotas | T03 |
| T13 | Stratified immutable assignment | T12, T11 |
| T14 | Renderer contract and full Markdown | T04, T13 |
| T15 | Native HTML | T14 |
| T16 | Native DOCX | T14 |
| T17 | Native XLSX | T14 |
| T18 | Native PPTX | T14 |
| T19 | Native PDF | T14 |
| T20 | Complex layouts and continuation | T15, T16, T17, T18, T19 |
| T21 | Independent artifact/set validation | T20 |
| T22 | Standalone Phase 2 and publication | T21, T13, T05 |
| T23 | Combined execution and recovery | T11, T22, T07 |
| T24 | Complete CLI and audit contracts | T23 |
| T25 | Bounded live pilot and human review | T24 |
| T26 | Windows 1,000-document scale gate | T24 |
| T27 | Release/regression evidence and docs | T25, T26 |

See the task contracts in [foundation](tasks/foundation.md), [content and allocation](tasks/content-and-allocation.md), [rendering](tasks/rendering.md), and [orchestration and release](tasks/orchestration-and-release.md). Every task identifies user stories, requirements, source/test paths, test IDs, and an acceptance outcome.

## Per-task test-first procedure

1. Confirm prerequisites and the task's public contract.
2. Add only this slice's test cases and fixtures. Do not write all future implementation tests in advance.
3. Run the relevant test selector and capture the intended behavioral failure. Fix test setup errors before treating a failure as RED.
4. Implement the smallest complete behavior, including failure reporting and directly related documentation.
5. Run targeted tests, lint/type checks, then the full applicable offline suite and package gate.
6. Run any task-required live or human gate. A required gate that was not run is not green.
7. Refactor only while green, then rerun affected checks. Record evidence and mark the task complete.

When a check fails, stop the task, diagnose the cause, and add a reproducing regression test before fixing it. Do not skip, weaken, or delete a legitimate assertion to move to the next task.

T06 includes a minimal live capability check because the provider contract is not proven by deployment metadata. Later tasks remain offline unless provider/schema/prompt behavior changes or their task explicitly requires live acceptance. [Test strategy](test-strategy.md) defines paid-test boundaries.

## Definition of done

- The task's unit, integration, contract, and applicable property/failure tests pass.
- The entire implemented offline suite passes with no known regressions.
- Application code passes linting, typing, and the packaging checks relevant to the change.
- Public input/output shapes and errors match the versioned contracts.
- Tests use public behavior and real owned components; only external boundaries are doubled.
- New code cannot silently discard facts, change assignments, substitute a model, or hide a failed item.
- Documentation and requirement/test traceability reflect any approved behavior change.
- A task-specific live, scale, or visual gate has evidence when required.

## Remaining approval and operational dependencies

| Item | Owner/gate | Effect |
|------|------------|--------|
| Baseline and persistence/rendering ADR approval | User, T00 | Complete on 2026-10-23; no longer blocks implementation |
| Data-plane authorization and model API/schema support | T06 | Verified against the existing deployment by L06 and actual authoring |
| Explicit paid-call authorization | User, L06/L25 | The user's subsequent direction authorized the bounded existing-resource tests; live tests remain explicitly opt-in |
| Currency pricing | Operator if monetary estimates are requested | No currency ceiling or estimate until verified |
| Licensed fonts and compatible library versions | T01, T19 | ReportLab's bundled Bitstream Vera assets/license and native package/readback checks pass |
| CI/PR platform | User; deliberately deferred | Local development can proceed; do not claim remote CI protection |
| Pilot relevance, regional language, and visual fidelity | T25 and human reviewer | Model-based native visual/content QA is recorded separately; human approval is not inferred |

## Planning quality review

The specification has testable requirements, happy/error/edge/negative conformance cases, prioritized stories, explicit scope, invariants, failure modes, and an AI cost posture. Each requirement has a primary task; each implementation task has concrete test cases. Proposed ADRs have an approval blocker.

Automated planning checks must confirm local links/anchors, unique task/test IDs, acyclic dependencies, requirement/story coverage, and task/test correspondence. These checks validate the plan, not application behavior. No application test result is claimed before implementation.

Validation completed on 2026-10-22: 16 documents, 29 local links, 28 requirements, seven stories, 28 tasks, 60 planned test groups, and ten conformance mappings passed the structural/traceability checks. Worked 7-item, 1-item, 12-item, and 1,000-item allocation examples also passed independent arithmetic checks. One ADR table-format defect was corrected and rechecked.

Critical rubric review: specification 5/5, each of the three ADRs 5/5, and task plan 4/4 criteria passed. This was a planning-quality result. The user separately completed T00 approval on 2026-10-23. Current engineering, live, visual, scale, and external human-gate status is maintained in the evidence ledger rather than inferred from this historical planning review.
