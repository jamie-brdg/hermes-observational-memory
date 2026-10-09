# Native observational context engine

## Authority and scope

User instruction: "build the native and improve it if you can". Build a native Python Hermes ContextEngine plugin in this new repository. Do not modify the installed Hermes source, active default configuration, any existing memory backend, other profiles, gateways, or archives. Installation/activation on the live profile remains separate. Synthetic-only local tests and bounded model calls through the already configured Hermes provider are permitted for verification; no new paid provider route or credentials.

## Product truth

A source-linked, session-isolated continuity layer for long Hermes conversations. It keeps exact supported source text locally, asynchronously observes completed turns, deterministically reflects the observation log into a bounded prompt, and exposes read-only source recall. It does not decide permissions, execute remembered intentions, claim verified completion, change model weights, or promise lossless summaries.

## First vertical slice

Synthetic conversation -> native Hermes post-turn hook -> private source store -> validated observation batch -> bounded reflection -> request-only context selection -> original source recall -> restart -> human-controlled plugin-copy deletion.

Request selection is deliberately non-destructive: canonical Hermes conversation history stays unchanged. v0.1 does not persist compressed generations back into Hermes or implement emergency destructive clipping. If observations are unavailable, mismatched, late, or invalid, preserve the original request. Large unsupported turns can still reach the host/provider limit and must be reported honestly.

## Improvements over naive observer/reflection memory

- Source-linked exact quotes with strict reference validation; generated paraphrases cannot become evidence.
- No automatic `verified` or completed state. User statements, assistant statements, and tool output remain attributed claims.
- Reflection selects/merges existing evidence, never fabricates new statements or treats elapsed time as completion.
- Separate profile AND session identity; no arbitrary cross-thread lookup tools.
- Complete-turn boundaries preserve tool-call/result pairs and the latest user turn.
- Stable prompt rendering until the source/observation generation changes.
- Non-blocking observation, one in-flight job, bounded per-call inputs/outputs, deadline checks and stale-generation discard.
- Explicit model-call opt-in, pinned current provider/model and no automatic cross-provider fallback. Offline extractive mode also works without a model or network.
- Read-only recall/search/status tools; destructive plugin-copy forgetting is human CLI only.
- Atomic SQLite state, source deletion/tombstones, no source content in operational error logs.

## Architecture

`observational/`: installable user context-engine plugin; standard library core; Hermes imported only at the engine/backend boundary.

- `contracts.py`: pure shared source/observation validation and deterministic reflection.
- `store.py`: private per-session SQLite persistence and CAS publication.
- `observer.py`: exact-quote extraction, constrained model prompt/parser, offline extractive observer.
- `backend.py`: opt-in same-route Hermes client; no tools or provider fallback.
- `engine.py`: installed ContextEngine ABI, worker/lifecycle, request-only projection, tools.
- `__init__.py`, `plugin.yaml`: discovery without import-time network/state writes.
- `tools/`: isolated Hermes bootstrap, replay, install/package and human forgetting helpers.
- `tests/`: deterministic, hostile, concurrency/restart, real host-loader/hook integration tests.

## Frozen cross-module data contract

A source is a JSON dict with exactly these required fields:
`id` (nonempty stable string), `ordinal` (nonnegative int), `role` (`user|assistant|tool`), `text` (string), `wire` (valid JSON dict preserving supported API message fields), `digest` (SHA256 hex of canonical wire), `message_uid` (string, optional empty), `occurred_at` (string or null).

An observation is a JSON dict with:
`id` (stable string), `source_ids` (nonempty list of source IDs), `quote` (nonempty verbatim substring of EACH referenced source's `text`), `kind` (`intent|reported_outcome|preference|constraint|correction|fact|tool_output|other`), `priority` (int 0..3), `attribution` (`user_statement|assistant_statement|tool_output` derived from source role, never mixed), `observed_at` (UTC ISO string).
No generated status, confidence, next action, instruction, or verified field is accepted. `kind` describes a quoted statement, never an independently established fact. Unknown fields are rejected. No source attachments, images, hidden reasoning, system/developer prompts or secret-bearing input is admitted to the observer in this first slice. Unsupported inputs keep the original actor context.

`contracts.py` public functions: `canonical_json(value)->str`, `digest_wire(wire)->str`, `validate_sources(sources)->list[dict]`, `validate_observations(observations,sources)->list[dict]`, `reflect(observations,max_chars:int)->list[str]` returning active observation IDs, `observation_id(source_ids,quote,kind)->str`. Validation raises `ValueError`, does not mutate inputs. Reflection is deterministic, chooses existing IDs only, prioritizes corrections/constraints/intents and recent high-priority facts; every omitted record stays available in the store. Budget accounts for full rendered observation metadata via `render_observation(obs)->str`.

`observer.py` API: `ExtractiveObserver.observe(sources, *, observed_at)->list[dict]`; `ModelObserver(complete, max_input_chars=48000, max_output_chars=24000).observe(sources, *, observed_at)->list[dict]`. `complete(system_prompt:str,user_payload:str)->str` is supplied by parent backend. Model output may contain only `source_id`, `quote`, `kind`, `priority` per item in a JSON `observations` array; code assigns IDs, attribution and timestamp, then validates. Reject invalid output atomically, no partial success and no guessing malformed source IDs. Source text is explicitly untrusted input. No source/system instructions may override the observer contract. Empty output for nonempty eligible input is a failed observation, not permission to discard history.

`store.py` API: `MemoryStore(path:Path, profile_key:str, session_id:str, max_bytes:int=67108864)`; `sync_sources(sources)->int` (current revision, idempotent for identical ordered sources, replace current snapshot atomically); `read()->dict` with `revision`, `sources`, `observations`, `covered_ids`, `active_ids`, `generation`, `disabled`; `commit_observation(revision:int, covered_ids:list[str], observations:list[dict], active_ids:list[str])->bool`; `recall(source_id:str,offset:int=0,limit:int=4000)->dict`; `search(query:str,limit:int=8)->list[dict]`; `forget()->None` clears every plugin source/observation payload and persists a disabled tombstone; `close()->None`.
Commit accepts ONLY an unchanged revision and covered IDs matching an exact prefix of current source IDs; observations must pass shared validation against covered sources; active IDs must exist, be unique, and preserve caller order. Replacing/undoing/changing a source invalidates dependent observation coverage; appending can retain a still-valid covered prefix. Source removal deletes its plugin copy and derived observations. `forget` prevents future ingestion/publication by that session even from stale workers. All methods thread-safe; connection lifecycle safe; database namespace is verified on reopen. Private file/dir permissions and symlink refusal. Recall only current sources; response names `source_id`, `role`, `text`, `offset`, `next_offset`, `has_more`; search bounded excerpts plus source IDs. No network.

## Tests and release gates

1. TDD for storage, observer validator and reflection, then full deterministic tests.
2. Real installed Hermes loader, ABC, request-selection/post-turn hook integration with disposable HERMES_HOME and synthetic state.
3. Small real-model synthetic observer call through the existing configured route; retain provider/model, usage, elapsed and validation results without secrets.
4. Synthetic multi-turn replay with corrected date, unsent intention, misleading assistant claim, hostile source text, paired tools, duplicate text, source revision, restart, scope denial, stale worker and forgetting.
5. Independent read-only code/privacy review against the actual completed candidate, then parent re-run of required fixes/tests.
6. Package installable files, instructions, source manifest and evidence. No activation on live profile.

## Review availability

Claude CLI smoke failed before inference: OAuth session expired and could not be refreshed (9 October 2026). No Claude review is claimed. A separate Hermes reviewer may review the artifact; a Claude-specific gate was not requested by the user. Preserve this limitation in the review record.

## Boundaries of claims

A synthetic replay proves integration/behavior on declared fixtures, not LongMemEval accuracy, total-cost savings on real work, or complete prompt-injection resistance. A source-only checked quote proves attribution to the stored text, not that its external claim is true. Plugin forgetting does not erase Hermes's separate canonical transcripts, provider retention, or backups outside this plugin.
