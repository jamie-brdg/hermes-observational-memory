# Preserved early integration findings

These are earlier failed attempts, not final release results.

1. The initial test launcher encountered macOS Python 3.9 before Hermes bootstrap could select its managed interpreter. The next attempt bootstrapped with a fresh HERMES_HOME, which triggered Hermes's automatic source-completion/dependency preparation and then timed out at 90 seconds. No test pass was claimed. The harness was corrected to resolve the supported managed interpreter, set HERMES_DISABLE_LAZY_INSTALLS=1, activate existing dependencies before redirecting application state, and avoid automatic installation on all subsequent verification commands. Installed Hermes source HEAD remained c8301ea6c9b797184df16a9c5dd462400b264ff4; this does not claim the failed bootstrap performed zero runtime metadata writes.

2. The first aggregate ran 122 tests and reported 12 errors. All engine/loader errors stopped at the symlink-path guard because Python's tempfile cache still pointed through macOS's /var symlink, despite bootstrap's environment update. The test harness now pins tempfile and TMPDIR to the owned scratch boundary. The production symlink refusal was not weakened. Parent normalization was also reconciled with the shared source contract: tool arguments stay in the local wire record, not the visible text forwarded to the Observer.

3. The SQLite component had a real POSIX lock-loss defect. See the preserved independent builder RED/GREEN record in ../sqlite-lock-repair.md. It was fixed before final replay, not waived.

4. Two new incremental/stale-worker tests passed their coverage/identity assertions but incorrectly demanded projection on short offline fixtures. A source-bound diagnostic returned:

| Fixture | Removed prefix characters | Replacement characters | Projected |
|---|---:|---:|---|
| size=80, unchanged | 6617 | 8699 | false |
| size=60, corrected | 4107 | 6531 | false |
| size=160, unchanged | 12377 | 8371 | true |

The original request was correctly retained because the exact-quote log would be larger. The tests were corrected to use an adequately long fixture for their separate must-project assertion, with a dedicated regression preserving the no-benefit/no-projection behavior. No product threshold or protection was weakened.

Claude CLI was not used as the reviewer: its early smoke failed because its OAuth session was expired. Any completed independent review in this package is a separate Hermes review, not a Claude/Opus claim.
