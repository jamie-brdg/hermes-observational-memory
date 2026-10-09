# Release handoff: Hermes Observational Memory 0.1.0

## Status

The native Python ContextEngine source has passed its bounded independent acceptance gate. **Live installation and activation are intentionally off.** This release is for a controlled fresh-session pilot, not a claim of lossless memory, broad benchmark superiority or production-wide trust-release certification.

## What is included

- Background Observer, deterministic Reflector, private per-session SQLite source store, paginated read-only recall/search/status, and request-only context selection.
- Exact source quotation and role attribution. Intentions do not become completed actions merely because time passed.
- Offline extractive mode by default. Hosted model observation needs explicit consent and matching provider/model pins; only the existing `openai-codex` adapter is enabled here.
- Create-only installation, separate activation/rollback instructions, and a human-confirmed plugin-copy forgetting CLI.
- Reproducible tests, clearly synthetic replay fixtures, exact source hashes and both adverse and final independent reviews.

No personal conversation archive, live database, credentials, dependency environment or installed Hermes source is included.

## Accepted evidence

| Gate | Result |
|---|---|
| Full deterministic suite | 152 tests passed |
| Actual installed Hermes integration | User-plugin loader, post-turn and request-selection hooks passed |
| Independent review | PASS on frozen candidate 02; original R1/R2 adverse findings preserved and closed |
| Offline synthetic replay | PASS, current runtime-source hashes match |
| Real model synthetic comparison | Original and observed context match the same five-field answer oracle |
| Fixture context size | 21,673 -> 3,053 characters, 85.91% reduction |
| Entire model comparison probe | 3 calls, 8,934 tokens, 15.4 seconds |

These are measurements of the declared synthetic scenario. Character reduction is not token reduction or money saved. Tests do not certify perfect prompt-injection resistance or external truth.

The independent reviewer was a separate Hermes `gpt-6-astra` worker, not Claude/Opus. The original Claude CLI authentication limitation remains recorded in the build plan.

## Evidence map

- `evidence/review-candidate-02.json`: accepted product/test/tool/config file hashes.
- `reviews/independent-review-02.md` and `.json`: independent PASS, exact coverage, executions, limitations and binding to the earlier adverse report.
- `reviews/independent-review-01.md` and `.json`: original REQUEST_CHANGES evidence, preserved unchanged.
- `reviews/repair-02.md`: source-bound repair explanation and genuine RED/GREEN results.
- `evidence/model-replay-03.json` and `offline-replay-03.json`: current-source replay receipts.
- `VERIFICATION.md`, earlier manifests and earlier replays: historical evidence, not current acceptance.

The final ZIP must be accompanied by the separate `release-verification-01.json` receipt with `pass: true` and a matching `archive_sha256`. The verifier extracts that exact archive, reconciles its manifest and independent PASS, reruns all 152 tests, executes the documented installer into a disposable home, loads and runs the installed plugin, exercises the human forgetting CLI and verifies its tombstone after restart, then removes the disposable state. Keeping this receipt outside the archive avoids a circular archive hash.

## Use and limits

Read the top-level `README.md` for exact installation, explicit activation, rollback, configuration and forgetting commands. Do not copy the hosted-mode example as if it were the offline default. Start a new session for a pilot; importing old live history has not been approved or performed.

The original Hermes transcript is never rewritten. This plugin is session-scoped and does not replace cross-session memory. Unsupported completed snapshots conservatively clear the plugin mirror while retaining the actor request. Already-admitted model calls cannot be retroactively unsent. Storage failures are reported rather than certified as deletion. Filesystem privacy is not encryption, secure SSD erasure or external-provider/backup deletion.
