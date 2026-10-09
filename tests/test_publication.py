"""Publication races must not roll back newer completed observation coverage."""
import tempfile
import unittest
from pathlib import Path

from observational.contracts import digest_wire, observation_id
from observational.store import MemoryStore


def row(i):
    wire = {"role": "user" if i % 2 == 0 else "assistant", "content": "Synthetic statement " + str(i)}
    return {"id": "source-" + str(i), "ordinal": i, "role": wire["role"], "text": wire["content"], "wire": wire, "digest": digest_wire(wire), "message_uid": "uid-" + str(i), "occurred_at": None}


def obs(source):
    ids = [source["id"]]
    return {"id": observation_id(ids, source["text"], "other"), "source_ids": ids, "quote": source["text"], "kind": "other", "priority": 1, "attribution": "user_statement" if source["role"] == "user" else "assistant_statement", "observed_at": "2026-10-09T08:00:00Z"}


class PublicationRaceTests(unittest.TestCase):
    def test_stale_observer_cannot_replace_a_newer_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "private" / "session.sqlite3"
            first = MemoryStore(path, "profile", "session")
            second = MemoryStore(path, "profile", "session")
            try:
                sources = [row(i) for i in range(4)]
                revision = first.sync_sources(sources)
                observations = [obs(s) for s in sources]
                self.assertEqual(second.read()["revision"], revision)
                self.assertTrue(first.commit_observation(revision, [s["id"] for s in sources], observations, [o["id"] for o in observations]))
                accepted = first.read()
                self.assertFalse(second.commit_observation(revision, [s["id"] for s in sources[:2]], observations[:2], [o["id"] for o in observations[:2]]))
                self.assertEqual(second.read(), accepted)
                # Identical retry against the fresh current revision is a no-op.
                self.assertTrue(second.commit_observation(accepted["revision"], accepted["covered_ids"], observations, accepted["active_ids"]))
                self.assertEqual(second.read(), accepted)
            finally:
                second.close()
                first.close()
