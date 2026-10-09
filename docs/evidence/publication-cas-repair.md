# Publication CAS repair

The initial state revision advanced on source edits but not on observation publication. Two independent workers could therefore capture the same revision, then publish out of order: a stale shorter observation snapshot replaced a newer longer one.

A new regression, `tests/test_publication.py::PublicationRaceTests.test_stale_observer_cannot_replace_a_newer_publication`, failed against the unchanged candidate (`AssertionError: True is not false`, one test, exit 1). It uses two real SQLite-backed MemoryStore instances, publishes complete coverage through one, then attempts stale shorter coverage through the other and compares the durable snapshots.

Repair: the CAS revision now advances on any changed observation publication as well as source edits and forgetting. An identical retry using the fresh current revision remains a no-op. The independent builder's earlier handoff is retained as historical evidence; its source-only-revision description is superseded by this narrowly documented repair.

Final commands and outcomes belong to the current aggregate receipt and independent review, not the earlier builder's counts. The model replay is re-run against the repaired store so a prior-source pass is not presented as current-source verification.
