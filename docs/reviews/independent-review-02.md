# Independent review 02 — PASS

**OM-R1 and OM-R2 are closed for the exact frozen candidate below.** No new in-scope blocker was found. The full current deterministic suite passed twice: **152 tests**, no skips. This is a narrow independent repair-closure verdict, not live activation or closure of the parent's delivery task.

## Candidate and preserved adverse review

- Repository: `/Users/mini/workspace/hermes-observational-memory`.
- Manifest: `docs/evidence/review-candidate-02.json`, SHA-256 `1c76d4ed03ad48820be4d66c4a2803ca5cac7bc56fe42cc3a64dcfd39dec0bfc`.
- Start: `2026-10-09T08:54:15.340117+00:00` — **27/27 file hashes match**; exact source/test/tool/example membership matches.
- End: `2026-10-09T09:00:34.795146+00:00` — **27/27 still match**, same manifest and membership; no source drift.
- The only predecessor changes are `README.md`, `observational/backend.py`, `observational/engine.py`; the only added source file is `tests/test_review_regressions.py`. All four were read in full. The previous full review of unchanged files is carried forward only after exact hash verification, with targeted supporting rereads.
- Installed host: `c8301ea6c9b797184df16a9c5dd462400b264ff4`. All six previously examined host files still match their recorded hashes and that commit; the actual ContextEngine ABI and host completion/selection hooks were reread.
- Reviewer: separate delegated Hermes reviewer, **gpt-6-astra / openai-codex**, not Claude/Opus. No implementation or test changes were made.

The original **REQUEST_CHANGES** verdict remains untouched:

| Preserved artifact | SHA-256 |
|---|---|
| `docs/reviews/independent-review-01.md` | `d603146fda211c0acd839b4a4017e5d127e6c27db1dbf12274509ff1a310e65a` |
| `docs/reviews/independent-review-01.json` | `3b930a63f4ce5c25fc6614dd04c5f1507839724566146146ef657b169f949423` |
| `docs/evidence/pre-review-candidate-01.zip` | `cb465f9314ccdb9276710e59e01a2b6bb3782c24c3645c4dd0cab007ac713c97` |

The first report's companion seal, source manifest, embedded probe-source hash, supporting evidence and unchanged-file bindings were reconciled programmatically. The historical ZIP matches all 26 predecessor manifest files. Its adverse findings were not rewritten or relabelled. The preserved RED log contains seven executed test methods and ten assertion-failure sections, including subtests; these are product-behavior failures, not import/setup failures. This review did not rerun the rejected historical candidate.

## OM-R1 — CLOSED

**Source:** `observational/engine.py:245–254,337–414`; `observational/backend.py:26–88`. **Regressions:** `tests/test_review_regressions.py:65–134`.

The update path now clears pending work and advances the epoch. Each default model job captures its own epoch/store in the authorization callback. The backend checks that callback before resolution and again at completion admission. Worker admission and result publication also reject route/snapshot/epoch/session-store invalidation. Stale success and failure paths do not erase the current guard error.

Independent execution verified:

- With a first completion held and a second snapshot queued, switching away clears pending work. Only the already-admitted first call occurs; it publishes no observation. `pinned_model_does_not_match_actor` survives its completion. Returning to matching pins produces a new call only after a fresh completed snapshot.
- A switch during provider resolution prevents `create` entirely. Instrumentation captured epoch **1** versus current epoch **2**, and a denied completion-admission check.
- An away-and-back change while the observer is held still denies the old job **before resolver entry**: captured epoch **1**, current epoch **3**, even though route mismatch is now false.

The immutable token, denial phase and preserved errors were inspected directly, not inferred only from test names. **Already-admitted work is in flight:** the repair does not claim transport cancellation, retroactive unsending or holding the engine lock over a network request.

## OM-R2 — CLOSED

**Source:** `observational/engine.py:274–310,337–414,440–443,484–508`; supporting `observational/store.py:337–393`. **Regressions:** `tests/test_review_regressions.py:135–209`.

Failed authoritative ingestion advances the epoch, clears pending work, marks the snapshot unavailable and transactionally clears the previous plugin mirror with `sync_sources([])`. Recall/search and selection are blocked while unavailable. This is not the human-only permanent-forgetting tombstone; later valid history can repopulate the session.

Actual host hooks and real SQLite verified previously published and in-flight observations, old-worker exceptions, structured content, incomplete tool pairs, synthetic credential-pattern input, oversized input and empty replacement. Each successful invalidation left no sources or observations, preserved `unsupported_or_sensitive_input` after old work settled, denied the removed source ID across restart, left canonical input and the actor request unchanged, and allowed valid replacement history without reviving the removed source. The in-flight success and failure fixtures both recorded one discard with the ingestion error intact.

An additional bounded independent probe rejected a snapshot while the model resolver was held, then supplied valid history **on the same engine before releasing the old job**. Despite the availability flag recovering, the old captured epoch was denied. Only the fresh job completed: two resolver entries, one synthetic completion, ten current sources, one new observation, and no removed source in its payload.

The documented storage-I/O limitation was also fault-tested, not hidden: an injected invalidation failure retained 12 sources/eight observations in SQLite, returned `source_invalidation_failed`, and blocked current-engine recall/search/projection without creating a tombstone. **No deletion, restart safety or storage-failure recovery is certified for that failure case.** This is the explicitly bounded error behavior, not a new durable-erasure promise.

## Executed verification

Working directory: `/Users/mini/workspace/hermes-observational-memory`.

```sh
PYTHONDONTWRITEBYTECODE=1 HERMES_DISABLE_LAZY_INSTALLS=1 python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent
```

- Full independent run: **152 tests, 3.406s, OK, exit 0**.
- Final uninstrumented confirmation: **152 tests, 3.749s, OK, exit 0**.
- Executed IDs reconciled to every static test method, with no missing tests or skips. Raw outputs are preserved in the JSON.
- A separate bounded scratch probe reran the seven unchanged repair tests with observational instrumentation: **7 tests, 0.228s, OK**, then executed the same-engine recovery and storage-failure probes above. Captured events, exact probe source and SHA-256 are in the JSON. Synthetic state and the temporary script were cleaned.
- Runtime: Python **3.14.7**, SQLite **3.53.1**. Provider clients were synthetic and socket connection attempts prohibited. No hosted model call, credentials access, dependency installation, live profile/config/history change, gateway action or archive mutation occurred.

## Renewed replay receipts

| Receipt | SHA-256 |
|---|---|
| `model-replay-03.json` | `78d9242bcc5f4fd8934ff9fc213c68708daf1dac9c625ec63e30e01376fa280d` |
| `offline-replay-03.json` | `5ecc4c79c95a9af620fa9e5133098d6e67b29a2bcd9e98bc49e9e9acc5aa361e` |

Both match the candidate's six runtime-source hashes. Offline analysis of the exact source-defined fixture validated all five model quotes and ten offline quotes, source identity/attribution, declared counts, deterministic reflection, complete rendered memory, character metrics, model answer-oracle agreement and usage arithmetic. The model receipt records three prior calls and 8,934 tokens; **no hosted replay was repeated here**. Its injected-observer fixture is evidence of the declared replay, not a substitute for the default engine/backend authorization regressions. Offline replay has no actor-answer accuracy comparison.

## Bounded acceptance

The first review's nonblocking limits remain: no total SQLite-publication latency guarantee; no forcibly cancellable arbitrary Python worker or absolute billing cap; exact quotation is not external truth, semantic completeness or perfect injection resistance; POSIX private storage is not encryption, forensic erasure or same-UID sabotage protection; request shaping remains session-only and host hooks are best-effort. No archive ingestion, cross-session memory, durable/emergency compaction, broad benchmark or cost-superiority claim is added.

**PASS** applies to OM-R1/OM-R2 closure, repair regressions and current acceptance on the bound source and installed host. Final packaging, extracted release-ZIP execution, installation/activation and the parent's final handoff remain separate gates. See `independent-review-02.json` for exact read ranges, source/evidence seals and executable results.
