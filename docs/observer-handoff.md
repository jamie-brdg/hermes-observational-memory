# Observer/contracts handoff

Status: implemented and focused verification passed. Public function signatures match `BUILD-PLAN.md`; strict supported wire details and identity/timestamp rules are explicit below. Only the five owned files listed at the end were changed by this worker.

## Shared interfaces (stdlib only)

- `canonical_json(value) -> str`: strict JSON, sorted keys, compact separators, UTF-8-compatible text; rejects non-JSON values, non-string object keys, nonfinite numbers and excessive/cyclic nesting. Never coerces types.
- `digest_wire(wire) -> str`: lowercase SHA256 of canonical JSON encoded as UTF-8.
- `validate_sources(sources) -> list[dict]`: exact source fields from the build plan; defensive copies. Reject duplicate IDs/ordinals, non-increasing ordinal order, booleans as ordinals, mismatched digest/role/text, unsupported wire fields and non-text content. Does not normalize IDs or text.
- Supported wire keys: `role`, `content`, optional `name`, assistant-only `tool_calls`, tool-only `tool_call_id`. `tool_calls` use the standard `id/type/function{name,arguments}` structure. `content` may be absent/null only for assistant tool calls, represented by source `text == ""`. No attachments, hidden reasoning, system/developer roles or arbitrary metadata. Secret exclusion remains the ingestion boundary's responsibility; syntax validation is not secret detection.
- Source IDs are opaque nonblank strings without boundary whitespace/control characters; source `message_uid` is a string (may be empty), and `occurred_at` is a string or null. Ordinals need not be contiguous and may start above zero: incremental observer slices retain their original ordinals. This is explicitly tested in validation and both observers.
- `observation_id(source_ids, quote, kind) -> str`: `obs_` + SHA256 of a versioned canonical record with sorted, unique source IDs, exact quote and kind. Validation requires this computed identity; don't invent IDs in fixtures. Priority and timestamp do not change evidence identity.
- `validate_observations(observations, sources) -> list[dict]`: exact observation keys; every reference exists; exact nonblank substring of every reference; references have one role; attribution is derived from that role; computed IDs match; priority is a non-bool integer 0..3; kind is the plan's enum. Returns defensive copies or raises `ValueError` for the entire batch. No statuses or verified fields exist.
- `observed_at`: UTC ISO timestamp with `T`, seconds, optional 1..6 fractional digits, and `Z` or `+00:00` (calendar validity checked). Values are preserved, not rewritten.
- `render_observation(obs) -> str`: a complete one-line, canonical JSON record followed by newline. Source text is quoted/escaped data, not prompt structure. Every field counts toward reflection's character budget.
- `reflect(observations, max_chars) -> list[str]`: validates observation shape/identity; selects existing IDs only; deterministic correction/constraint/intent priority, then priority and actual UTC recency, with later log positions breaking equal-time ties. Charges full `render_observation` length. Skips records that do not fit and never rewrites or deletes input/history. `max_chars=0` returns no IDs. Source-link validation belongs at publication: reflection has no source argument and cannot re-prove that linkage.

## Observer interfaces

- `ExtractiveObserver().observe(sources, *, observed_at) -> list[dict]`: one complete exact source quote per nonblank text source, conservative kind labels, role-derived attribution. No truncation that could drop negation/qualifiers, no network or external imports.
- `ModelObserver(complete, max_input_chars=48000, max_output_chars=24000).observe(sources, *, observed_at) -> list[dict]`: injected two-positional-argument `complete(system_prompt, user_payload) -> str`; JSON-only `{"observations":[{"source_id":...,"quote":...,"kind":...,"priority":...}]}`. No generated IDs/timestamps/attribution/status fields. Strict parser rejects duplicate JSON keys, nonfinite values, extra fields, unknown IDs, fences/trailing prose, malformed types, duplicate observations and blank/empty results for eligible input. All-or-nothing. Raises `ValueError` on validation/budget/response failure, never returns a partial batch.
- Input budget covers the complete system prompt plus JSON user payload (including JSON escaping/metadata); output budget is checked before parsing. Invalid sources/timestamps and excessive input do not call `complete`. Limits are characters, not token counts. Backend owns deadlines, token caps, route pinning and opt-in.
- Empty input or sources containing only blank text yield `[]` without a completion call. Observation coverage/atomic publication and reflection-wrapper budgeting remain engine/store responsibilities.

## Important scope limits

Exact quote validation proves source linkage, not real-world truth or complete prompt-injection resistance. `kind` is descriptive metadata, not a verified state. Entire offline quotes retain plans, negation and conflicting claims; a model can still select an unrepresentative but exact substring, so prompts explicitly require material qualifiers. No actual model calls, installs, network calls, live Hermes changes, runtime configuration edits or private data are used in this slice.

## Verification evidence

Run from `/Users/mini/workspace/hermes-observational-memory`:

```sh
python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent --pattern 'test_[co]*.py'
```

Final result: **82 tests, OK**, exit 0 (44 contracts/reflection tests, 38 observer tests), including the parent's nonzero incremental-slice clarification. Parent-owned runner activates the existing managed Hermes interpreter/dependencies, disables lazy installs, and uses a disposable Hermes home. These tests do not import or invoke an actual Hermes model backend.

Earlier commands/results, retained honestly:

- `python3 -m unittest discover -s tests -p 'test_contracts.py' -v`: initial TDD RED was the absent contracts module. First implementation ran 41 tests with one error: Python 3.9's `datetime.fromisoformat` rejected a valid one-digit fraction. Switched the already regex-validated timestamp parser to `strptime`; 41 tests then passed.
- `python3 -m unittest discover -s tests -p 'test_observer.py' -v`: initial TDD RED was the absent observer module; implementation then passed 37 tests.
- Managed runner, `--pattern test_contracts.py`: two added snapshot-boundary fault tests failed (43 tests, 2 failures). Validators previously serialized caller data then checked the mutable original, allowing a repaired caller object to validate an earlier invalid copy. Fixed by checking the exact detached snapshot being returned. Final combined run above passed both regressions.
- Managed runner individual patterns `test_contracts.py` and `test_observer.py` also passed before the two additional snapshot regressions (41 and 37 tests respectively). No failed run was relabeled as passing.
- AST parsing/compilation passed for all four Python files. Explicit `git diff --no-index --check /dev/null <owned-file>` checks emitted no whitespace diagnostics for all five owned files. An initial wrapper incorrectly treated normal no-index exit 1 (files differ from `/dev/null`) as failure; corrected the wrapper to require exit 0/1 with empty diagnostic output, then reran the entire check successfully. Ordinary `git diff --check` alone is insufficient here because these files are untracked in the new repository.

Coverage includes exact non-normalized Unicode quotes and IDs; cross-source same-quote validation; duplicate sources/observations/JSON keys; booleans versus integers; unknown fields and forbidden states; mixed-role rejection; wire digest/role/text agreement; unsupported attachments/reasoning; output/input budgets at exact boundaries; hostile source strings; nonfinite/deep/cyclic JSON; callback source mutation; sanitized provider errors without retries; empty-output refusal; full rendered metadata budgets; UTC recency; retained historical records and long negated intentions. Fixtures are synthetic. Network/process calls are explicitly blocked in the offline/injected-observer side-effect regression.

## Owned files

- `observational/contracts.py`
- `observational/observer.py`
- `tests/test_contracts.py`
- `tests/test_observer.py`
- `docs/observer-handoff.md`

No edits to `__init__.py`, engine, backend, store, other tests, live Hermes, profile configuration or archives. No commits or pushes. Real-provider behavior and full engine/store integration remain the parent's verification scope.
