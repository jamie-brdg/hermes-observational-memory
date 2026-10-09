# Independent review 01 — REQUEST_CHANGES

Two concrete in-scope defects block acceptance. All **145 deterministic tests pass**; the extra independent scenarios demonstrate gaps rather than a failing existing suite. No product code or test was changed.

## Bound candidate and review identity

- Candidate: `/Users/mini/workspace/hermes-observational-memory`, v0.1.0.
- Manifest: `docs/evidence/review-candidate-01.json`, SHA-256 `6378c8a928d0b6666a793391e513149a7557a0a4187b012ca6cf3e558523d303`.
- Start verification: 2026-10-09T08:32:17.477386+00:00 — **26/26 hashes match**.
- End verification: 2026-10-09T08:40:03.155569+00:00 — **26/26 hashes match**, no drift; filesystem product/test/tool/example membership exactly agrees with the manifest.
- Installed Hermes: `c8301ea6c9b797184df16a9c5dd462400b264ff4`. Examined host files also match that commit, not only its HEAD label.
- Reviewer: separate Hermes delegated reviewer, `gpt-6-astra` / `openai-codex`. This is **not Claude/Opus review**. The earlier Claude authentication limitation is preserved, not treated as a user-required gate.
- Exact paths, hashes and examined host line ranges are in the companion JSON: all 26 frozen files read fully, eight supporting documents/receipts, six targeted host files. The new candidate is untracked, so the binding is the exact manifest, not a fabricated candidate commit.

## Blocking findings

### OM-R1 — High: queued work bypasses the actor/provider mismatch guard

**Locations:** `observational/engine.py:240–246,283–290,317–359`; dispatch at `observational/backend.py:38–51`.

`update_model()` sets `_route_mismatch` and increments the epoch, but leaves queued `_pending` work. The next `_work()` loop does not check the route and captures the *new* epoch. It therefore starts another old-pinned completion and accepts its result even after the actor has changed.

**Reproduced twice:** start model-mode observation with matching `openai-codex/gpt-6-astra` pins and consent; hold its first completion; enqueue a newer completed-turn snapshot; switch the actor to `custom/synthetic-local-only`; then release the first completion. The actual engine, ModelObserver, HermesCompletion and SQLite are used; only provider resolution/client output is replaced by a synthetic client, with socket connections prohibited.

**Observed:** two completion dispatches. At the second dispatch `_route_mismatch=true`, actor provider `custom`, requested observer model still `gpt-6-astra`. One observation covering ten sources is published; `last_error=null`; one old result was discarded. Thus discarding the first stale result does not prevent a second unauthorized-by-current-route batch.

This violates the actor/pin requirement in `README.md:19` and `docs/BUILD-PLAN.md:26`. It is a demonstrated completion-boundary authorization defect, **not a claim that private data was transmitted during review**. An already-sent request cannot be retroactively unsent; the blocker is a newly initiated queued call.

**Required:** invalidate mismatched pending work and check current route/epoch at every new dispatch and publication. Add a queued-work/model-switch regression; preserve no fallback and the distinction between newly dispatched and already-in-flight calls.

### OM-R2 — Medium: rejected replacement retains removed sources and accepts an old worker

**Locations:** `observational/engine.py:266–282,317–363,437–459`.

On unsupported/sensitive/invalid replacement input, the post-turn hook returns before source synchronization and does not invalidate the worker epoch. Its old source revision remains eligible for publication and read-only recall. A later successful old commit also clears the recorded ingestion error.

**Reproduced twice through actual installed host hooks:** observe six synthetic text turns with a held offline observer; supply a completed replacement snapshot that removes the first turn and appends a structured-content turn; let normalization reject it; release the old observer. Query the real store and `om_recall`, then close/reopen and query again.

**Observed:** source revision stays `1` after replacement rejection, then becomes `2` when the old worker publishes. The removed marker is absent from the supplied current history, but its old source remains recallable and a derived observation is published. It is still recallable after restart. `unsupported_or_sensitive_input` is replaced by `last_error=null`. The actual host request-selection helper correctly preserves the changed actor request; **that does not repair stale persistence and tool exposure**.

`docs/BUILD-PLAN.md:28,57` promises source deletion/current-source recall. Unsupported attachments are allowed to leave the actor request uncompressed, not to make removed plugin data indefinitely current. This is not a request to support multimodal observation or perform bulk archive deletion.

**Required:** failed authoritative-snapshot ingestion must invalidate stale work and conservatively reconcile/quarantine obsolete source/recall state. Keep attachments/secrets out and preserve the actor transcript. Regress existing and in-flight observations, restart and source recall. Do not convert this into model-controlled permanent session forgetting.

## Verification actually executed

Working directory: `/Users/mini/workspace/hermes-observational-memory`.

```sh
PYTHONDONTWRITEBYTECODE=1 HERMES_DISABLE_LAZY_INSTALLS=1 python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent
```

- First independent run: **145 tests, 3.598s, OK, exit 0**.
- Final finite confirmation: **145 tests, 3.444s, OK, exit 0**.
- All executed test IDs are recorded and reconciled programmatically to every static test method, with final raw output in the JSON. No skips or substituted partial suite.
- Managed runtime observed: Python `3.14.7`, SQLite `3.53.1`.
- The independent scratch probe ran twice, exit 0 both times. Its assertions intentionally confirm the two defects and the nonblocking deadline characterization; this is not a product PASS. Exact script bytes/hash and observed results are embedded in the JSON. All synthetic state was cleaned. The temporary script is removed after reporting.

Existing passing coverage includes strict quote/attribution/JSON validation; partial-output rejection; source revision and publication CAS; true independent-process SQLite lock oracles; process crash recovery; tombstones/forgetting; page-size rollback; symlink/hardlink/inode refusals; create-only install; real user-plugin loader; host post-turn and request-selection hooks; unchanged canonical history and scoped tools.

## Replay and previous repairs

- `model-replay-02.json`: SHA-256 `4e19f7c4a82382271ee9305ac7161eb83cd9fb7b427261dad81cd5506d26846f`.
- `offline-replay-02.json`: SHA-256 `6f95c92d8923c0cf13d101060cc1978b51d6bd961b66cdb8540940f4e4c423fa`.
- Both receipt hashes and all six recorded runtime-source hashes match the frozen candidate. Offline analysis of the exact synthetic fixture validates every recorded quote/identity/attribution, declared counts, reflection and complete rendered memory text. Model baseline/observed/expected answers agree; usage totals reconcile. No replay module top-level or hosted model/network call was rerun.
- Prior receipts are evidence of their declared fixtures, not independent broad accuracy/cost proof. The offline replay has no actor-answer accuracy comparison.
- Read the preserved raw-fd SQLite repair and publication-CAS repair notes. Current source contains both repairs, and their regressions pass independently. Historical adverse records were not rewritten or relabeled.

## Bounded nonblocking limitations

1. **No total publication latency guarantee.** A real separate SQLite connection held `BEGIN IMMEDIATE`. A timely observer result reached the write attempt at 0.001838s, the lock was released at 1.256820s against a 1s job setting, and eight observations committed without error. The deadline check is before potentially blocking storage. This is a characterization, not evidence that a *late observer result* was accepted. Strict end-to-end deadline semantics would need a separate tightened contract/implementation.
2. **Cancellation/cost are bounded honestly.** Arbitrary injected Python threads cannot be forcibly killed; installed Codex streaming uses progress-aware timeout logic plus a separate ceiling. No absolute 90-second termination or billing-token cap is certified.
3. **Exact attribution is not truth or injection immunity.** Lossy reflection and a misleading-but-verbatim model substring remain declared limits. No new external-truth, perfect qualifier, lossless-memory or perfect prompt-injection requirement is introduced.
4. **POSIX private storage, not encryption/DLP.** Static path defenses and real lock preservation pass; same-UID/privileged sabotage, network filesystems, Windows, forensic SSD erasure, external provider retention and backups are outside this certification.
5. **Session-only request shaping.** No archive ingestion/cross-session memory, durable/emergency compression, LongMemEval result or total-cost superiority claim. Best-effort host hooks and oversized unsupported requests remain explicit limits.
6. **Mutation review is bounded.** Reviewed actual host structural clones, prefix equality, detached validator snapshots and selected-message deep copies; no write-through to canonical history was observed. Hypothetical concurrent mutation of an owned request or data already in a running call was not promoted to a demonstrated exploit.
7. **ZIP/live operation are separate.** Package allowlist/code reviewed; final ZIP execution belongs to the parent lane. No live installation/activation/configuration/profile/gateway/credentials action occurred in this review. Only the installed revision and synthetic macOS fixtures are certified.

## Required disposition

**REQUEST_CHANGES** for OM-R1 and OM-R2. Preserve this source-bound adverse review. Repair against a new frozen candidate, add the missing regressions and rerun independent acceptance. This verdict does not activate the plugin or close the parent's delivery task.
