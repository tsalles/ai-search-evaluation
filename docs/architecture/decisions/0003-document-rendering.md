# 0003 Document Rendering

Status: Accepted  
Date: 2026-10-22  
Accepted: 2026-10-23

## Context

The corpus must contain actual editable/parseable structures, with no LLM rewrite or duplicate alternate formats. Runtime execution is local and Windows must work without requiring Microsoft Office.

## Priorities and requirements

1. Preserve all business text, facts, and table associations in native document structures.
2. Make rendering offline, repeatable, and independently testable.
3. Keep runtime installation manageable on Windows.

## Options evaluated

| Option | Native fidelity | Offline verification | Windows runtime | Limitation |
|--------|-----------------|----------------------|-----------------|------------|
| Dedicated Python native libraries and direct PDF layout | Meets with per-format layout work | Meets; inspect saved text/XML/cells | Meets without Office | Requires six renderer contracts and explicit continuation rules |
| One HTML/Markdown intermediate converted by external tools | Partial; spreadsheet and slide semantics need custom treatment | Meets if converters are pinned | Requires browser/Pandoc/office converter dependencies | A universal intermediate can flatten tables or business structure |
| Office automation or cloud document conversion | Can preserve Office layouts | Depends on installed applications/service | Requires Office or remote service | Adds environment, licensing, concurrency, or network dependencies |

## Decision

Use small MD/HTML writers, `python-docx`, `openpyxl`, `python-pptx`, and ReportLab. This prioritizes native structures and offline inspection over uniform rendering code. Bundle a licensed portable font and retain all source values; do not shrink or truncate to make a page fit.

## Consequences and approval

Native readback, table-association tests, long-content fixtures, Unicode checks, and visual pilot review are mandatory. Office/LibreOffice may be used as an optional review viewer, not a runtime dependency. Exact library versions and font redistribution rights are verified during implementation. The user approved this approach through T00 on 2026-10-23; renderer work remains subject to the task prerequisites and tests.
