# Rendering Tasks

Status: T14 to T22 complete; representative visual QA findings and fixes are recorded under T25

All renderer tests use canonical fixtures, actual saved files, and independent readback. Every renderer preserves all baseline blocks. Paths are relative to the project root.

## T14 Establish the renderer contract and complete Markdown

- Stories: US03, US05. Requirements: FR15, FR20. Prerequisites: T04, T13.
- Scope: typed renderer registry/capability matrix, artifact descriptor, safe assigned destination, and complete GFM headings/lists/tables/callouts.
- Paths: `src\docgen\renderers\base.py`, `src\docgen\renderers\markdown.py`, `tests\rendering\test_markdown.py`, `tests\test_artifact_validation.py`.
- U14: unsupported structures fail with block ID; table pipes, literal markup, backslashes, and multiline text retain meaning without active content.
- I14: independent Markdown parsing reconstructs headings, order, table associations, Portuguese accents, and all protected facts. No provider call is possible.
- Acceptance: no renderer may paraphrase, omit unsupported content, or choose its own output format/path.

## T15 Render native semantic HTML

- Stories: US03, US05. Requirements: FR15. Prerequisites: T14.
- Scope: UTF-8 self-contained HTML, semantic sections/lists/tables, and bounded local CSS.
- Paths: `src\docgen\renderers\html.py`, `tests\rendering\test_html.py`.
- U15: script/markup-like business text is escaped; no executable handlers, remote assets, or hidden business facts are emitted.
- I15: an independent HTML parser verifies the table grid, heading hierarchy, language metadata, text/facts, and readable DOM order.
- Acceptance: opening the file requires no network and executes no generated code.

## T16 Render native DOCX

- Stories: US03, US05. Requirements: FR16. Prerequisites: T14.
- Scope: styles, real headings/list numbering, native tables, portable font choice, and multipage flow.
- Paths: `src\docgen\renderers\docx.py`, `tests\rendering\test_docx.py`.
- U16: nested lists, long paragraphs/cells, page breaks, and repeated table headers have no fixed-height truncation or missing blocks.
- I16: inspect ZIP/XML independently for text, numbering, table row/column relationships, styles, and absence of macros/external relationships.
- Acceptance: required text is editable body content, not drawings, comments, or hidden metadata.

## T17 Render native XLSX

- Stories: US03, US05. Requirements: FR17. Prerequisites: T14.
- Scope: section-based sheets, typed cells, visible units, native table ranges, wrapping, and safe sheet/table names.
- Paths: `src\docgen\renderers\xlsx.py`, `tests\rendering\test_xlsx.py`.
- U17: formula-like text stays literal; real negative decimals remain numeric. Overlong cells, precision overflow, forbidden sheet characters, 31-character name limits, and case-insensitive collisions are handled explicitly without truncating business content.
- I17: inspect saved XML/cells/table definitions for values, types, visible units, row/column association, sheet order, and absence of formulas, macros, external links, and hidden facts.
- Acceptance: narrative sections remain readable cell groups, not one giant cell or an embedded image. No formula evaluation service is introduced.

## T18 Render native PPTX

- Stories: US03, US05. Requirements: FR18. Prerequisites: T14.
- Scope: widescreen presentation, native editable text and tables, explicit reading order, and continuation slides.
- Paths: `src\docgen\renderers\pptx.py`, `tests\rendering\test_pptx.py`.
- U18: long content continues onto new slides; long tables split by rows with headers; font size stays at least 14 pt; an unfit block raises a precise error.
- I18: independently inspect slide XML for text/table presence and order, slide boundaries, font/shape bounds, and no required notes-only text or rasterized body.
- Acceptance: all source blocks remain represented exactly once, except declared repeated structural headers.

## T19 Render native text PDF

- Stories: US03, US05. Requirements: FR19. Prerequisites: T14.
- Scope: direct ReportLab layout, licensed embedded font, UTF-8/Portuguese glyph coverage, page flow, long tables, and visible units.
- Paths: `src\docgen\renderers\pdf.py`, `src\docgen\renderers\layout.py`, ReportLab's bundled fonts/license, `tests\rendering\test_pdf.py`.
- U19: paragraphs/rows crossing pages retain all text; overwide/unbreakable blocks report overflow rather than clipping. Font asset packaging and redistribution notice are verified.
- I19: `pypdf` and independent `pdfplumber` table geometry check facts/blocks/table relationships, embedded fonts, native text, and page bounds. Fixtures include cedilla, nasal vowels, accents, currency, and dates.
- Acceptance: the installed wheel renders correctly without depending on system fonts or a browser; no text-as-image substitute.

## T20 Add complex layouts and common fidelity fixtures

- Stories: US03, US05. Requirements: FR20. Prerequisites: T15, T16, T17, T18, T19.
- Scope: the complex profile, two-column PDF/DOCX prose, nested lists, multiple/long tables, slide/sheet/page continuation, and common geometry limits. Keep unsupported features explicit.
- Paths: `src\docgen\profiles.py`, `src\docgen\renderers\`, `tests\rendering\test_complex_profiles.py` and its `complex_reference` fixture.
- U20: all profile boundaries and renderer capabilities are validated before writing; impossible layout cannot downgrade or discard a structure.
- I20: render the same deterministic complex fixture separately in each format for renderer testing only, outside any published corpus. Independently verify full block/fact/table preservation and format-native structures; this test fixture reuse is not a generated document-set feature.
- Acceptance: each renderer meets its declared capability matrix; six complex reference files are available for the later visual release review. Geometry and token checks are not claimed to prove every viewer's visual behavior.

## T21 Validate artifacts independently

- Stories: US05, US06. Requirements: FR20, FR28. Prerequisites: T20.
- Scope: public artifact/set validation, independent extractors, format signatures, native-structure checks, protected facts, table association, block mapping, and exact-set integrity.
- Paths: `src\docgen\validation.py`, `src\docgen\extractors\`, `tests\test_artifact_validation.py`.
- U21: removing a fact, swapping two table cells, moving a fact into notes/hidden cells, breaking XML/ZIP, altering hashes, or adding an unexpected file must fail even when most tokens remain present.
- I21: valid baseline/complex artifacts pass all six validators; intentionally damaged copies identify the content/block and failure type. The renderer's own in-memory representation is not used as readback evidence.
- Acceptance: reports distinguish syntax, content fidelity, native structure, geometry, and set-integrity outcomes; invalid artifacts block publication.

## T22 Complete standalone Phase 2 and safe publication

- Stories: US03, US04, US06. Requirements: FR21, FR25, FR26. Prerequisites: T21, T13, T05.
- Scope: allocate, stage, render, validate, ready-manifest, atomic corpus publication, and report export. Reuse verified staged artifacts on failure/resume.
- Paths: `src\docgen\rendering.py`, `src\docgen\publication.py`, `tests\test_render_phase.py`.
- U22: a missing/corrupt content item, unavailable renderer, wrong assignment, or failed validator leaves the corpus unpublished and reports a typed error.
- I22: render the 12-item mix to exact totals 3 PDF, 3 DOCX, 2 XLSX, 2 PPTX, 1 HTML, 1 MD with network/provider forbidden. The final directory contains exactly 12 assigned documents and no sidecars.
- I22 recovery: fail before/after ready-manifest and directory rename; reopen and recover only the same planned file set. Never expose partial output as complete or retain a second published format.
- Acceptance: Phase 2 runs with no Azure credentials and zero LLM calls; source content hashes are unchanged.

## Completion evidence

- Each native writer has its matching test module above and an independent saved-file extractor.
- Shared artifact tests corrupt files, facts, cell associations, font sizes, hidden content, checksums, and set membership; plausible-looking invalid output fails.
- Complex reference tests exercise all six formats, native tables, nested lists, two-column prose, and continuation. Reusing reference content across formats is test-only.
- Publication tests cover the ready checkpoint, before/after directory rename, valid files between file/database commits, and refusal to overwrite verified corruption.
- Native Word/PowerPoint schema checks and actual Microsoft Office exports supplement automated readback. Model visual review found orphaned PPTX headings; deterministic tests and fixed native re-exports verify the repair.
