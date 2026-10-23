# SG cold-start V2 code review candidate

Status: code/provenance review candidate only. Not published, not a selected finalist, and not a heldout-results release. No network access or push was performed. The prior published snapshot remains unchanged at transit-routing-bench commit 67b7222a066b10182646f74d2d0ed2a1f7d59223, results/sg-public-model-2026-10-21.

## What is here

- Two complete allowlisted source/config/fixture base projections, plus 42 ordered branch patches. Every new/deleted source file is represented. BRANCH_RECONSTRUCTION.json supplies explicit reconstruction dependencies, patch hashes, file changes and source digests.
- Eleven routing variants, thirty benchmark/selector/native/storage compositions, and the measured offline-feature-probe composition. Branch names and native API contracts are preserved. Slab/no-arena, local-walking-tie, range, bounded closure, compact T-REX, TB answer ties, sparse diagnostics, walking prefix, finite-safe A and hybrid-fill B remain distinct.
- Exact scientific evaluator/checker, synthetic test, measured harness and source-recipe snapshots in helpers/. Failed bounded-memory/evaluator attempts and source-only/failed native compositions are retained, not promoted to winners.
- Per-file public clearance decisions and summarized withholding categories, source/test hashes, original patch/qualification digest references, licenses, upstream pins and configuration recipes. Hash-only references do not redistribute their target artifacts or assert that they can be fetched publicly.

## Reconstruction order

Choose a branch in BRANCH_RECONSTRUCTION.json. Start with its supplied base, recursively reconstruct its declared parent, copy that parent into a new directory, and apply the branch's relative patch with patch -p1 or an equivalent exact unified-patch reader. Do not apply sibling patches on one another. These parents describe byte reconstruction, not invented Git ancestry.

scripts/reconstruct_code.py can perform create-only, offline byte reconstruction without importing or running project code. Example: python scripts/reconstruct_code.py --tree bench-safe-fill-B-q01 --out /a/new/directory. Use --helpers instead of --tree to materialize exact helper source layout under a new research root. The packager did not execute this deliverable script, project tests, builds, routers, selectors or evaluators.

source-hashes/ records every allowed source/test byte identity, including the benchmark SourceHash convention. The benchmark base was compared with all 216 allowlisted files in the local Git object at f5fb8ebf5fbbb030ab0c3ed4c7feee33dff7311c. The routing base was reconstructed by exact inverse/forward replay of the frozen baseline patch and agrees on all 92 production Go files shared with that benchmark base's routing vendor. It is not claimed that an unavailable complete routing Git commit object was independently re-created or remotely checked.

## Rights and data boundaries

Project code/tests use the retained MIT license. Reference notices are preserved separately. Only the explicitly invented tiny/scoped fixture bytes and synthetic unit literals are included under the retained CC0 dedication. Time zone names in toy fixtures do not make those fixtures real Singapore data.

The public-modeled GTFS provenance remains research-only/no-public-redistribution, and the OSM manifest's public redistribution flag remains false. No raw/derived real model, workload/OD bytes, actual feature pool, witness/proof/index payload, raw result JSONL, cache, binary, archive, private transcript/prompt/agent message, credential or authentication configuration is included. Real source/target domain identifiers in configurations are replaced with explicit placeholders; original file hashes and exact transformations are recorded. The two-query oracle-probe workload is withheld entirely. Lawfully supplied data and new source/input seals are required for future reproduction.

Unchanged, licensed CSA packages are inherited baseline build dependencies only. There is no CSA-package delta, CSA optimization or CSA measurement in this V2 bundle.

## Verification and limitations

VALIDATION.json distinguishes exact source byte checks from unperformed experimental validation. In-memory replay of every generated branch patch matched its allowlisted frozen source map. Original source trees were never edited. No experiment, source build/test, model parse, router/search/scalar/helper run or new timing measurement was performed.

Source projections deliberately omit unrelated repository docs/results and Git metadata; this is not a complete Git-tree/commit/mode replay. Exact helper source bytes retain historical absolute paths and hash assertions. This preserves measured identities but is not a claim that every helper can run unchanged at an arbitrary new path. Some internal qualification/orchestration wrappers are withheld, with opaque original source hash references; they are not required bases for the included algorithm source branches. Portability edits or replacing withheld data require a separately reviewed change, fresh hashes and fresh seals. Do not silently substitute the older portable checker copy for the exact checker supplied here.

Native 2D contracts are not relabeled 3D; local/answer-only walking tie refinements do not promise exhaustive walking-minimal representatives. Compact storage does not alone establish lower process RSS or latency. Source-only/failed/negative branches remain source evidence, not successful measured improvements. Final selected candidates, complete heldout outcomes and final quality/latency conclusions remain pending and belong to a separate reviewed results release.

## Runtime source binding receipt

RUNTIME_SOURCE_BINDING_REVIEW.json explicitly verifies both sources named in the 640-offer runtime freeze: bench-v3-control = 05a41ecd0b4687e83b57d8a548835137c2d049755815dcbef01bb92590a17800 and bench-safe-fill-B-q01 = 8f13517d8a75df4c155e735eb1a03bbfd80012f3cd0de7e32827d1cb13b3628f. Frozen expectations, recomputed original source bytes and reconstructed-bundle fingerprints agree. This does not attest 640 outcomes, a clean Git worktree, an executable/build identity, a portable build path or a latency result. No binary is copied.

The exact scientific schema, hypothetical preference seals/exposure ledger, and three native216 reader adapters are included as evaluator dependencies. Their historical prose/statuses are preserved as source evidence, not promoted to current final-selection or heldout acceptance. Generic preservation/harness source is included only where explicitly required by those source dependencies; operational receipts, admission files and actual datasets remain withheld.

## Public payload boundary

This directory alone is the public source candidate. Its source clearance and byte manifests contain cleared public-relative files, not the detailed private withholding inventory. Omitted categories are summarized without original internal paths; opaque evidence hashes preserve identity without disclosing those private mappings. The surrounding review container and its private review inventory are explicitly ineligible for publication. Publication must copy only entries in the review container's exact public-payload copy allowlist, never the entire review directory.
