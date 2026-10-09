# Historical verification record: candidate 01

**Superseded, not release acceptance.** The first independent review subsequently found OM-R1 and OM-R2. Preserve the results below as evidence of the original fixture coverage, not of the repaired source. Current repaired-candidate results are in `reviews/repair-02.md`, `evidence/review-candidate-02.json` and the `*-replay-03.json` receipts. The new full suite passes 152 tests; independent closure review and final ZIP execution remain separate gates.

## Original completed gates

- Native installed Hermes API inspected at `c8301ea6c9b797184df16a9c5dd462400b264ff4`.
- Full deterministic suite: **145 tests passed**, including actual user-plugin discovery, the real post-turn and request-selection hooks, exact-source recall, incremental coverage, stale-worker invalidation, provider/profile pinning, human forgetting CLI, restart, tool pairing and real cross-process SQLite locks.
- Current aggregate log: `test-run-02.log`. Its hash and source membership are recorded in `evidence/review-candidate-01.json`.
- Offline synthetic replay: `evidence/offline-replay-02.json`, PASS.
- Real model-backed synthetic replay: `evidence/model-replay-02.json`, PASS. Observer and answerer used the existing `openai-codex` / `gpt-6-astra` route, with no new provider or private-history ingestion.
- Exact candidate ZIP extracted and all **145 tests re-run from the extracted artifact**: `evidence/package-smoke-01.json`, PASS. Membership and hashes matched the frozen source; disposable runtime removed.
- Independent review is tracked separately in `docs/reviews/`. This document does not confer that review's verdict.

## Model-backed result

The explicitly synthetic Cedar conversation covered a planned but unsent proposal, a corrected meeting date, denied outbound permission, a hostile quoted page and an unsupported assistant claim.

Both original-context and observed-context answers matched the same five-field oracle. Exact original-source pagination, unchanged canonical transcript, stable repeated selection, restart equality and disabled-tombstone forgetting also passed.

| Metric | Actual result |
|---|---:|
| Original request characters | 21,673 |
| Observed request characters | 3,052 |
| Character reduction in this fixture | 85.92% |
| Observer calls | 1 |
| Observer input / output tokens | 4,047 / 277 |
| Baseline plus candidate answerer calls | 2 |
| Whole probe tokens, including both comparison answers | 8,935 |
| Whole probe elapsed | 14.310 seconds |

This is a bounded behavior/integration test, not a broad accuracy benchmark. The baseline and candidate answering costs are combined in this probe receipt. Character reduction and prompt-cache stability do not establish net monetary savings.

## Live-state boundary checked

The live default profile still selected `context.engine: compressor`. The following live default-home paths were absent at verification:

- `plugins/observational`
- `observational-memory.json`
- `observational-memory`

No other profile, memory provider, gateway, archive or real conversation store was changed for this implementation. The early test-bootstrap side effect and all discovered RED cases are documented in `evidence/early-findings.md` and their dedicated repair records. The plugin itself remains uninstalled and inactive on live sessions.

## Release boundary

The user-facing ZIP must be rebuilt after independent review, checked against that accepted source manifest, then extracted and tested again. Any product-code change after the model replay requires source-applicable renewed verification. Read-only review evidence and packaging receipts remain separate from implementation-author claims.
