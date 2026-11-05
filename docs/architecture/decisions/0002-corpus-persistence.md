# 0002 Corpus Persistence

Status: Accepted  
Date: 2026-10-22  
Accepted: 2026-10-23

## Context

Phase 1 must survive interruption and feed offline Phase 2. Each content item may produce only one document format, even after resume. The target is at most 1,000 items on a local filesystem.

## Priorities and requirements

1. Immutable content and assignment integrity: resume must not duplicate or silently alter accepted items.
2. Format-neutral fidelity: tables, facts, and logical sections must survive all renderers.
3. Low operational overhead: no external database or storage service is needed at this scale.

## Options evaluated

| Option | Integrity/resume | Structured fidelity | Operational overhead | Limitation |
|--------|------------------|---------------------|----------------------|------------|
| Canonical JSON files plus SQLite checkpoints | Meets with explicit write reconciliation and locks | Meets with versioned typed blocks | Local standard-library database | Requires testing non-atomic filesystem/database boundaries |
| Markdown files plus a mutable JSON manifest | Partial; concurrent/crash-safe manifest mutation is custom logic | Partial; typed cells and fact references need conventions | Low initially | Couples content to a presentation syntax and adds parsing ambiguity |
| External database/object store | Meets with additional design | Meets | Requires services, credentials, and remote transactions | Exceeds the local 1,000-item requirement |

## Decision

Use immutable canonical JSON for accepted content and SQLite for mutable attempt/item/assignment state. This directly supports the first two priorities while keeping persistence local. A ready-manifest and same-volume directory rename protect complete-corpus publication.

## Consequences and approval

Run-locking, checksums, failed-write reconciliation, and crash tests are required. Network shares and cloud storage adapters are deferred. The published corpus contains documents only. The user approved this decision through T00 on 2026-10-23; implementation remains subject to the task prerequisites and tests.
