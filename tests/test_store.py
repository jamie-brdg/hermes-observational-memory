"""Synthetic, offline tests for the private session memory store."""

import copy
from contextlib import closing
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import unittest
from typing import Any, cast
from unittest import mock

from observational.contracts import canonical_json, digest_wire, observation_id
from observational.store import MemoryStore


STAMP = "2026-10-09T12:00:00Z"


def source(index, text=None, role="user"):
    text = text if text is not None else "Synthetic statement %d." % index
    wire = {"role": role, "content": text}
    if role == "tool":
        wire["tool_call_id"] = "call-synthetic"
    return {
        "id": "source-%d" % index,
        "ordinal": index,
        "role": role,
        "text": text,
        "wire": wire,
        "digest": digest_wire(wire),
        "message_uid": "uid-%d" % index,
        "occurred_at": None,
    }


def observation(item, quote=None):
    quote = item["text"] if quote is None else quote
    kind = "tool_output" if item["role"] == "tool" else "fact"
    ids = [item["id"]]
    return {
        "id": observation_id(ids, quote, kind),
        "source_ids": ids,
        "quote": quote,
        "kind": kind,
        "priority": 1,
        "attribution": {
            "user": "user_statement",
            "assistant": "assistant_statement",
            "tool": "tool_output",
        }[item["role"]],
        "observed_at": STAMP,
    }


def process_writer(path, start, results, index):
    """Real independent SQLite connections, including concurrent first open."""
    try:
        if not start.wait(15):
            raise RuntimeError("test start deadline")
        store = MemoryStore(Path(path), "profile", "session")
        rev = store.sync_sources([source(0, "Process %d" % index)])
        store.close()
        results.put(("ok", rev))
    except Exception as exc:
        results.put((type(exc).__name__, str(exc)))


def process_stale_worker(path, ready, resume, results):
    try:
        store = MemoryStore(Path(path), "profile", "session")
        snapshot = store.read()
        ready.set()
        if not resume.wait(15):
            raise RuntimeError("test resume deadline")
        item = snapshot["sources"][0]
        obs = observation(item)
        accepted = store.commit_observation(
            snapshot["revision"], [item["id"]], [obs], [obs["id"]]
        )
        store.sync_sources(snapshot["sources"])
        results.put((accepted, store.read()))
        store.close()
    except Exception as exc:
        results.put((type(exc).__name__, str(exc)))


def process_interrupted_writer(path, ready):
    store = MemoryStore(Path(path), "profile", "session")
    original_save = store._save
    def held_save(state):
        original_save(state)
        ready.set()
        threading.Event().wait(30)  # Parent kills us with a real transaction open.
    store._save = held_save
    try:
        store.sync_sources([source(0, "Uncommitted replacement")])
    finally:
        store.close()


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        # Explicit disposable scratch boundary; never read live Hermes state.
        self.temp = tempfile.TemporaryDirectory(
            prefix=".store-test-", dir=Path.home() / ".hermes" / "cache" / "scratch"
        )
        self.root = Path(self.temp.name)
        self.path = self.root / "private" / "session.sqlite3"
        self.stores = []

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.temp.cleanup()

    def open(self, path=None, profile="profile", session="session", **kwargs):
        store = MemoryStore(path or self.path, profile, session, **kwargs)
        self.stores.append(store)
        return store

    def seed(self, store, count=3):
        sources = [source(i) for i in range(count)]
        rev = store.sync_sources(sources)
        observations = [observation(item) for item in sources]
        self.assertTrue(store.commit_observation(
            rev, [item["id"] for item in sources], observations,
            [item["id"] for item in observations],
        ))
        return sources, observations

    def test_initial_state_and_idempotence_restart_and_defensive_copy(self):
        store = self.open()
        initial = store.read()
        self.assertEqual(set(initial), {
            "revision", "sources", "observations", "covered_ids",
            "active_ids", "generation", "disabled",
        })
        self.assertFalse(initial["disabled"])
        self.assertEqual(initial["sources"], [])
        self.assertEqual(store.sync_sources([]), initial["revision"])
        sources, observations = self.seed(store)
        before = store.read()
        self.assertEqual(store.sync_sources(copy.deepcopy(sources)), before["revision"])
        self.assertEqual(store.read(), before)
        self.assertTrue(store.commit_observation(
            before["revision"], before["covered_ids"], observations,
            before["active_ids"],
        ))
        self.assertEqual(store.read(), before)
        sources[0]["text"] = "caller mutation"
        observations[0]["quote"] = "caller mutation"
        returned = store.read()
        returned["sources"].clear()
        returned["observations"][0]["source_ids"].clear()
        self.assertEqual(store.read(), before)
        store.close()
        self.assertEqual(self.open().read(), before)

    def test_append_preserves_coverage_but_old_revision_cannot_publish(self):
        store = self.open()
        sources, observations = self.seed(store, 2)
        old = store.read()
        rev = store.sync_sources(sources + [source(2)])
        self.assertGreater(rev, old["revision"])
        state = store.read()
        for key in ("observations", "covered_ids", "active_ids"):
            self.assertEqual(state[key], old[key])
        self.assertFalse(store.commit_observation(
            old["revision"], old["covered_ids"], observations, old["active_ids"]
        ))
        self.assertEqual(store.read(), state)

    def test_revision_undo_removal_and_reorder_invalidate_exact_prefix(self):
        for change in ("edit", "remove", "undo", "reorder", "metadata"):
            with self.subTest(change=change):
                store = self.open(self.root / change / "memory.db")
                sources, observations = self.seed(store)
                if change == "edit":
                    changed = [sources[0], source(1, "Edited"), sources[2]]
                elif change == "remove":
                    changed = [sources[0], sources[2]]
                elif change == "undo":
                    changed = sources[:1]
                elif change == "reorder":
                    # Ordinals remain strictly increasing in the new snapshot.
                    changed = copy.deepcopy([sources[0], sources[2], sources[1]])
                    for index, item in enumerate(changed):
                        item["ordinal"] = index
                else:
                    changed = copy.deepcopy(sources)
                    changed[1]["message_uid"] = "replacement-uid"
                old_rev = store.read()["revision"]
                new_rev = store.sync_sources(changed)
                self.assertGreater(new_rev, old_rev)
                state = store.read()
                self.assertEqual(state["sources"], changed)
                self.assertEqual(state["covered_ids"], [sources[0]["id"]])
                self.assertEqual(state["observations"], observations[:1])
                self.assertEqual(state["active_ids"], [observations[0]["id"]])
                self.assertFalse(store.commit_observation(
                    old_rev, [s["id"] for s in sources], observations,
                    [o["id"] for o in observations],
                ))

    def test_exact_prefix_rejection_and_active_order(self):
        store = self.open()
        sources, observations = self.seed(store)
        before = store.read()
        for ids in ([sources[1]["id"]], [sources[0]["id"], sources[2]["id"]],
                    list(reversed(before["covered_ids"])),
                    before["covered_ids"] + ["not-current"],
                    [sources[0]["id"], sources[0]["id"]]):
            with self.subTest(ids=ids):
                self.assertFalse(store.commit_observation(
                    before["revision"], ids, observations, before["active_ids"]
                ))
                self.assertEqual(store.read(), before)
        reverse = list(reversed(before["active_ids"]))
        self.assertTrue(store.commit_observation(
            before["revision"], before["covered_ids"], observations, reverse
        ))
        self.assertEqual(store.read()["active_ids"], reverse)
        self.assertGreater(store.read()["generation"], before["generation"])

    def test_invalid_sources_are_atomic(self):
        store = self.open()
        self.seed(store)
        before = store.read()
        mutations = [
            lambda s: s.update(extra="forbidden"),
            lambda s: s.update(digest="0" * 64),
            lambda s: s.update(text="not matching wire"),
            lambda s: s.update(role="system"),
            lambda s: s.update(ordinal=True),
            lambda s: s.update(id=""),
            lambda s: s.update(occurred_at=123),
            lambda s: s["wire"].update(content=[{"type": "image_url", "image_url": "x"}]),
        ]
        for mutation in mutations:
            item = source(0)
            mutation(item)
            with self.subTest(item_keys=sorted(item)):
                with self.assertRaises(ValueError):
                    store.sync_sources([item])
                self.assertEqual(store.read(), before)
        with self.assertRaises(ValueError):
            store.sync_sources([source(0), source(0)])
        self.assertEqual(store.read(), before)

    def test_invalid_observations_and_active_ids_are_atomic(self):
        store = self.open()
        sources, observations = self.seed(store)
        before = store.read()
        mutations = [
            lambda o: o.update(verified=True),
            lambda o: o.update(quote="fabricated statement"),
            lambda o: o.update(source_ids=["foreign-source"]),
            lambda o: o.update(attribution="assistant_statement"),
            lambda o: o.update(priority=True),
            lambda o: o.update(priority=4),
            lambda o: o.update(observed_at="yesterday"),
        ]
        for mutation in mutations:
            bad = copy.deepcopy(observations)
            mutation(bad[0])
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    store.commit_observation(
                        before["revision"], before["covered_ids"], bad,
                        before["active_ids"],
                    )
                self.assertEqual(store.read(), before)
        for active in (["missing"], [observations[0]["id"]] * 2, "not-a-list"):
            with self.assertRaises(ValueError):
                store.commit_observation(
                    before["revision"], before["covered_ids"], observations, active
                )
            self.assertEqual(store.read(), before)
        with self.assertRaises(ValueError):
            store.commit_observation(before["revision"], before["covered_ids"], [], [])
        with self.assertRaises(ValueError):
            store.commit_observation(
                before["revision"], [sources[0]["id"]], observations, []
            )
        self.assertEqual(store.read(), before)

    def test_recall_pagination_scope_unicode_and_missing(self):
        store = self.open()
        text = "Synthetic 🍎 text\nSecond line"
        item = source(0, text)
        store.sync_sources([item])
        chunks = []
        offset = 0
        while True:
            page = store.recall(item["id"], offset, 3)
            self.assertEqual(set(page), {
                "source_id", "role", "text", "offset", "next_offset", "has_more"
            })
            self.assertEqual(page["source_id"], item["id"])
            self.assertEqual(page["role"], "user")
            self.assertEqual(page["offset"], offset)
            self.assertLessEqual(len(page["text"]), 3)
            chunks.append(page["text"])
            if not page["has_more"]:
                self.assertIsNone(page["next_offset"])
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual("".join(chunks), text)
        self.assertEqual(store.recall(item["id"], len(text) + 3)["text"], "")
        for missing in ("foreign-source", "../../other-session"):
            with self.assertRaises(KeyError):
                store.recall(missing)
        store.sync_sources([])
        with self.assertRaises(KeyError):
            store.recall(item["id"])

    def test_recall_and_search_bounded_inputs(self):
        store = self.open()
        store.sync_sources([source(0, "X" * 20000)])
        page = store.recall("source-0", limit=1000000)
        self.assertLessEqual(len(page["text"]), 4000)
        self.assertTrue(page["has_more"])
        for kwargs in ({"offset": -1}, {"offset": True}, {"limit": 0},
                       {"limit": -1}, {"limit": True}, {"limit": "3"}):
            with self.assertRaises(ValueError):
                store.recall("source-0", **kwargs)
        for query in ("", "   ", None, "x" * 1025):
            with self.assertRaises(ValueError):
                store.search(query)
        for limit in (0, -1, True, "3"):
            with self.assertRaises(ValueError):
                store.search("x", limit=limit)

    def test_search_literal_scoped_bounded_and_deterministic(self):
        store = self.open()
        sources = [source(i, "prefix " + "z" * 900 + " NEEDLE %_ " + "z" * 900)
                   for i in range(30)]
        store.sync_sources(sources)
        results = store.search("needle", limit=2)
        self.assertEqual(results, store.search("needle", limit=2))
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertIn(result["source_id"], [s["id"] for s in sources])
            self.assertIn("NEEDLE", result["text"])
            self.assertLessEqual(len(result["text"]), 400)
        self.assertLessEqual(len(store.search("needle", limit=100000)), 20)
        self.assertEqual(store.search("' OR 1=1 --"), [])
        self.assertEqual(len(store.search("%_", limit=2)), 2)
        store.sync_sources([])
        self.assertEqual(store.search("needle"), [])

    def test_namespace_mismatch_denies_without_altering_owner(self):
        store = self.open()
        self.seed(store)
        before = store.read()
        for profile, session in (("other", "session"), ("profile", "other")):
            with self.assertRaises(ValueError):
                self.open(profile=profile, session=session)
            self.assertEqual(store.read(), before)
        unrelated = self.root / "unrelated.sqlite3"
        conn = sqlite3.connect(str(unrelated))
        conn.execute("CREATE TABLE unrelated (value TEXT)")
        conn.commit()
        conn.close()
        unrelated.chmod(0o600)
        with self.assertRaises(ValueError):
            self.open(unrelated)
        conn = sqlite3.connect(str(unrelated))
        self.assertEqual(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall(), [("unrelated",)])
        conn.close()

    def test_forget_tombstone_shared_connections_and_restart(self):
        store = self.open()
        marker = "PRIVATE_SYNTHETIC_SENTINEL_7cb083be"
        item = source(0, marker)
        rev = store.sync_sources([item])
        obs = observation(item)
        self.assertTrue(store.commit_observation(rev, [item["id"]], [obs], [obs["id"]]))
        other = self.open()
        store.forget()
        tombstone = store.read()
        self.assertTrue(tombstone["disabled"])
        self.assertGreater(tombstone["revision"], rev)
        for key in ("sources", "observations", "covered_ids", "active_ids"):
            self.assertEqual(tombstone[key], [])
        self.assertFalse(other.commit_observation(rev, [item["id"]], [obs], [obs["id"]]))
        self.assertEqual(other.sync_sources([item]), tombstone["revision"])
        self.assertEqual(other.read(), tombstone)
        store.forget()
        self.assertEqual(store.read(), tombstone)
        self.assertEqual(store.search(marker), [])
        with self.assertRaises(KeyError):
            store.recall(item["id"])
        store.close()
        other.close()
        self.assertNotIn(marker.encode(), self.path.read_bytes())
        reopened = self.open()
        self.assertEqual(reopened.read(), tombstone)
        reopened.sync_sources([item])
        self.assertEqual(reopened.read(), tombstone)
        self.assertFalse(Path(str(self.path) + "-journal").exists())
        self.assertFalse(Path(str(self.path) + "-wal").exists())

    def test_private_modes_and_symlink_hardlink_refusal(self):
        store = self.open()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        link = self.root / "linked.sqlite3"
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            self.open(link)
        parent_link = self.root / "parent-link"
        parent_link.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.open(parent_link / "new.db")
        self.assertFalse((self.path.parent / "new.db").exists())
        hard = self.root / "hard.sqlite3"
        os.link(self.path, hard)
        with self.assertRaises(ValueError):
            self.open(hard)
        hard.unlink()
        bad_parent = self.root / "public"
        bad_parent.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            self.open(bad_parent / "memory.db")
        self.assertFalse((bad_parent / "memory.db").exists())
        store.close()
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.open()
        self.path.chmod(0o600)

    def test_sidecar_symlink_and_path_replacement_fail_closed(self):
        store = self.open()
        self.seed(store)
        outside = self.root / "untouched"
        outside.write_text("sentinel")
        journal = Path(str(self.path) + "-journal")
        journal.symlink_to(outside)
        with self.assertRaises(ValueError):
            store.sync_sources([source(0, "different")])
        with self.assertRaises(ValueError):
            self.open()
        self.assertEqual(outside.read_text(), "sentinel")
        journal.unlink()
        original = self.path.with_suffix(".saved")
        self.path.rename(original)
        self.path.symlink_to(original)
        with self.assertRaises(ValueError):
            store.read()
        self.path.unlink()
        original.rename(self.path)

    def test_size_limit_atomic_rollback_and_reopen(self):
        store = self.open(max_bytes=65536)
        store.sync_sources([source(0, "small")])
        before = store.read()
        with self.assertRaises(ValueError):
            store.sync_sources([source(0, "oversized-" * 20000)])
        self.assertEqual(store.read(), before)
        self.assertLessEqual(self.path.stat().st_size, 65536)
        store.close()
        self.assertEqual(self.open(max_bytes=65536).read(), before)
        with self.assertRaises(ValueError):
            self.open(self.root / "tiny" / "memory.db", max_bytes=1)
        for invalid in (0, -1, True, "65536"):
            with self.assertRaises(ValueError):
                self.open(self.root / "invalid" / "memory.db", max_bytes=invalid)

    def test_existing_database_uses_no_raw_file_descriptors(self):
        self.open().close()
        real_open, real_close = os.open, os.close

        def directory_open(path, flags, *args, **kwargs):
            self.assertTrue(flags & os.O_DIRECTORY, "raw database open is unsafe")
            return real_open(path, flags, *args, **kwargs)

        def directory_close(fd):
            self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode),
                            "only SQLite may close a published database inode")
            return real_close(fd)

        with mock.patch("observational.store.os.open", side_effect=directory_open), \
                mock.patch("observational.store.os.close", side_effect=directory_close):
            store = self.open()
            store.sync_sources([source(0)])
            self.assertEqual(len(store.read()["sources"]), 1)
            with self.assertRaisesRegex(ValueError, "namespace"):
                self.open(session="other")
            store.close()

    def test_private_creation_closes_raw_descriptor_before_publication(self):
        real_open, real_close, real_link = os.open, os.close, os.link
        raw_fds, published = set(), []

        def track_open(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if not flags & os.O_DIRECTORY:
                self.assertTrue(flags & os.O_EXCL)
                raw_fds.add(fd)
            return fd

        def track_close(fd):
            result = real_close(fd)
            raw_fds.discard(fd)
            return result

        def publish(src, dst, **kwargs):
            self.assertEqual(raw_fds, set(), "raw descriptor survives publication")
            info = os.stat(src, dir_fd=kwargs["src_dir_fd"], follow_symlinks=False)
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_nlink, 1)
            self.assertFalse(self.path.exists())
            published.append((info.st_dev, info.st_ino))
            return real_link(src, dst, **kwargs)

        with mock.patch("observational.store.os.open", side_effect=track_open), \
                mock.patch("observational.store.os.close", side_effect=track_close), \
                mock.patch("observational.store.os.link", side_effect=publish):
            store = self.open()
            store.close()
        info = self.path.stat()
        self.assertEqual(published, [(info.st_dev, info.st_ino)])
        self.assertEqual(info.st_nlink, 1)
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(list(self.path.parent.glob(".memory-create-*")), [])

    def test_regular_file_inode_replacement_fails_closed(self):
        store = self.open()
        original = self.path.with_suffix(".saved")
        self.path.rename(original)
        replacement = self.open()
        try:
            with self.assertRaisesRegex(ValueError, "memory file was replaced"):
                store.read()
            with self.assertRaisesRegex(ValueError, "memory file was replaced"):
                store.sync_sources([source(0)])
            self.assertEqual(replacement.read()["sources"], [])
        finally:
            replacement.close()
            self.path.unlink()
            original.rename(self.path)
        self.assertEqual(store.read()["sources"], [])

    def test_creation_rejects_replaced_staging_inode(self):
        real_link = os.link

        def replace_then_link(src, dst, **kwargs):
            directory_fd = kwargs["src_dir_fd"]
            os.rename(src, src + ".saved", src_dir_fd=directory_fd,
                      dst_dir_fd=directory_fd)
            fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         0o600, dir_fd=directory_fd)
            os.close(fd)  # This replacement is also unpublished, not SQLite-open.
            return real_link(src, dst, **kwargs)

        with mock.patch("observational.store.os.link", side_effect=replace_then_link):
            with self.assertRaisesRegex(ValueError, "memory file was replaced"):
                self.open()
        self.assertEqual(self.path.stat().st_size, 0)

    def test_concurrent_first_open_waits_for_complete_publication(self):
        real_link, real_flock = os.link, fcntl.flock
        published, attempting, resume = threading.Event(), threading.Event(), threading.Event()
        errors, states = [], []

        def held_link(*args, **kwargs):
            result = real_link(*args, **kwargs)
            published.set()  # Deliberately expose the temporary two-link window.
            if not resume.wait(10):
                raise RuntimeError("publication test deadline")
            return result

        def observe_flock(fd, operation):
            if operation == fcntl.LOCK_EX and published.is_set():
                attempting.set()
            return real_flock(fd, operation)

        def open_worker():
            try:
                store = MemoryStore(self.path, "profile", "session")
                try:
                    states.append(store.read())
                finally:
                    store.close()
            except BaseException as exc:
                errors.append(exc)

        first, second = threading.Thread(target=open_worker), threading.Thread(target=open_worker)
        with mock.patch("observational.store.os.link", side_effect=held_link), \
                mock.patch("observational.store.fcntl.flock", side_effect=observe_flock):
            try:
                first.start()
                self.assertTrue(published.wait(10))
                self.assertEqual(self.path.stat().st_nlink, 2)
                second.start()
                self.assertTrue(attempting.wait(10))
            finally:
                resume.set()
                for thread in (first, second):
                    if thread.ident is not None:
                        thread.join(20)
                        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(states), 2)
        self.assertEqual(states[0], states[1])
        self.assertEqual(self.path.stat().st_nlink, 1)
        self.assertEqual(list(self.path.parent.glob(".memory-create-*")), [])

    def test_directory_inode_and_private_permissions_rechecked(self):
        store = self.open()
        parent = self.path.parent
        original = parent.with_name("saved-private")
        parent.rename(original)
        parent.mkdir(mode=0o700)
        try:
            with self.assertRaisesRegex(ValueError, "memory directory was replaced"):
                store.read()
        finally:
            parent.rmdir()
            original.rename(parent)
        parent.chmod(0o755)
        try:
            with self.assertRaisesRegex(ValueError, "owner-only"):
                store.read()
            with self.assertRaisesRegex(ValueError, "owner-only"):
                self.open()
        finally:
            parent.chmod(0o700)
        self.assertEqual(store.read()["sources"], [])

    def test_shared_instance_thread_safety_and_closed_lifecycle(self):
        store = self.open()
        start = threading.Barrier(9)
        errors = []
        def work(index):
            try:
                start.wait(timeout=10)
                for j in range(5):
                    item = source(0, "thread %d iteration %d" % (index, j))
                    rev = store.sync_sources([item])
                    obs = observation(item)
                    store.commit_observation(rev, [item["id"]], [obs], [obs["id"]])
                    self.assertEqual(len(store.read()["sources"]), 1)
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        start.wait(timeout=10)
        for thread in threads:
            thread.join(20)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        state = store.read()
        store.close()
        store.close()
        for operation in (store.read, store.forget,
                          lambda: store.sync_sources([]),
                          lambda: store.search("thread"),
                          lambda: store.recall("source-0"),
                          lambda: store.commit_observation(state["revision"], [], [], [])):
            with self.assertRaises(RuntimeError):
                operation()
        self.assertEqual(self.open().read(), state)

    def test_real_process_concurrent_initialization_and_writes(self):
        ctx = multiprocessing.get_context("spawn")
        event = ctx.Event()
        results = ctx.Queue()
        children = [ctx.Process(target=process_writer,
                                args=(str(self.path), event, results, i))
                    for i in range(2)]
        try:
            for child in children:
                child.start()
            event.set()
            receipts = [results.get(timeout=25) for _ in children]
            for child in children:
                child.join(10)
                self.assertEqual(child.exitcode, 0)
            self.assertEqual(sorted(receipts), [("ok", 1), ("ok", 2)])
            state = self.open().read()
            self.assertEqual(state["revision"], 2)
            self.assertEqual(len(state["sources"]), 1)
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                child.join(10)
            results.close()
            results.join_thread()

    def test_real_sqlite_page_limit_rolls_back_and_connection_remains_usable(self):
        store = self.open(max_bytes=8192)
        store.sync_sources([source(0, "initial")])
        before = store.read()
        oversized = [source(0, "a" * 2500)]
        payload = {"sources": oversized, "observations": [],
                   "covered_ids": [], "active_ids": []}
        # The JSON preflight passes, but the physical SQLite page cap must fail.
        self.assertLess(len(canonical_json(payload).encode("utf-8")), 8192)
        with self.assertRaisesRegex(ValueError, "size limit"):
            store.sync_sources(oversized)
        self.assertEqual(store.read(), before)
        self.assertLessEqual(self.path.stat().st_size, 8192)
        store.sync_sources([source(0, "after rollback")])
        self.assertEqual(store.recall("source-0")["text"], "after rollback")

    def test_observation_size_limit_is_atomic(self):
        store = self.open(max_bytes=32768)
        item = source(0, "x" * 3000)
        revision = store.sync_sources([item])
        before = store.read()
        observations = [observation(item, "x" * length) for length in range(1, 251)]
        with self.assertRaisesRegex(ValueError, "size limit"):
            store.commit_observation(revision, [item["id"]], observations, [])
        self.assertEqual(store.read(), before)

    def test_removed_source_payload_is_not_retained_on_disk(self):
        store = self.open()
        marker = "REMOVED_PRIVATE_SYNTHETIC_94db8ef5"
        sources = [source(0, "retained"), source(1, marker)]
        revision = store.sync_sources(sources)
        observations = [observation(s) for s in sources]
        self.assertTrue(store.commit_observation(
            revision, [s["id"] for s in sources], observations,
            [o["id"] for o in observations],
        ))
        store.sync_sources(sources[:1])
        self.assertEqual(store.read()["observations"], observations[:1])
        self.assertEqual(store.search(marker), [])
        store.close()
        self.assertNotIn(marker.encode(), self.path.read_bytes())
        self.assertEqual(self.open().read()["sources"], sources[:1])

    def test_multisource_observation_is_removed_if_one_reference_changes(self):
        store = self.open()
        sources = [source(0, "shared quote A"), source(1, "shared quote B")]
        revision = store.sync_sources(sources)
        obs = observation(sources[0], "shared quote")
        obs["source_ids"] = [s["id"] for s in sources]
        obs["id"] = observation_id(obs["source_ids"], obs["quote"], obs["kind"])
        self.assertTrue(store.commit_observation(
            revision, obs["source_ids"], [obs], [obs["id"]]
        ))
        store.sync_sources([sources[0], source(1, "replacement")])
        state = store.read()
        self.assertEqual(state["covered_ids"], [])
        self.assertEqual(state["observations"], [])
        self.assertEqual(state["active_ids"], [])

    def test_unicode_casefold_search_preserves_original_offsets(self):
        store = self.open()
        text = "ß" * 500 + "The Straße is synthetic" + " suffix" * 100
        store.sync_sources([source(0, text)])
        result = store.search("STRASSE")[0]
        self.assertIn("Straße", result["text"])
        self.assertEqual(result["text"], text[result["offset"]:result["offset"] + 400])

    def test_argument_types_and_no_namespace_rewriting(self):
        store = self.open()
        self.seed(store, 1)
        before = store.read()
        for revision in (True, -1, "1", None):
            with self.assertRaises(ValueError):
                store.commit_observation(cast(Any, revision), [], [], [])
            self.assertEqual(store.read(), before)
        for coverage in ("source-0", [None], [True], [""]):
            with self.assertRaises(ValueError):
                store.commit_observation(before["revision"], cast(Any, coverage), [], [])
            self.assertEqual(store.read(), before)
        store.close()
        exact_bytes = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "namespace"):
            self.open(profile="profile ")
        self.assertEqual(self.path.read_bytes(), exact_bytes)

    def test_invalid_persisted_payload_fails_closed_without_content_in_errors(self):
        store = self.open()
        self.seed(store, 1)
        store.close()
        with closing(sqlite3.connect(str(self.path))) as connection, connection:
            raw = connection.execute("SELECT payload FROM memory_state").fetchone()[0]
            payload = json.loads(raw)
            payload["sources"][0]["text"] = "SYNTHETIC_PRIVATE_CORRUPTION"
            connection.execute("UPDATE memory_state SET payload=?", (json.dumps(payload),))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "invalid stored memory state") as raised:
            self.open()
        self.assertNotIn("SYNTHETIC_PRIVATE_CORRUPTION", str(raised.exception))
        self.assertEqual(self.path.read_bytes(), before)

    def test_crash_before_commit_recovers_prior_snapshot(self):
        store = self.open()
        self.seed(store, 1)
        before = store.read()
        store.close()
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        child = ctx.Process(target=process_interrupted_writer, args=(str(self.path), ready))
        try:
            child.start()
            self.assertTrue(ready.wait(20))
            journal = Path(str(self.path) + "-journal")
            self.assertTrue(journal.is_file())
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
            child.kill()
            child.join(10)
            self.assertIsNotNone(child.exitcode)
            self.assertNotEqual(child.exitcode, 0)
            reopened = self.open()
            self.assertEqual(reopened.read(), before)
            reopened.sync_sources([source(0, "After recovered crash")])
            self.assertEqual(reopened.recall("source-0")["text"], "After recovered crash")
            self.assertFalse(journal.exists())
        finally:
            if child.is_alive():
                child.kill()
            child.join(10)

    def test_real_process_stale_worker_cannot_resurrect_forgetting(self):
        store = self.open()
        self.seed(store, 1)
        ctx = multiprocessing.get_context("spawn")
        ready, resume, results = ctx.Event(), ctx.Event(), ctx.Queue()
        child = ctx.Process(target=process_stale_worker,
                            args=(str(self.path), ready, resume, results))
        try:
            child.start()
            self.assertTrue(ready.wait(20))
            store.forget()
            expected = store.read()
            resume.set()
            accepted, actual = results.get(timeout=20)
            child.join(10)
            self.assertEqual(child.exitcode, 0)
            self.assertIs(accepted, False)
            self.assertEqual(actual, expected)
            self.assertEqual(store.read(), expected)
        finally:
            resume.set()
            if child.is_alive():
                child.terminate()
            child.join(10)
            results.close()
            results.join_thread()


if __name__ == "__main__":
    unittest.main()
