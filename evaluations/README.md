# Evaluation assets

The complete evaluation payload is available in the
[versioned experimental release](https://github.com/tsalles/ai-search-evaluation/releases/tag/v0.1.0-experiments).
Git tracks this index; compressed release assets contain the datasets and results.

| Scope | Files | Restored bytes |
|-------|------:|---------------:|
| Evaluations | 63,210 | 9,182,335,896 |
| Full release, including runs and supporting study assets | 73,941 | 12,282,355,075 |

The full release uses eight independently extractable ZIP archives totaling
1,913,228,843 compressed bytes. The committed
[manifest](../results/asset-manifest.json) records every file, its archive, and its
public SHA256. [Archive checksums](../results/archive-checksums.sha256) support
independent verification.

## Download and restore into a checkout

After following the [installation instructions](../README.md#install-and-verify),
run from the repository root in a fresh source checkout:

```powershell
python .\scripts\experimental_assets.py `
  --cache ..\ai-search-evaluation-cache --download --extract . --workers 4
```

This explicitly downloads all eight archives, verifies their checksums and every
member, and restores `evaluations\`, `runs\`, and `study-assets\` alongside the source.
The existing evaluation index is preserved. Allow at least 15 GB of free disk
space for the compressed cache and the restored dataset.

To keep the restored data outside the checkout:

```powershell
python .\scripts\experimental_assets.py `
  --cache ..\ai-search-evaluation-cache --download `
  --extract ..\ai-search-evaluation-data --workers 4
```

Use a destination without previously restored release files. The helper refuses
to overwrite files; repeating extraction into a populated destination fails.
Restored payloads remain ignored by Git, while this index remains tracked.

## Evaluation index for v0.1.0-experiments

Counts and archive assignments come from the committed manifest. A study can span
multiple archives; each ZIP is independently extractable. The helper above restores
the complete release, including supporting evidence outside this directory.

| Group | Files | Restored bytes | Archives |
|-------|------:|---------------:|----------|
| `(root configurations)` | 2 | 5,287 | [001][archive-001], [005][archive-005] |
| `decision` | 3,343 | 807,502,424 | [001][archive-001], [005][archive-005] |
| `decision-variants` | 9,927 | 1,542,171,404 | [001][archive-001], [005][archive-005] |
| `entities-development` | 3,136 | 226,795,169 | [001][archive-001], [005][archive-005] |
| `entities-smoke` | 451 | 21,664,896 | [001][archive-001], [005][archive-005] |
| `index-epochs` | 6,624 | 1,442,670,740 | [001][archive-001], [005][archive-005], [006][archive-006] |
| `index-tuning` | 3,281 | 304,752,314 | [001][archive-001], [006][archive-006] |
| `index-tuning-readiness` | 7 | 88,763,754 | [001][archive-001], [006][archive-006] |
| `inventory` | 857 | 11,897,445 | [001][archive-001], [006][archive-006] |
| `large-sample` | 3,303 | 333,507,000 | [002][archive-002], [006][archive-006] |
| `main` | 1,052 | 100,286,209 | [002][archive-002], [006][archive-006] |
| `raw-only` | 1,060 | 133,370,912 | [002][archive-002], [006][archive-006] |
| `saas-confirmation` | 3,759 | 61,711,717 | [002][archive-002], [006][archive-006] |
| `saas-confirmation-study` | 474 | 112,968,924 | [002][archive-002], [006][archive-006] |
| `saas-corrected` | 4,343 | 695,725,421 | [002][archive-002], [006][archive-006] |
| `saas-final-quality` | 4,490 | 696,713,912 | [002][archive-002], [006][archive-006], [007][archive-007] |
| `saas-frozen-tuned` | 8,825 | 1,139,437,794 | [002][archive-002], [003][archive-003], [007][archive-007] |
| `saas-pilot` | 194 | 2,767,117 | [003][archive-003], [007][archive-007] |
| `section-local` | 367 | 2,887,264 | [003][archive-003], [007][archive-007] |
| `section-study` | 3,299 | 686,128,840 | [003][archive-003], [007][archive-007] |
| `semantic-confirmation` | 56 | 13,090,613 | [003][archive-003], [007][archive-007] |
| `smoke` | 120 | 4,950,150 | [003][archive-003], [007][archive-007] |
| `tuning` | 4,240 | 752,566,590 | [003][archive-003], [007][archive-007] |

Archives [004][archive-004] and [008][archive-008] contain supporting release assets
outside the evaluation groups listed above.

## Versioning and evidence limits

Published data snapshots are immutable. Future snapshots receive a new versioned
release, matching manifest, checksums, and updated index; existing archives are
never silently replaced. See the [release strategy](../PUBLIC-DATA.md#release-strategy).

These are anonymized public derivatives. Embedded historical seals do not verify
changed public bytes. Use the public manifest, and retain the documented
[historical producer-version limitation](../PUBLIC-DATA.md#scope-and-provenance).
Restoring data does not execute studies, contact Azure, or rerun live inference.

[archive-001]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-001.zip
[archive-002]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-002.zip
[archive-003]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-003.zip
[archive-004]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-004.zip
[archive-005]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-005.zip
[archive-006]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-006.zip
[archive-007]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-007.zip
[archive-008]: https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/experiments-008.zip
