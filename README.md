# Hermes Observational Memory

A native Python **Hermes ContextEngine plugin**: background observation, a bounded evidence log, request-only context selection, and original-source recall. No Mastra/Node service, vector database or additional Python packages are required by the plugin.

**Version 0.1.0. Build/test artifact, not automatically activated.** The store supports POSIX systems (tested on macOS); Windows is not supported in this release. This is a deliberately session-scoped first release. It does not replace Hermes's selected long-term memory provider or merge memories between profiles/threads.

## What it does

1. After a completed turn, capture supported visible conversation text in a private local per-session SQLite file.
2. Observe older complete turns, keeping the latest two turns verbatim by default.
3. Retain source-linked exact quotations rather than allowing invented paraphrases to become evidence.
4. Reflect the log deterministically into a bounded selection, prioritising corrections, constraints and intentions. Unselected records remain locally recallable.
5. Replace only the already-observed prefix of an individual model request. Canonical Hermes conversation history is not rewritten.
6. Expose `om_search`, paginated `om_recall` and `om_status`, scoped to that engine's exact session.

There are two modes:

- **Extractive, default:** entirely offline. Whole source statements are retained and a bounded selection is shown. This is conservative but less compact/intelligent than model extraction; oversized statements may remain uncompressed.
- **Model, explicit opt-in:** a pinned model selects useful verbatim quotes. This release enables only the existing `openai-codex` Hermes route. The actor's model/provider must match the pins. A route change cancels queued work and invalidates prior jobs, including a change away and back. The captured job authorization is checked before provider resolution and again at completion admission; already-admitted calls cannot be retroactively unsent. There is no automatic alternative-provider fallback. Source text leaves the machine through that existing provider when enabled.

The Reflector is intentionally **not another free-form LLM rewrite**. It selects existing validated evidence instead of repeatedly paraphrasing facts until provenance disappears.

## Improvements and boundaries

| Concern | This implementation |
|---|---|
| Past plan incorrectly becomes completed action | No automatic completed/verified state. Every quote remains attributed to a user, assistant or tool. Elapsed dates never trigger state changes. |
| Hallucinated memory | Every quote must be an exact substring of its declared source; unknown IDs and output fields fail the whole batch. This proves attribution, not external truth or preservation of every qualifier. |
| Corrections and conflicting statements | Priority for explicit corrections; originals remain recallable. Old claims are not silently rewritten as verified truth. |
| Source instructions laundered into authority | Memory is explicitly labelled historical untrusted evidence, never system instructions; the Observer gets no tools. This is not a proof of perfect prompt-injection resistance in the actor. |
| Other profile/thread leakage | Separate database namespace and session path; recall/search accept no alternate identity/path arguments. |
| Bad/late/stale model output | Reject publication, retain the original actor request. One in-flight worker per engine. |
| Privacy | No system/developer prompts, hidden reasoning or attachments are forwarded to the Observer. Secret-pattern matches reject ingestion. Detection is heuristic, not comprehensive PII/DLP protection. |
| Forgetting | Human-only CLI clears plugin source/observation payloads and persists a disabled session tombstone. It does not erase Hermes's original transcript, external provider retention, RAM already in a running call, or external backups. |
| Prompt cache | Rendering is stable for an unchanged stored generation. A changed selection can still invalidate a prompt cache; no total-cost saving is claimed. |

## Install, without activation

Choose the **one exact profile home** you mean to use. The installer is create-only and will not overwrite an existing plugin, follow a symlink target, modify `config.yaml`, or activate anything.

```bash
python3 tools/install.py --home /absolute/path/to/your/hermes-home
```

The installed host's user-engine discovery uses:

```text
<profile-home>/plugins/observational/
```

This is distinct from Hermes's **bundled** `plugins/context_engine/<name>/` source directory. The plugin is verified through the real user-directory loader, not merely imported by its development path.

## Activation is a separate explicit step

After reviewing the test evidence, select `context.engine: observational` through the existing Hermes configuration UI/CLI for the intended profile. For the default profile only, the command is:

```bash
hermes config set context.engine observational
```

Start a **new session** through the supported UI. Do not restart a shared messaging gateway merely to test this plugin. The live configuration has not been changed by this repository's installer or test harness.

No plugin configuration file is required for offline mode. Optional settings live at:

```text
<profile-home>/observational-memory.json
```

See `examples/extractive.json`. `examples/model-opt-in.json` is an explicit data-egress opt-in, not a default to copy blindly. Its provider/model pins must match the actor and be available on that exact profile. This first bridge does not automatically select a local model or a different provider.

**Pilot in a fresh session.** Activating in an old conversation can make the current history delivered by the post-turn hook eligible for capture. There is no bulk archive crawler or automatic corpus import.

## Rollback / disable

Select the built-in engine again for the same profile:

```bash
hermes config set context.engine compressor
```

Then start a new session. The plugin never rewrites canonical history, so no transcript restoration is required. Disabled selection does not automatically delete its local copies.

## Forget a plugin copy

First inspect the exact session ID in Hermes's session interface. A dry run makes no change:

```bash
python3 tools/forget.py --home /absolute/profile/home --session-id EXACT_SESSION_ID
```

To confirm deletion of **only this plugin's copy**:

```bash
python3 tools/forget.py --home /absolute/profile/home --session-id EXACT_SESSION_ID --confirm-plugin-copy-deletion
```

The empty tombstone deliberately remains. Deleting the database file manually removes that protection and can permit later re-ingestion. A forgotten session cannot be re-enabled by a model tool. Start a new session if you want a new memory boundary.

## Reproduce verification

Use the installed Hermes source path, not an assumed virtual environment:

```bash
python3 tools/run_tests.py --hermes-repo /absolute/path/to/hermes-agent
python3 tools/replay.py --hermes-repo /absolute/path/to/hermes-agent --output /new/path/offline-replay.json
```

A bounded model-backed synthetic comparison is **separate**, uses the existing pinned route, and never reads real conversation history:

```bash
python3 tools/replay.py --hermes-repo /absolute/path/to/hermes-agent --allow-model-call --provider openai-codex --model gpt-6-astra --output /new/path/model-replay.json
```

Receipts are create-only so failed runs cannot be overwritten. The replay compares original-context and observed-context answers on the same clearly synthetic scenario, checks exact recall/restart/forgetting, and records actual usage. Character reduction is not token reduction, an accuracy benchmark, or whole-system cost saving.

`tools/run_tests.py` disables Hermes lazy dependency installation, resolves its managed interpreter, then redirects application state into an owned scratch directory. The plugin's core modules are stdlib-only. The tests exercise the actual installed ContextEngine ABC, plugin loader and host post-turn/request-selection call sites.

## Known limitations

- Session scope only. New conversations use their own observation store; existing cross-session memory remains Hermes's responsibility.
- Plain visible text only. A rejected completed snapshot (structured/multimodal input, secret-pattern match, incomplete tools or oversized transcript) keeps the actor request intact, invalidates old worker jobs and conservatively clears the plugin's previous mirror. It does not permanently forget the session: the next supported snapshot can populate it again. No rejected content is stored. If storage itself prevents invalidation, the current engine blocks recall/projection and reports `source_invalidation_failed`; resolve the storage problem and ingest a valid current snapshot before reuse, rather than treating a restart as proof of deletion.
- Read-only **request shaping**, not durable history compaction. Manual `/compress` is intentionally a no-op for this engine. It does not implement emergency compression when no validated observations are ready. A huge unsupported request can still exceed the host/provider context limit.
- Background callbacks are best-effort in Hermes. Some abnormal terminal paths do not emit the post-turn hook.
- Whole-source offline extraction can omit a large important statement from the bounded active selection; it remains available by search/recall. A model can also select a misleading substring even when the quote is verbatim. Review original sources for consequential decisions.
- The log is bounded in the prompt, not a lossless brain. SQLite stores the current source snapshot and full observation log under an explicit storage limit; this simple snapshot design is not a large-corpus search engine.
- Privacy is local filesystem isolation, not database encryption. The machine owner and compromised same-user processes are outside this boundary.
- A timeout prevents a late result from committing; Python cannot forcibly kill an arbitrary injected observer thread. The shipped network adapter has its own timeout and no SDK retry loop. Codex does not honour `max_tokens` on this route, so the output acceptance limit is not a billing-token cap.
- Only the installed Hermes revision in the verification receipt is tested. Plugin APIs and transport adapters may change.
- No LongMemEval run or broad claim of superiority over Mastra/Hermes memory is made.

## Evidence and source references

`docs/BUILD-PLAN.md` records scope and authorization. `docs/*handoff.md` preserve component results. Final verification and independent review receipts are kept under `docs/evidence/` and `docs/reviews/` when completed.

- [Hermes context-engine contract](https://hermes-agent.nousresearch.com/docs/developer-guide/context-engine-plugin)
- [Hermes memory-provider separation](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin)
- [Mastra Observational Memory](https://mastra.ai/docs/memory/observational-memory), inspiration rather than a dependency
