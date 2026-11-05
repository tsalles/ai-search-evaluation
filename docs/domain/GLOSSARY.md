# Domain Glossary

Status: Generator terminology baseline with proposed retrieval-experiment terms

Date: 2026-10-28

## Corpus generation

| Term | Definition | Status | Aliases to avoid |
|------|------------|--------|-----------------|
| Content item | One immutable, format-neutral semantic unit accepted from Phase 1. | Established | File, document, page |
| Document | One rendered file containing one content item in one assigned format. | Established | Content, chunk |
| Corpus | The complete published set of final documents from one run. | Established | Output folder including reports |
| Run | One persisted execution identity containing its plan, content, state, reports, and optional published corpus. | Proposed | Corpus when referring to working state |
| Topic | A user-supplied subject and brief used to plan content items. | Established | Format, genre |
| Genre | A logical writing pattern such as procedure, FAQ, comparison, or explainer. | Proposed | File type, layout |
| Length band | A bounded word-count category assigned before format allocation. | Proposed | Page count |
| Structure profile | A declared set of logical content structures and complexity limits. | Proposed | Format weight |
| Layout profile | A format-specific arrangement that preserves all canonical content. | Proposed | Paraphrase |
| Structure recipe | A bounded declaration of ordered block groups, repetition ranges, optional groups, and a genre/complexity contract. | Proposed | Prompt fragment, executable template |
| Structure plan | One immutable resolved sequence of canonical slots sampled from a structure recipe before authoring. | Proposed | Draft, layout plan |
| Logical complexity | A measured envelope of heading/list nesting, tables, and callouts independent of content length and native layout. | Proposed | Word count, retrieval difficulty |
| Native layout plan | One immutable supported arrangement sampled after format assignment that preserves accepted business content. | Proposed | Rewrite, logical recipe |
| Structural signature | A normalized hash of resolved block shapes and order excluding identifiers, roles, wording, and word budgets. | Proposed | Content fingerprint |
| Word-band tolerance | A frozen fractional acceptance margin around nominal word-band endpoints that does not change authoring targets or length-band labels. | Proposed | Retry budget, automatic relaxation |
| Slot word budget | An advisory total word target for one frozen block, including every list item or table header/cell in that block. | Proposed | Per-cell allowance, acceptance threshold |
| Measurement-unit identity | The semantic unit shared by explicitly known grammatical variants while visible labels, values, periods, and dimensions remain intact. | Proposed | Display string equality, numeric conversion |
| Corpus push | An independent operation that copies an existing corpus into an explicitly selected Azure Blob container without authoring or rewriting content. | Proposed | Generation, publication rollback |
| Blob prefix | A relative object-name namespace prepended to corpus-relative filenames in the destination container. | Established | Local filesystem directory |
| Format share | A requested fractional corpus proportion whose integer quota is determined by rounding. | Established | Guaranteed exact percentage at every N |
| Format assignment | The immutable mapping from one content ID to its sole output format and path. | Established | Independent random draw per retry |
| Fact ledger | Scenario-scoped synthetic values used to keep generated statements and tables consistent. | Proposed | Retrieval answer key |
| Accepted content | A content item that passed required local quality checks and has a persisted hash. | Proposed | Any model response |
| Published corpus | Final documents made available only after complete-set validation. | Proposed | Staging artifacts |

## Retrieval experiments

| Term | Definition | Status | Aliases to avoid |
|------|------------|--------|-----------------|
| Scenario family | A linked set of fictional entities, claims, related documents and distractors assigned to one evaluation split. | Proposed | Topic, one document |
| Information need | A stable question intent with explicit entity/scope, answerability and sufficient evidence requirements. | Proposed | Query wording |
| Query utterance | One reviewed natural-language expression of an information need. | Proposed | Independent intent |
| Reference release | An immutable reviewed set of queries, judgments, evidence and corpus identities used for evaluation. | Proposed | Unchecked generated answers |
| Qrels | Explicit query-to-document relevance judgments with grades and a declared coverage policy. | Proposed | Retrieved positives only |
| Canonical parent | The source semantic document identity shared by its indexed chunks and matched format views. | Proposed | Search-generated parent key |
| Index snapshot | A frozen observation of indexed sources, chunks, configuration and embedding identity used for collection. | Proposed | Index name alone |
| Pipeline arm | One frozen extraction/chunking treatment applied to the same newly generated source corpus and evaluated with a shared reference and common retrieval settings. | Proposed | A separately generated corpus, an arm-specific ranker |
| Evidence occurrence | A verified location of a claim in accepted canonical content with its applicability and relation context. | Proposed | Token presence |
| Sufficient claim set | A minimal set of grounded claims that together answers an information need. | Proposed | One matching value |
| Benchmark view | An isolated artifact assignment containing one representation of each canonical parent for a controlled comparison. | Proposed | Duplicate copies in one corpus |

## Relationships

- A **run** plans N **content items** and publishes at most one **corpus**.
- Each **content item** belongs to one **topic**, one **genre**, and one **length band**.
- Each accepted **content item** has at most one **format assignment**.
- A recipe-enabled **content item** has exactly one **structure plan** with one logical complexity level.
- A layout-enabled **format assignment** has exactly one **native layout plan**.
- Each **document** renders exactly one **content item**; a complete **corpus** contains exactly N **documents**.
- A **fact ledger** belongs to an explicit scenario and may be shared only through a frozen scenario definition.
- A **scenario family** owns related documents and **information needs**; all their utterances/views remain in the same split.
- An **information need** has one or more reviewed **query utterances** and zero or more alternative **sufficient claim sets**.
- A **canonical parent** can have many indexed chunks in one **index snapshot**, but earns document-level relevance credit at most once in a ranked result.

## Flagged ambiguities

- "Number of contents" means N semantic content items and therefore N final files, not N pages or N files per format.
- "Weights" means requested shares totaling 1, not arbitrary scores normalized silently.
- "Reproducible" means stable planning/allocation and replay from persisted content, not identical new LLM generations.
- "Complexity" means logical complexity unless explicitly qualified as native layout; neither label establishes equal extraction difficulty across formats.
- "Documents only" excludes retrieval queries, qrels, and engine execution; it permits private generation state and quality reports.
- "Documents only" describes the original generator release; the [proposed experiment extension](../experiments/design.md) adds separate reference/evaluation artifacts without putting them into the published corpus.
- "Relevant" means the declared grade policy, not that a document was the source used to draft a query; `unjudged` is not grade zero.
