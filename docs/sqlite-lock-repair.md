# SQLite process-lock repair

This is an addendum, not a replacement for `store-handoff.md`. The original
findings and handoff are intentionally unchanged. This repair owns only
`observational/store.py`, `tests/test_store.py`,
`tests/test_sqlite_lock_safety.py`, and this document.

## Reproduced defect (RED before implementation)

The old store retained a raw `_file_fd` for the same inode SQLite opened.
Closing another store—or cleaning up a failed constructor—closed that raw
file descriptor. POSIX process-scoped record locks were lost even though the
first SQLite connection still reported an active transaction. SQLite's own
connection-close handling is not the problem: it coordinates/defer-closes its
own descriptors when another connection needs the inode's locks.

The new regression was written and run against the unchanged implementation
before the production repair. Both original regression cases failed:

```text
python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent --pattern 'test_sqlite_lock_safety.py'

FAIL: test_closing_second_store_does_not_unlock_first
FAIL: test_failed_constructor_does_not_unlock_existing_connection
AssertionError: Tuples differ: ('busy', 'acquired', 'acquired') != ('busy', 'busy', 'acquired')
Ran 2 tests in 0.586s
FAILED (failures=2)
exit code: 1
```

The tuple records independent child attempts **before the action, after the
action while the first transaction remains active, and after rollback**.
The first case uses two real `MemoryStore` instances in one process, issues
`BEGIN IMMEDIATE` on the first connection, then closes the second instance.
The second case injects constructor failure just before SQLite connection
creation to cover preflight/exception cleanup, including the tempting but
unsafe workaround of moving a raw close earlier in construction.

## Implementation

- Remove `_file_fd` entirely. Existing database validation uses no-follow
  `stat`, retained directory identity, and a cached `(st_dev, st_ino)` pair;
  only SQLite opens/closes a published database inode.
- Preserve private creation without changing the process-wide umask or
  chmodding an existing file. Exclusively create a random empty staging file
  at `0600` inside the validated `0700` parent; validate and close its raw
  descriptor **before** publishing that inode at the database pathname.
- Publish with a non-overwriting hard link, then unlink the staging name.
  A directory `flock` serializes cooperating constructors through this short
  publication window, so they never reject the temporary two-link state.
  The directory lock is released **before** opening SQLite or waiting on
  `BEGIN IMMEDIATE`. It is not a database-file descriptor or SQLite lock.
- Recheck the created/published inode identity and require the final file to
  be singly linked, owner-owned, regular, and exactly `0600`. Keep the
  existing leaf-parent `0700`, directory identity, leaf/ancestor symlink,
  sidecar, size, namespace and schema checks.
- Use SQLite URI `mode=rw`, not implicit create, after preflight. A removed
  pathname must not make SQLite silently create an unchecked replacement.
- Normal close and constructor cleanup close the SQLite connection and
  directory descriptor only. No global connection registry or assumption
  that every SQLite connection belongs to `MemoryStore` is required.

Store-test byte inspections now happen after explicitly closing all relevant
SQLite connections. In particular, a SQLite transaction context manager alone
does not close its connection; that fixture now also uses `closing(...)`.
Disposable store/lock fixtures use the explicit
`~/.hermes/cache/scratch` boundary.

## Verification

All database fixtures were newly created, synthetic, and owned by the tests.
No live external database was opened, copied, hashed, or otherwise read. No
Hermes runtime/configuration changes or package installations were performed.
The provided runner selects managed Python, disables lazy installs and
redirects application state into disposable scratch.

The lock probe launches `sys.executable -I` as a fresh independent process,
uses `mode=rw`, a 0.2-second SQLite timeout and a 15-second subprocess bound,
accepts only the actual `SQLITE_BUSY` code as contention, and rolls back every
successful acquisition. It does not infer safety merely from the parent
connection's `in_transaction` flag. Each final case requires
`('busy', 'busy', 'acquired')`:

1. Close a second `MemoryStore` while the first holds `BEGIN IMMEDIATE`.
2. Inject constructor failure before SQLite opens and run real cleanup.
3. Let the real constructor fail with `SQLITE_BUSY` and run SQLite close
   cleanup. Only this case's constructor busy timeout is shortened to 1 ms
   by a connection subclass; production retains 10 seconds.
4. Close a `MemoryStore` while the lock owner is a plain `sqlite3.Connection`
   outside `MemoryStore`.

Exact recorded runs:

| Stage | Command pattern | Result | Elapsed | Exit |
| --- | --- | --- | --- | --- |
| RED, original implementation | `test_sqlite_lock_safety.py` | 2 tests, 2 failures | 0.586s | 1 |
| First GREEN, original regression pair | `test_sqlite_lock_safety.py` | 2 tests, OK | 1.067s | 0 |
| First GREEN, unchanged store coverage | `test_*store*py` | 25 tests, OK | 0.402s | 0 |
| Final lock coverage | `test_sqlite_lock_safety.py` | 4 tests, OK | 2.089s | 0 |
| Final store coverage | `test_*store*py` | 31 tests, OK | 0.530s | 0 |

Final commands (working directory `/Users/mini/workspace/hermes-observational-memory`):

```sh
python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent --pattern 'test_*store*py'
python3 tools/run_tests.py --hermes-repo /Users/mini/.hermes/hermes-agent --pattern 'test_sqlite_lock_safety.py'
```

The final 35 tests include the original namespace, private-permission,
symlink/hardlink, atomicity, crash recovery, real-process concurrent
initialization/writes and stale-worker tests. Added store tests also reject
all raw file opens/closes on an existing DB path, verify private descriptor
closure before publication, detect replaced file/directory/staging inodes,
recheck parent permissions, and hold the two-link publication window open
while another constructor attempts entry. Both threads complete successfully
with a singly linked final file and no staging residue.

Source hashes for the final runs (SHA-256):

```text
898715f242407c66c2c90a76e494ec093ec7882bee5cc81d762f60ef0bb39fdb  observational/store.py
3f140f4b62f58cd02175facb7595212287450407c326efc60f0a20887a1daac7  tests/test_store.py
f6230a719bfbebb10add855f20d49f97efb04fd299fd0e63165aec5ad8c0771e  tests/test_sqlite_lock_safety.py
```

## Boundaries and caveats

- Verified on this macOS host with its managed SQLite/Python runtime. The
  implementation is POSIX-specific (including directory `flock`); this is
  not Windows or network-filesystem certification. Directory-lock waiting
  is separate from SQLite's busy timeout.
- The private parent is a required trust boundary. Cached identities and
  before/after path checks preserve fail-closed replacement detection; they
  do not make pathname-based SQLite opening atomic against a hostile
  same-UID process that can swap and restore paths between checks. No claim
  of protection against such an adversary is made.
- Raw open/close by unrelated application code can still destroy process
  locks. This repair removes that behavior from `MemoryStore`; it cannot
  repair other callers. Never raw-read/hash/copy an open SQLite database in
  the same process for diagnostics.
- A process death or filesystem error between link publication and staging
  unlink can leave an extra private hard link. Future construction refuses
  that file rather than weakening the single-link check. This tiny creation
  window has no automatic orphan recovery; inspect it offline with all
  database users stopped. Ordinary transaction crash recovery remains
  covered by the store suite. A crash before publication can leave an empty
  private staging orphan.
- Only store and lock suites were run for this repair; engine/backend and
  broader integration verification belong to the parent task. No commit
  was made, and independent final review is still required.
