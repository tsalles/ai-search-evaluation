# Experimental data release

Status: local export, recursive archive verification, and full restoration passed.
All 73,941 released files were restored and SHA256-checked. The
[GitHub release](https://github.com/tsalles/ai-search-evaluation/releases/tag/v0.1.0-experiments)
is the distribution location; local verification evidence is recorded separately.

The full anonymized experimental dataset belongs in independently extractable GitHub
release archives for tag `v0.1.0-experiments`. Source code, small numerical reports, and
`results/asset-manifest.json` belong in Git. The manifest is generated only after every
selected candidate and every archive member passes offline verification.

## Restore and verify

Run from the repository root with the project's Python environment:

```powershell
python scripts\experimental_assets.py --cache C:\release-cache
python scripts\experimental_assets.py --cache C:\release-cache `
  --extract C:\restored-experiments --workers 4
```

The first command verifies locally available archives. Download requires explicit consent:

```powershell
python scripts\experimental_assets.py --cache C:\release-cache --download
```

Download URLs use
`https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/`.
No command downloads implicitly. Extraction rejects traversal, links, duplicate members,
unexpected members, checksum mismatches, and overwriting existing files. Every archive
contains complete files, with exact member mapping in the manifest. Restore all archives
to an empty data destination to recover `evaluations\`, `runs\`, and `study-assets\`.
Optional `--workers 1` through `--workers 4` bounds concurrent archive verification and
extraction; all archives pass verification before any extraction begins.

The tracked [evaluations index](evaluations/README.md) lists all evaluation groups
and their archives. To restore into a fresh source checkout instead of a separate
data directory, run:

```powershell
python .\scripts\experimental_assets.py `
  --cache ..\ai-search-evaluation-cache --download --extract . --workers 4
```

The index remains tracked; restored evaluation payloads, runs, and study assets stay
ignored. A checkout must not already contain files being restored. The helper refuses
to overwrite existing release files.

## Release strategy

- Keep source, the visible evaluation index, review reports, and the public manifest
  in Git. Keep bulky datasets and databases in compressed GitHub release assets.
- Give each dataset snapshot a new versioned tag, such as `v0.1.1-experiments`.
  Preserve published snapshots; do not overwrite their archives or move their tags.
- Before a new snapshot, run the confidentiality export, preserve numerical invariants,
  and verify every compressed member and a complete restoration. Retain the historical
  producer and seal limitations.
- Update the manifest, archive checksums, evaluation index, and helper's pinned release
  URL together. Commit them and tag the exact source revision used for the release.
- Upload independently extractable ZIPs below the exporter's 1.8 GB per-archive limit
  to a draft release. Compare GitHub's uploaded sizes and SHA256 digests with the
  committed manifest before publishing.
- After publication, verify anonymous download and checksum validation. Existing users
  can keep the earlier tag and its matching manifest to retain their chosen snapshot.

## Numerical review reports

`results\decision-study-summary.json` is a compact projection of the decision study's
aggregate results. Numerical values and evidence caveats are copied, not recomputed.
Only bulky `source_readback` case records and feature-donor details are omitted from this
review file; their full public artifact remains in the archives. The report records its
source artifact's public checksum and retains the unresolved historical-producer caveat.
Generate it only after the release manifest has been verified:

```powershell
python scripts\summarize_experiment_release.py --cache C:\release-cache
```

`results\release-verification.json` records measured release coverage and the independent
restoration check. `results\frozen-package-source-checks.json` records historical
wheel/source correspondence, not validation of changed public bytes.
`results\archive-checksums.sha256` lists the eight archive checksums from the manifest.
These checks cover the selected experimental assets, not a blanket repository/history audit.

## Scope and provenance

The verified selection contains 73,385 direct files: 63,403 main experimental files,
9,909 external evidence files, and 73 producer scripts. Six original package archives are
replaced by 556 expanded members, yielding 73,941 released files. Of these, 59,016 retain
their original SHA256 and 14,925 are public derivatives. The eight ZIP archives total
1,913,228,843 bytes; the largest is 304,100,502 bytes, below the 1.8 GB exclusive limit.

- Preserve native synthetic corpora, references, qrels, rankings, model evidence, metrics,
  and reconstructed SQLite ledgers.
- Include 73 externally maintained producer scripts and four explicitly frozen evidence
  trees under `study-assets\`.
- Expand the three frozen source distributions and retain wheel dependency metadata.
  Original built packages are excluded explicitly; their expanded source is independently
  sanitized. Historical package checksums do not describe the expanded public derivative.
- Exclude customer presentation binaries, private Git refs, caches, credentials, links,
  macros, and unclassified candidates. Unresolved confidentiality blocks the release.

External trees live in `study-assets\frozen-evidence\`, producer scripts in
`study-assets\producers\`, and expanded source packages in
`study-assets\frozen-dependencies\`. These scripts preserve historical study evidence.
They are not turnkey replay commands: configure local input paths and fresh resource
endpoints before any explicitly authorized live run. No producer is executed during export.
The three frozen wheels each match all 79 package members in their corresponding original
source distributions; `results\frozen-package-source-checks.json` records that comparison.

All embedded legacy hashes, seals, wheel RECORD entries, and signature claims are historical
opaque identifiers. They do **not** verify changed public bytes. Use the manifest's separate
public SHA256 values. Existing original seal validators can reject sanitized derivatives;
do not bypass them or claim that the public derivative reproduces the sealed original.

The recorded `independent_saas_audit.py` hash in
`evaluations\saas-confirmation-study\study-0e518aae\search-validation-proof-v2.json`
does not match the available producer. Its historical producer version remains unresolved.

## Offline exporter

`scripts\public_asset_release.py` accepts an explicit local scope configuration and
private anonymization policy. Neither input belongs in Git or release archives.
It never executes producer scripts or makes model/network requests. It preserves JSON
numeric values and structure, SQLite row counts and numeric cells, XML numeric nodes,
and PDF text, and records the measured invariant counts. TREC, CSV, and PowerShell numeric
token order is preserved; Python numeric and null constants are counted separately.

An operator supplies two private JSON inputs. The scope has `roots`, `scripts`, `files`,
and `distributions` lists; each entry pairs an absolute local `source` with a relative
`public` destination. `roots` are recursive directory selections; the other lists select
individual files. The policy has `replacements` (approved identifying-string mappings),
`clients` (forbidden client names), `private_terms` (identifying aliases that must not
remain), and optional `approved_images` (explicitly approved standard-thumbnail SHA256 values).
Do not publish either input, and do not put credentials in the scope or policy.
Unknown formats and unclassified privacy candidates block export.

```powershell
python scripts\public_asset_release.py `
  --config C:\private-release\scope.json --policy C:\private-release\policy.json `
  --output C:\new-release-cache --manifest results\asset-manifest.json --workers 2
```

The output must be new and outside every selected source. A protected client occurrence
is a blocker, not permission to silently delete an asset. Image approval never permits
retaining a content image merely because it matches a standard metadata thumbnail.

Transformation can reuse bounded, previously assessed byte-identical content with the same
anonymization categories. On-disk exact-content reuse includes copies of freshly
reconstructed public databases; logical per-file invariant counts include these copies.
Unique-content counters are not multiplied when identical emitted files are reused.
Use `--workers 2`, `--workers 3`, or `--workers 4` to partition identical original contents
together after a shared categorized-identifier inventory. Every final archive member is
still read, checksum-verified, and recursively assessed independently.
Parallel exports save an explicitly uncleared checkpoint before final validation.
After a validation interruption, `--resume` with the same scope, policy, output, and
worker count rechecks original input hashes and packed checksums before repeating final
validation; it does not grant clearance to a checkpoint.
Repeated identical text values may reuse a bounded successful privacy assessment;
any identity/resource mapping or protected-term change invalidates that cache.

Python producer sources are parsed, never executed. String literals and comments are
sanitized without rewriting resource-name substrings inside Python identifiers. Numeric
AST constants and syntactic validity must remain unchanged. Literal credential values
remain forbidden; actual AST-proven variable references are not treated as secret literals.

Protected-name checks normalize accents and escaped text, recognize lexical and CamelCase
boundaries in prose, and reject any occurrence in emitted filenames. A matching substring
inside an unrelated ordinary word is not blindly redacted or classified as a client name.

Every text file, JSON value, SQLite text/JSON BLOB, Office XML and relationship, nested ZIP
member, PDF text/metadata, and embedded image is assessed. Unknown image hashes block
export. Approved standard thumbnail metadata may be removed with relationship/content-type
updates. No OCR clearance is claimed. The manifest reports exact format coverage,
unchanged files, derivatives, exclusions, and archive sizes below 1.8 GB.
Nested ZIP member names and text comments are also sanitized. Unclassified extra fields,
prefixes, interstitial bytes, and trailing data block export.

Office compatibility namespace bindings are preserved and checked. Standard PowerPoint
printer settings contain two framed XML property lists, not an opaque binary: their text,
numeric values, structure, and framing lengths are validated without dropping the part.
PDF inspection includes indirect objects and decoded page content streams. Declarative
Adobe Unicode maps and bounded TrueType font programs are classified separately; name
records, table layouts, glyph indices, and metrics are checked without changing font bytes.
Other binary strings or streams, actions, attachments, and images block export.
Final archive members are recursively reparsed from their compressed release bytes.
SQLite residue inspection distinguishes verified public-host suffixes split across
overflow pages from actual endpoints. B-tree cell payloads and overflow chains are
validated first; every logical text value and JSON BLOB still receives strict checks.
The four-byte numeric next-page pointers are not text: their printable low bytes cannot
be joined to the following text payload to invent a client name. These validated framing
bytes are classified separately without changing the database.
Unknown fragments and endpoints remain blockers.

## Offline regression checks

Run the release-specific tests with the public source and scripts on the import path:

```powershell
$env:PYTHONPATH="$PWD\src;$PWD\scripts"
python -m pytest -q tests\test_public_asset_release.py --basetemp=.release-test-work
```

These tests cover preservation, privacy blockers, classified binary framing, historical
seal semantics, archive verification, safe extraction, and the numerical review projection.
They do not execute study producers or contact model services.
