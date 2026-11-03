# vLLM 0.31.0 offline fixtures

These are excerpts from the user-supplied server evidence package captured on
2026-11-02 UTC. The agent only read the extracted files. No network request,
inference request, or code from that package was executed to create these files.

`provenance.json` records the exact repository-relative source path, original
SHA-256, retained source line numbers, and fixture SHA-256 for every file.
The `version` and `models` JSON files are byte-for-byte copies. Each metrics file
keeps selected original lines in their original order, with UTF-8 LF line endings
and a final newline; labels, values, HELP, and TYPE text are unchanged.

| Fixture prefix | Evidence HTTP directory | Reported model |
| --- | --- | --- |
| `chat` | `http/8000` | `qwen3.8-flash-next` |
| `embedding` | `http/8001` | `qwen3-embedding-4b` |
| `reranker` | `http/8002` | `qwen3-reranker-0.6b` |

Both recorded rounds are retained. The selected values did not change between
rounds; these samples establish a valid zero-increment interval, not a measured
nonzero rate or recent latency window. Nonzero cumulative latency totals describe
the service lifetime and must not be displayed as a fresh 60-second average.

The excerpts contain the relevant gauges, token counters, completion counters
with all recorded finish reasons, latency sum/count pairs, `_created` markers,
and `process_start_time_seconds`. The `+Inf` histogram bucket is retained to test
that its label is not mistaken for an invalid numeric sample. Other buckets and
unrelated metric families are omitted; this is a parser fixture, not a complete
copy of the service's metrics endpoint.

Tests may create explicitly synthetic mutations of these fixtures for identity,
label, number, reset, topology, missing-field, and error cases. Such mutations
are not additional server evidence and must not overwrite these source excerpts.

The source package contains vLLM's Apache-2.0 source files for offline semantic
review. Source code is not imported or executed by these fixtures or tests.
