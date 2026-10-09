"""Regression closure for the preserved independent review OM-R1 and OM-R2.

Use real host hooks, engine, observer, backend and SQLite. Provider boundaries
are synthetic and sockets forbidden; no credentials or live history are used.
"""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.conversation_loop import _apply_context_engine_selection, _notify_context_engine_turn_complete
from observational.engine import EngineConfig, ObservationalEngine, normalize_sources
from observational.observer import ExtractiveObserver, ModelObserver
from test_engine import conversation


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.engines = []
        self.releases = []
        self.network = patch("socket.socket.connect", side_effect=AssertionError("Synthetic regression prohibits network"))
        self.network_ex = patch("socket.socket.connect_ex", side_effect=AssertionError("Synthetic regression prohibits network"))
        self.network.start()
        self.network_ex.start()

    def tearDown(self):
        for release in self.releases:
            release.set()
        for engine in self.engines:
            engine.on_session_end(engine.session_id, [])
            self.assertTrue(engine.wait_until_idle(10))
        self.network_ex.stop()
        self.network.stop()
        self.temp.cleanup()

    def barrier(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        return entered, release

    def engine(self, session, *, model_mode=False, observer=None):
        route = {"observer_mode": "model", "allow_model_calls": True, "provider": "openai-codex", "model": "gpt-6-astra"} if model_mode else {}
        config = EngineConfig(observe_min_chars=1, max_batch_chars=200000, max_source_chars=40000, observation_budget_chars=8000, **route)
        engine = ObservationalEngine(config=config, observer=observer)
        engine.on_session_start(session, hermes_home=self.home, model="gpt-6-astra" if model_mode else "synthetic", provider="openai-codex" if model_mode else "synthetic")
        self.engines.append(engine)
        return engine

    @staticmethod
    def client(create):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)

    @staticmethod
    def response(kwargs):
        source = json.loads(kwargs["messages"][1]["content"])["sources"][0]
        text = json.dumps({"observations": [{"source_id": source["source_id"], "quote": source["text"][:50], "kind": "other", "priority": 1}]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))], usage=None)

    def test_queued_work_is_cancelled_on_actor_route_switch(self):
        entered, release = self.barrier()
        engine = self.engine("route-queue", model_mode=True)
        calls = []
        def create(**kwargs):
            calls.append((engine._route_mismatch, kwargs["model"]))
            if len(calls) == 1:
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Fixture release timed out")
            return self.response(kwargs)
        with patch("agent.auxiliary_client.resolve_provider_client", return_value=(self.client(create), "gpt-6-astra")):
            engine.on_turn_complete(conversation(size=160))
            self.assertTrue(entered.wait(5))
            updated = conversation(turns=7, size=160)
            engine.on_turn_complete(updated)
            self.assertTrue(engine._pending)
            engine.update_model("synthetic-local-only", 200000, provider="custom")
            release.set()
            self.assertTrue(engine.wait_until_idle(10))
            self.assertEqual(calls, [(False, "gpt-6-astra")])
            self.assertEqual(engine.store.read()["observations"], [])
            self.assertEqual(engine.get_status()["last_error"], "pinned_model_does_not_match_actor")
            # Explicitly returning to the pin plus a new completed snapshot works.
            engine.update_model("gpt-6-astra", 200000, provider="openai-codex")
            engine.on_turn_complete(updated)
            self.assertTrue(engine.wait_until_idle(10))
            self.assertTrue(engine.store.read()["observations"])
            self.assertEqual(calls, [(False, "gpt-6-astra"), (False, "gpt-6-astra")])

    def test_route_switch_during_provider_resolution_denies_create(self):
        entered, release = self.barrier()
        engine = self.engine("route-resolve", model_mode=True)
        create = MagicMock(side_effect=lambda **kwargs: self.response(kwargs))
        def resolve(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Fixture release timed out")
            return self.client(create), "gpt-6-astra"
        with patch("agent.auxiliary_client.resolve_provider_client", side_effect=resolve):
            engine.on_turn_complete(conversation(size=160))
            self.assertTrue(entered.wait(5))
            engine.update_model("synthetic-local-only", 200000, provider="custom")
            release.set()
            self.assertTrue(engine.wait_until_idle(10))
            self.assertEqual(create.call_count, 0)
            self.assertEqual(engine.store.read()["observations"], [])
            self.assertEqual(engine.get_status()["last_error"], "pinned_model_does_not_match_actor")

    def test_route_roundtrip_before_observer_completion_denies_old_epoch(self):
        entered, release = self.barrier()
        engine = self.engine("route-roundtrip", model_mode=True)
        original_observe = ModelObserver.observe
        def held(observer, sources, *, observed_at):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Fixture release timed out")
            return original_observe(observer, sources, observed_at=observed_at)
        create = MagicMock(side_effect=lambda **kwargs: self.response(kwargs))
        with patch.object(ModelObserver, "observe", held), patch("agent.auxiliary_client.resolve_provider_client", return_value=(self.client(create), "gpt-6-astra")) as resolve:
            engine.on_turn_complete(conversation(size=160))
            self.assertTrue(entered.wait(5))
            engine.update_model("synthetic-local-only", 200000, provider="custom")
            engine.update_model("gpt-6-astra", 200000, provider="openai-codex")
            release.set()
            self.assertTrue(engine.wait_until_idle(10))
            self.assertEqual(resolve.call_count, 0)
            self.assertEqual(create.call_count, 0)
            self.assertEqual(engine.store.read()["observations"], [])

    def invalid_replacement(self, *, published=False, failed_worker=False, kind="structured"):
        entered, release = self.barrier()
        class Held:
            def observe(self, sources, *, observed_at):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Fixture release timed out")
                if failed_worker:
                    raise RuntimeError("Synthetic old failure")
                return ExtractiveObserver().observe(sources, observed_at=observed_at)
        session = f"replace-{published}-{failed_worker}-{kind}"
        engine = self.engine(session, observer=None if published else Held())
        agent = SimpleNamespace(context_compressor=engine, session_id=session, model="synthetic", model_max_context=200000)
        logger = MagicMock()
        history = conversation(size=160)
        changed = copy.deepcopy(history[2:])
        if kind == "structured":
            changed += [{"role": "user", "content": [{"type": "text", "text": "Unsupported new attachment turn."}]}, {"role": "assistant", "content": "Received."}]
        elif kind == "unpaired":
            changed += [{"role": "user", "content": "Check only."}, {"role": "assistant", "content": None, "tool_calls": [{"id": "missing-result", "type": "function", "function": {"name": "synthetic", "arguments": "{}"}}]}]
        elif kind == "sensitive":
            changed += [{"role": "user", "content": "https://synthetic-user:synthetic-password@example.invalid/"}, {"role": "assistant", "content": "Do not store that."}]
        elif kind == "oversize":
            changed += [{"role": "user", "content": "X" * 50000}, {"role": "assistant", "content": "Unsupported size."}]
        elif kind == "empty":
            changed = []
        else:
            raise AssertionError("Unknown fixture")
        original_changed = copy.deepcopy(changed)
        _notify_context_engine_turn_complete(agent, history, logger=logger, interrupted=False, failed=False)
        if published:
            self.assertTrue(engine.wait_until_idle(10))
            self.assertTrue(engine.store.read()["observations"])
        else:
            self.assertTrue(entered.wait(5))
        old_id = normalize_sources(history)[0]["id"]
        _notify_context_engine_turn_complete(agent, changed, logger=logger, interrupted=False, failed=False)
        self.assertEqual(engine.get_status()["last_error"], "unsupported_or_sensitive_input")
        release.set()
        self.assertTrue(engine.wait_until_idle(10))
        state = engine.store.read()
        self.assertEqual(state["sources"], [])
        self.assertEqual(state["observations"], [])
        self.assertFalse(state["disabled"], "Rejection must not become permanent forgetting")
        self.assertEqual(engine.get_status()["last_error"], "unsupported_or_sensitive_input")
        self.assertIn("error", json.loads(engine.handle_tool_call("om_recall", {"source_id": old_id})))
        self.assertEqual(json.loads(engine.handle_tool_call("om_search", {"query": "Turn 0"})).get("results", []), [])
        request = changed + [{"role": "user", "content": "Use current history only."}]
        self.assertEqual(_apply_context_engine_selection(agent, request, changed, request[-1], logger=logger), request)
        self.assertEqual(changed, original_changed)
        engine.on_session_end(session, [])
        reopened = self.engine(session)
        self.assertEqual(reopened.store.read()["sources"], [])
        self.assertIn("error", json.loads(reopened.handle_tool_call("om_recall", {"source_id": old_id})))
        # New supported history can recover, without reviving the removed source.
        supported = copy.deepcopy(history[2:])
        _notify_context_engine_turn_complete(SimpleNamespace(context_compressor=reopened, session_id=session), supported, logger=logger, interrupted=False, failed=False)
        self.assertTrue(reopened.wait_until_idle(10))
        self.assertTrue(reopened.store.read()["observations"])
        self.assertNotIn(old_id, [s["id"] for s in reopened.store.read()["sources"]])
        self.assertIsNone(reopened.get_status()["last_error"])

    def test_rejected_replacement_invalidates_inflight_and_restart_recall(self):
        self.invalid_replacement()

    def test_rejected_replacement_removes_published_sources_without_tombstone(self):
        self.invalid_replacement(published=True)

    def test_old_worker_failure_cannot_replace_ingestion_error(self):
        self.invalid_replacement(failed_worker=True)

    def test_other_rejected_snapshot_shapes_reconcile_obsolete_sources(self):
        for kind in ("unpaired", "sensitive", "oversize", "empty"):
            with self.subTest(kind=kind):
                self.invalid_replacement(published=True, kind=kind)
