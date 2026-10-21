# Independent outcome gzip shards

Run only after the compact stage has completed successfully. Use a fresh output directory outside that stage:

```sh
taskset -c 8 python public-campaign-20261021/shard_publication_outcomes.py \
  --stage public-campaign-20261021/publication-outcomes-final-v3 \
  --out public-campaign-20261021/publication-outcomes-sharded-v1
```

The default target is 1,048,576 compressed bytes per shard. `--target-bytes` may select a smaller target. A streaming zlib compressor copy plus finish preview tests the exact finished gzip size before admitting each line. Shards are filled near the compressed target, not split at an arbitrary uncompressed byte count. A single row may exceed the soft target but never the strict 2,097,152-byte compressed limit. Every input line must be a complete JSON object ending in newline and strictly below 1,048,576 bytes; oversized lines fail, never truncate.

Each `outcomes/part-00000.jsonl.gz` is a complete independent deterministic gzip stream with zero modification time and no original filename. Original JSONL bytes, field representation, whitespace, row order, row count, failures and diagnostics remain exactly unchanged. Determinism is tested for identical input and zlib implementation; the zlib version is recorded.

`SHARD_INDEX.json` binds each shard's compressed and uncompressed bytes/SHA256, row count and zero-based start/end-exclusive ordinals. It binds the whole original decompressed stream's SHA256/byte count/row count and the original compressed source file. Assembly checks that source compressed bytes match the completed source manifest, and that the row count matches the original artifact index. It then independently decompresses and verifies every produced shard and the joined stream before creating completion manifests.

Portable provenance, reports and `ARTIFACT_INDEX.json` are copied byte-for-byte after verifying their original source-manifest bindings. The original outcome gzip is not copied. Original stage manifest/checksum files survive only under the explicitly historical names `ORIGINAL_STAGE_MANIFEST.json` and `ORIGINAL_STAGE_SHA256SUMS.json`; they are not descriptions of current package contents. Fresh `PUBLICATION_MANIFEST.json` and `SHA256SUMS.json` describe only files actually present. Stdout returns the final manifest size/hash.

The output is create-only. Failure can leave an incomplete output directory without a final manifest; do not publish that directory. This does not change the compact projector's existing omissions, does not access original routing inputs, and does not run routing/builds or publish anything. Keep the frozen original source bundle unchanged; include this helper, tests and guide as separate publication tools when assembling the outer package.
