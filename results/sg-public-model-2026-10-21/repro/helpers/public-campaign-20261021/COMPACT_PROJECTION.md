# Optional compact publication projection

Use the same create-only publisher with `--compact`:

```sh
taskset -c 8 python public-campaign-20261021/stage_publication.py \
  --compact \
  --campaign public-campaign-20261021/first-baseline \
  --campaign public-campaign-20261021/resumed-0130/auxiliary-native-smoke-7gb \
  --report path/to/compact-aggregate-summary.json \
  --out path/to/new-publication-directory
```

Repeat `--campaign` and `--report` for the approved selection. Do not pass complete evalkit scorecards, pools, raw workload JSONL, source datasets, binary files or unreviewed narrative/source reports. The output directory must not already exist. This helper does not execute routers or publish anything.

Without `--compact`, the existing expanded layout and outcome projection remain the default.

## Layout and verification

Compact output has five base files, plus individually readable approved reports:

- `outcome-records.jsonl.gz`: every emitted outcome and offered-unresolved slot, with request identities, original record/artifact bindings, completion/status/error, timing/allocation, diagnostics, row certificates, objectives and existing witness hashes. No row sampling or failure removal occurs.
- `provenance-records.jsonl.gz`: portable plan, status, command, process and native summary/manifest members. Each line contains the logical relative `path`, parsed `content`, and its projected canonical `bytes` and `sha256`.
- `ARTIFACT_INDEX.json`: original source-file SHA256/size bindings, exact record counts and compact loss disclosure.
- `SHA256SUMS.json` and `PUBLICATION_MANIFEST.json`: bounded output hashes, sizes and paths. The manifest excludes its own recursive entry; stdout gives its final size/hash.

Both compact gzip files have an empty filename header and zero modification time. Canonical member bytes are sorted-key, compact UTF-8 JSON followed by one newline. Canonical payload hashes use the same serialization without that newline. Original file hashes bind the original bytes, not these canonical projections. Full input selection, original file bytes and helper source identity are required when checking repeatability.

## Exact omissions

1. Within `recommendation_quality` only, feature identity/pattern/metric objects and repeated per-selection chosen identities/decision maps become an original canonical payload hash, exact feature/selection counts, policy, and up to 64 selection configurations and decision-reason categories. Each retained selection has its own original hash. Ordinary final objective metrics, raw/final witness hashes, per-query certificates and all outcome fields outside that quality subtree are unchanged. Compact quality alone cannot recompute every feature/user-choice score; publish separately reviewed aggregate quality results and independent audit bindings.
2. Within preparation/index-cost metadata only, arrays of sparse transfer certificates, incoming/witness-connection proof cells and other preparation arrays become original canonical payload hashes, exact item counts and bounded reason/status counts. Scalar configuration, phase, resource, timing, allocation, count, completion/decline, status and error fields remain. Raw-source-table-shaped preparation values are represented only by payload hashes/counts. This preserves reported preparation/accounting but does not distribute the detailed proof corpus or permit proof revalidation from this package alone.
3. Portable metadata members move into the provenance gzip instead of thousands of individual files. Original references in the artifact index remain original references; logical member paths locate the corresponding portable metadata.

The package remains an outcome projection, not byte-identical raw originals or a replacement for authorized source retrieval/rerun. No change to request/row/cell denominators, forced/warmup labeling, capability declines, failed attempts, unsupported cases or prelaunch unknowns is intended. Raw redistribution rights remain unverified. End-to-end inspection of the final approved selection is still required before publishing.

## Bounded size estimate

The layout reduces roughly 1,500 metadata files to one compressed provenance file, independent of row count. The five base files plus readable reports are exact; compressed byte size is data-dependent. Existing small family-baseline projection rows can estimate quality reduction, but extrapolating them to all algorithms is not a final package-size guarantee. CoreCH ordered target cells, profile ready-time grids and all objective/certificate hashes remain intentionally unthinned.
