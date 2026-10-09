# MemoryStore handoff

Owned paths only: `observational/store.py`, `tests/test_store.py`, and this document.
No live Hermes/config/history/profile changes, installs, network/model calls, or commits.

## Implemented API and explicit semantics

- Implements the frozen `MemoryStore` API. One owner-only SQLite file is bound to the exact profile/session pair and schema version; mismatches refuse access.
- Source revision is a monotonically increasing CAS token for the ordered source snapshot. Identical source sync is a no-op. Publication changes generation, not source revision; identical publication is a no-op. Generation advances on each logical source/publication/forget change.
- `commit_observation` **replaces the complete observation snapshot** with the validated caller-supplied list. The engine must include retained log entries when publishing another batch; reflection omissions belong only in `active_ids`. This does not automatically accumulate independent batches.
- Every write performs `BEGIN IMMEDIATE`, then checks authoritative state. Stale revision, disabled session, or non-prefix coverage returns `False`. Structurally invalid arguments/observations/active IDs raise `ValueError`. Nonempty covered sources require at least one valid observation. Active IDs retain caller order and cannot be duplicated or unknown.
- Sync invalidates coverage at the first changed full source record (including identity/ordinal/metadata), keeps only the unchanged covered prefix and observations entirely contained in that prefix, and removes invalid active IDs. Append retains prior covered evidence. If no observations survive, coverage is cleared conservatively.
- `forget()` clears the source/observation payload and advances revision/generation, persisting a disabled tombstone. Subsequent sync is a no-op returning its current revision; every subsequent publication returns `False`, including from other already-open connections. Repeated forgetting is idempotent.
- Recall returns exactly the six frozen fields, with character-based offsets and `next_offset=None` at EOF. Missing/currently removed IDs raise `KeyError`. Positive limits clamp to 4000 characters. Offset beyond EOF yields an empty final page.
- Search is literal case-insensitive Unicode casefold search in current source order. No SQL wildcard interpretation. Query must be nonblank and at most 1024 characters; results clamp to 20 (default 8); excerpts are exact source substrings of at most 400 characters, returned with the recall-shaped source/role/text/offset/pagination metadata.
- Shared pure contracts validate source/observation payloads both on write and read. Returned and stored data are detached from caller-owned dicts. Disabled tombstones deliberately ignore attempted source ingestion rather than inspecting/retaining it.
- File is 0600; leaf parent is 0700. Missing directories are created 0700; existing broader leaf-directory/file permissions are **refused, not silently chmodded**. Symlinked path components, database and sidecars, hardlinked databases, and replaced path identities are refused. Caller should give the store a dedicated private directory. Parent path traversal (`..`) is refused, not normalized.
- SQLite uses DELETE journaling, FULL synchronization, `secure_delete=ON`, in-memory temp storage, a per-connection page cap, and a UTF-8 JSON payload bound. Limit includes database pages (rounded down to page size), not transient rollback-journal bytes. Conservative failure is possible before logical payload reaches the configured byte maximum because SQLite needs page overhead/free space. Errors leave the prior snapshot intact.
- RLock serializes each connection; SQLite serializes independent connections/processes with a 10-second busy timeout. A store inherited across fork is refused before acquiring its inherited lock: reopen inside the child. Close is idempotent; later calls raise `RuntimeError`.

## Verification evidence

Initial RED receipt, exact command:

```text
python3 -m unittest discover -s tests -p test_store.py
E
======================================================================
ERROR: test_store (unittest.loader._FailedTest)
----------------------------------------------------------------------
ImportError: Failed to import test module: test_store
Traceback (most recent call last):
  File "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/unittest/loader.py", line 436, in _find_test_path
    module = self._get_module_from_name(name)
  File "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/unittest/loader.py", line 377, in _get_module_from_name
    __import__(name)
  File "/Users/mini/workspace/hermes-observational-memory/tests/test_store.py", line 14, in <module>
    from observational.contracts import digest_wire, observation_id
ModuleNotFoundError: No module named 'observational.contracts'


----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

This was the expected missing parallel-owned dependency, not a behavioral red. No dependency stubs or test skips were introduced. After real `contracts.py` and store implementation existed, the same command returned:

```text
.................
----------------------------------------------------------------------
Ran 17 tests in 0.372s

OK
```

The final expanded suite was exercised through the parent's managed-runtime runner with lazy dependency installation disabled:

```text
python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent --pattern test_store.py
----------------------------------------------------------------------
Ran 25 tests in 0.342s

OK
```

Exit status: 0. A preceding expanded-suite execution also passed 25 tests in 0.318s. No behavioral failures were suppressed, skips added, or assertions weakened. The only initial test failure was the missing parallel-owned dependency reproduced above.

Coverage includes real spawned-process concurrent first open/write, a held stale worker released after durable forgetting, and process kill while a real SQLite write transaction is open followed by recovery of the prior committed snapshot. Also covered: shared-instance threaded writes, exact-prefix edit/undo/removal/reorder/metadata invalidation, multi-source dependency invalidation, scoped Unicode pagination/search, literal SQL-hostile queries, strict input and persisted-data validation, byte-identical namespace-denial readback, reopen/lifecycle handling, private modes (including an open rollback journal), symlink/hardlink refusal, replacement denial, both JSON preflight and real SQLITE_FULL rollback, observation-size rejection, and absence of synthetic removed/forgotten payload markers in database bytes.

All fixtures are synthetic and use disposable repository-local state. A post-run search found no remaining `.store-test-*` paths. Source and test writes passed the tool's Python syntax lint. Tests deliberately pass malformed values at validation boundaries; `typing.cast(Any, ...)` documents these negative cases without changing runtime behavior.

Whitespace review note: an initial chained `git diff --no-index --check /dev/null ...` returned exit 1 with no diagnostics because untracked files differ from `/dev/null`; it short-circuited before the remaining comparisons. This is not recorded as a successful complete review. The follow-up ran every owned comparison independently and checked diagnostics separately from expected no-index difference status. It exited 0 with these exact results:

```text
observational/store.py diff_exit=1 whitespace=PASS
tests/test_store.py diff_exit=1 whitespace=PASS
docs/store-handoff.md diff_exit=1 whitespace=PASS
```

Git status confirmed all three owned files are new/untracked; nothing was staged or committed.

## Honest boundaries

- This store is private local persistence, **not encryption** and not a secret classifier. Engine ingestion owns secret filtering and complete-turn eligibility. No source payload is logged by the store.
- POSIX owner-only paths and no-follow checks reject static symlink attacks and path substitutions observed before operations; they do not promise protection against concurrent privileged/same-UID filesystem sabotage between checks and SQLite's pathname open. Windows ACL support is not implemented or claimed.
- `secure_delete` and DELETE journaling remove current SQLite payloads, not OS snapshots, SSD history, backups, host transcripts, provider retention, or copies held in a stale worker's memory. A stale worker cannot republish those copies after a persisted tombstone.
- Single-snapshot JSON deliberately avoids a complex relational schema. Recall/search validate and scan a bounded snapshot, so they are not a full-text index and may cost O(database payload). No network, host-hook, model, or accuracy claim is made by these storage tests.
- Independent review and parent engine/integration acceptance remain outstanding.
