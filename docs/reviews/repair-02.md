# Independent review repair 02

## Binding and preserved adverse evidence

The original REQUEST_CHANGES verdict remains unchanged at `docs/reviews/independent-review-01.md` and `.json`. Its source and companion-report hashes were checked before repair. The exact original source archive is retained at `docs/evidence/pre-review-candidate-01.zip`; it matches all 26 original source-manifest entries. It is a rejected historical candidate, not the release to install.

The new candidate is frozen in `docs/evidence/review-candidate-02.json`. Relative to the first manifest, only `observational/engine.py`, `observational/backend.py` and `README.md` changed, and `tests/test_review_regressions.py` was added. Other product, storage, validation, installer and test files are unchanged.

## OM-R1: queued route changes

- Model updates invalidate the captured epoch and clear pending work. The worker loop will not admit a mismatched route.
- Each model observer job binds its own immutable epoch/store pair into the backend authorization callback. Returning to the previous model does not renew an old job.
- Backend authorization runs before provider resolution and again immediately before completion admission, so a route switch during a blocked resolver prevents the client completion call.
- Result publication checks current route, epoch, session/store and snapshot eligibility. Old failures cannot erase the current route/snapshot error.
- The network call is not held under the engine lock. Completion admission is the authorization boundary: already-admitted/in-flight work cannot be retroactively unsent or forcibly killed. This is explicitly documented, not a claim of atomic transport revocation.

Regressions cover a queued second batch while the first completion is held; a route change while provider resolution is held; a route away-and-back while the observer is held before completion; and successful recovery only after a fresh completed snapshot with matching pins. Real engine/ModelObserver/HermesCompletion/SQLite are used, with synthetic provider objects and socket denial.

## OM-R2: rejected authoritative replacement

A failed complete-snapshot ingestion increments the worker epoch, cancels pending work, blocks source tools/projection in that engine and clears the previous plugin mirror using `sync_sources([])`. It never stores rejected content, changes the canonical actor transcript or invokes the human-only `forget()` tombstone. A later valid snapshot can repopulate the session.

Regressions cover both previously published and in-flight old observations, an old worker that raises, structured input, incomplete tool pairs, synthetic URL credentials, an oversized transcript and an empty replacement. They use the real installed post-turn/request-selection hooks and prove empty persisted sources/observations, unavailable removed source IDs, unchanged actor requests, restart denial and supported-snapshot recovery without permanent forgetting.

Storage failures are not falsely reported as deletion: `source_invalidation_failed` blocks current-engine use. If the storage device/transaction cannot accept the clear, the operator must resolve it and ingest the current supported snapshot before reuse. A restart alone is not proof of deletion. This does not certify forensic erasure or storage-failure recovery.

## Execution

- New regression file against unchanged original source: **7 tests, failed**, actual RED receipt `docs/review-regressions-red.log`. The route test observed the unwanted second mismatched call, and replacement tests retained old sources. Subtest failures remain in the raw log.
- Same regression file after repair: **7 tests, OK**, `docs/review-regressions-green.log`.
- Full current suite: **152 tests, OK**, `docs/test-run-03.log`.
- Renewed offline and real model replays: `docs/evidence/offline-replay-03.json` and `model-replay-03.json`, both PASS, both bound to the current six runtime-source hashes.
- Current model fixture: 21,673 -> 3,053 request characters, 85.91% reduction; the original-context and observed-context answers agree with the declared oracle. Whole probe: 3 calls, 8,934 tokens, 15.4 seconds. This is a synthetic integration result, not a generalized accuracy/cost benchmark.

Machine-parsed counts/hashes are in `docs/evidence/review-repair-02-results.json`. These are implementation-author findings, not independent acceptance. Fresh read-only closure review and final ZIP execution remain separate gates.
