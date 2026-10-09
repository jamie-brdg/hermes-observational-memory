"""Real cross-process lock oracles, using only owned synthetic databases."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from observational.store import MemoryStore


# A fresh interpreter, not a forked SQLite connection or same-process lock check.
# It only attempts a reservation and rolls back; it never changes database data.
_CHILD_PROBE = r"""
import json
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1], uri=True, timeout=0.2, isolation_level=None)
try:
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY:
            raise
        result = "busy"
    else:
        result = "acquired"
        connection.execute("ROLLBACK")
finally:
    connection.close()
print(json.dumps(result))
"""


@unittest.skipUnless(os.name == "posix", "requires POSIX SQLite file locking")
class SQLiteLockSafetyTests(unittest.TestCase):
    def setUp(self):
        scratch = Path.home() / ".hermes" / "cache" / "scratch"
        self.temp = tempfile.TemporaryDirectory(prefix="om-lock-test-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "memory.sqlite3"

    def open(self):
        store = MemoryStore(self.path, "profile", "session")
        self.addCleanup(store.close)
        return store

    def probe(self):
        child = subprocess.run(
            [sys.executable, "-I", "-c", _CHILD_PROBE,
             self.path.as_uri() + "?mode=rw"],
            capture_output=True, text=True, timeout=15, check=True,
            close_fds=True,
        )
        self.assertEqual(child.stderr, "")
        result = json.loads(child.stdout)
        self.assertIn(result, ("busy", "acquired"))
        return result

    def check_lock_survives(self, connection, action):
        connection.execute("BEGIN IMMEDIATE")
        try:
            before = self.probe()
            action()
            self.assertTrue(connection.in_transaction)
            after = self.probe()
        finally:
            connection.execute("ROLLBACK")
        released = self.probe()
        self.assertEqual(
            (before, after, released), ("busy", "busy", "acquired"),
            "child must stay blocked across the action, then acquire after rollback",
        )

    def test_closing_second_store_does_not_unlock_first(self):
        first = self.open()
        second = self.open()
        self.check_lock_survives(first._conn, second.close)

    def test_failed_constructor_does_not_unlock_existing_connection(self):
        store = self.open()

        def fail_constructor():
            # Fail after filesystem validation but before SQLite opens. Cleanup
            # must not close a raw database descriptor acquired by preflight.
            with mock.patch("observational.store.sqlite3.connect",
                            side_effect=RuntimeError("injected connect failure")):
                with self.assertRaisesRegex(RuntimeError, "injected connect failure"):
                    MemoryStore(self.path, "profile", "session")

        self.check_lock_survives(store._conn, fail_constructor)

    def test_constructor_sqlite_busy_cleanup_preserves_lock(self):
        store = self.open()
        real_connect = sqlite3.connect

        class ShortBusyConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                # Exercise the real constructor/SQLite failure path without
                # spending the production ten-second busy timeout per test.
                if sql == "PRAGMA busy_timeout=10000":
                    sql = "PRAGMA busy_timeout=1"
                return super().execute(sql, *args, **kwargs)

        def connect(*args, **kwargs):
            return real_connect(*args, factory=ShortBusyConnection, **kwargs)

        def busy_constructor():
            with mock.patch("observational.store.sqlite3.connect", side_effect=connect):
                with self.assertRaises(sqlite3.OperationalError) as raised:
                    MemoryStore(self.path, "profile", "session")
                self.assertEqual(raised.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)

        self.check_lock_survives(store._conn, busy_constructor)

    def test_closing_store_preserves_lock_owned_outside_memory_store(self):
        self.open().close()
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                     isolation_level=None)
        try:
            sibling = self.open()
            self.check_lock_survives(connection, sibling.close)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
