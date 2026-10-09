"""Synthetic behavior tests, executed with the real Hermes ABC imported."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from observational.engine import ObservationalEngine, EngineConfig, normalize_sources


def conversation(turns=6, size=900):
    result = []
    for i in range(turns):
        result.extend([
            {"role": "user", "content": f"Turn {i}. I intend to send the draft, but it is not sent. " + ("background detail " * size), "message_uid": f"u{i}"},
            {"role": "assistant", "content": f"Turn {i}: the draft remains a plan, not a verified outcome.", "message_uid": f"a{i}"},
        ])
    return result


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            engine.on_session_end(engine.session_id, [])
        self.tmp.cleanup()

    def engine(self, session="synthetic", observer=None, **options):
        config = EngineConfig(observe_min_chars=1, retain_turns=2, max_batch_chars=200000, observation_budget_chars=8000, **options)
        engine = ObservationalEngine(config=config, observer=observer)
        engine.on_session_start(session, hermes_home=str(self.home), model="synthetic-model", context_length=200000)
        self.engines.append(engine)
        return engine

    def ready(self, engine):
        self.assertTrue(engine.wait_until_idle(10), engine.get_status())
        self.assertIsNone(engine.get_status()["last_error"], engine.get_status())

    def test_native_abc_and_request_only_compaction(self):
        from agent.context_engine import ContextEngine
        engine = self.engine()
        self.assertIsInstance(engine, ContextEngine)
        messages = conversation()
        self.assertFalse(engine.should_compress(999999))
        self.assertIs(engine.compress(messages, force=True), messages)
        self.assertEqual(engine.name, "observational")

    def test_observe_project_original_recall_and_restart(self):
        engine = self.engine()
        history = conversation(size=180)
        original = copy.deepcopy(history)
        engine.on_turn_complete(history)
        self.ready(engine)
        request = [{"role": "system", "content": "The authoritative instructions."}] + history + [{"role": "user", "content": "What is still unsent?"}]
        out = engine.select_context(request)
        self.assertIsNotNone(out, engine.get_status())
        self.assertLess(len(json.dumps(out)), len(json.dumps(request)))
        self.assertEqual(out[0], request[0])
        self.assertEqual(out[-1], request[-1])
        self.assertEqual(history, original)
        self.assertEqual(out, engine.select_context(request))
        state = engine.store.read()
        self.assertGreater(len(state["observations"]), 0)
        source = state["sources"][0]
        recalled = json.loads(engine.handle_tool_call("om_recall", {"source_id": source["id"], "offset": 0, "limit": 4000}))
        self.assertEqual(recalled["text"], source["text"][:4000])
        self.assertTrue(recalled["untrusted_data"])
        engine.on_session_end("synthetic", [])
        reopened = self.engine()
        self.assertEqual(out, reopened.select_context(request))

    def test_unobserved_append_does_not_rewrite_memory_prefix(self):
        engine = self.engine()
        history = conversation(size=130)
        engine.on_turn_complete(history)
        self.ready(engine)
        before = engine._render(engine.store.read())
        expanded = history + [{"role": "user", "content": "A fresh short turn."}, {"role": "assistant", "content": "Acknowledged."}]
        engine.store.sync_sources(normalize_sources(expanded))
        self.assertEqual(engine._render(engine.store.read()), before)

    def test_rendered_observations_fit_the_declared_log_budget(self):
        engine = self.engine()
        engine.on_turn_complete(conversation(size=150))
        self.ready(engine)
        state = engine.store.read()
        rendered = engine._render(state)
        from observational.contracts import render_observation
        lookup = {o["id"]: o for o in state["observations"]}
        records = "".join(render_observation(lookup[i]) for i in state["active_ids"])
        self.assertLessEqual(len(records), engine.config.observation_budget_chars)
        self.assertTrue(rendered.endswith(records))
        self.assertLess(len(rendered) - len(records), 1200)

    def test_scope_tool_arguments_rejected_and_other_session_empty(self):
        engine = self.engine()
        engine.on_turn_complete(conversation(size=120))
        self.ready(engine)
        sid = engine.store.read()["sources"][0]["id"]
        for name, args in [("om_search", {"query": "draft", "session_id": "foreign"}), ("om_recall", {"source_id": sid, "profile": "foreign"}), ("om_status", {"extra": True})]:
            self.assertIn("error", json.loads(engine.handle_tool_call(name, args)))
        other = self.engine(session="foreign")
        self.assertIn("error", json.loads(other.handle_tool_call("om_recall", {"source_id": sid})))
        self.assertEqual(other.store.read()["sources"], [])

    def test_mismatched_or_edited_source_never_projects_old_notes(self):
        engine = self.engine()
        history = conversation(size=120)
        engine.on_turn_complete(history)
        self.ready(engine)
        altered = copy.deepcopy(history)
        altered[0]["content"] = "Correction: do not use that old instruction."
        self.assertIsNone(engine.select_context(altered + [{"role": "user", "content": "continue"}]))
        self.assertIsNone(engine.select_context(history[2:]))

    def test_tool_pairs_and_latest_turn_stay_intact(self):
        engine = self.engine()
        history = conversation(size=130)
        history[-1] = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "synthetic_lookup", "arguments": "{}"}}]}
        history += [{"role": "tool", "tool_call_id": "call_1", "content": "Synthetic receipt: no message sent."}, {"role": "assistant", "content": "There is no send receipt."}]
        engine.on_turn_complete(history)
        self.ready(engine)
        latest = {"role": "user", "content": "Please explain, do not send anything."}
        out = engine.select_context(history + [latest])
        self.assertIsNotNone(out, engine.get_status())
        self.assertEqual(out[-4:], history[-3:] + [latest])
        self.assertEqual([m for m in out if m["role"] == "tool"], [history[-2]])

    def test_unsupported_attachments_do_not_enter_store_or_observer(self):
        engine = self.engine()
        history = conversation(size=10)
        history[0]["content"] = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,SYNTHETIC"}}]
        engine.on_turn_complete(history)
        self.assertEqual(engine.store.read()["sources"], [])
        self.assertEqual(engine.get_status()["last_error"], "unsupported_or_sensitive_input")
        self.assertIsNone(engine.select_context(history))

    def test_system_and_reasoning_not_saved(self):
        history = [{"role": "system", "content": "Never copy this system instruction."}] + conversation(size=10)
        history[2]["reasoning_content"] = "PRIVATE_CHAIN_SHOULD_NOT_COPY"
        engine = self.engine()
        engine.on_turn_complete(history)
        self.ready(engine)
        data = json.dumps(engine.store.read())
        self.assertNotIn("Never copy this system", data)
        self.assertNotIn("PRIVATE_CHAIN_SHOULD_NOT_COPY", data)

    def test_interrupted_turn_does_not_observe(self):
        engine = self.engine()
        engine.on_turn_complete(conversation(), interrupted=True)
        self.assertEqual(engine.store.read()["sources"], [])

    def test_closed_or_forgotten_session_rejects_late_worker(self):
        entered, release = threading.Event(), threading.Event()
        class HeldObserver:
            def observe(self, sources, *, observed_at):
                from observational.observer import ExtractiveObserver
                entered.set()
                release.wait(5)
                return ExtractiveObserver().observe(sources, observed_at=observed_at)
        engine = self.engine(observer=HeldObserver())
        engine.on_turn_complete(conversation(size=20))
        self.assertTrue(entered.wait(3))
        engine.store.forget()
        release.set()
        self.assertTrue(engine.wait_until_idle(8))
        state = engine.store.read()
        self.assertTrue(state["disabled"])
        self.assertEqual(state["sources"], [])
        self.assertEqual(state["observations"], [])
        engine.on_turn_complete(conversation(size=20))
        self.assertEqual(engine.store.read()["sources"], [])

    def test_expired_observer_result_not_published(self):
        from observational.observer import ExtractiveObserver
        class Slow:
            def observe(self, sources, *, observed_at):
                time.sleep(0.08)
                return ExtractiveObserver().observe(sources, observed_at=observed_at)
        engine = self.engine(observer=Slow(), job_timeout_seconds=0.02)
        engine.on_turn_complete(conversation(size=15))
        self.assertTrue(engine.wait_until_idle(8))
        self.assertEqual(engine.store.read()["observations"], [])
        self.assertEqual(engine.get_status()["last_error"], "observation_deadline_exceeded")

    def test_duplicate_text_has_distinct_sources(self):
        sources = normalize_sources([{"role": "user", "content": "same"}, {"role": "assistant", "content": "same"}, {"role": "user", "content": "same"}])
        self.assertEqual(len({s["id"] for s in sources}), 3)

    def test_incremental_observation_appends_coverage_without_duplicates(self):
        engine = self.engine()
        # Large enough that a bounded exact-quote log actually saves space.
        history = conversation(size=160)
        previous_covered = 0
        for stop in range(2, len(history) + 1, 2):
            engine.on_turn_complete(history[:stop])
            self.ready(engine)
            state = engine.store.read()
            self.assertGreaterEqual(len(state["covered_ids"]), previous_covered)
            previous_covered = len(state["covered_ids"])
            self.assertEqual(len(state["observations"]), len({o["id"] for o in state["observations"]}))
        self.assertEqual(previous_covered, 8)
        final_request = history + [{"role": "user", "content": "Recall the plans, do not act."}]
        self.assertIsNotNone(engine.select_context(final_request))

    def test_source_revision_during_worker_cannot_publish_stale_evidence(self):
        entered, release = threading.Event(), threading.Event()
        class OnceHeld:
            calls = 0
            def observe(self, sources, *, observed_at):
                from observational.observer import ExtractiveObserver
                self.calls += 1
                if self.calls == 1:
                    entered.set()
                    release.wait(5)
                return ExtractiveObserver().observe(sources, observed_at=observed_at)
        engine = self.engine(observer=OnceHeld())
        history = conversation(size=180)
        engine.on_turn_complete(history)
        self.assertTrue(entered.wait(3))
        corrected = copy.deepcopy(history)
        corrected[0]["content"] = "Correction: the previous plan was withdrawn. Do not send anything."
        engine.on_turn_complete(corrected)
        release.set()
        self.assertTrue(engine.wait_until_idle(10))
        state = engine.store.read()
        old_id = normalize_sources(history)[0]["id"]
        self.assertFalse(any(old_id in o["source_ids"] for o in state["observations"]))
        self.assertGreaterEqual(engine.get_status()["discarded_runs"], 1)
        self.assertIsNotNone(engine.select_context(corrected + [{"role": "user", "content": "What changed?"}]))

    def test_no_projection_when_evidence_wrapper_would_grow_request(self):
        engine = self.engine()
        history = conversation(size=25)
        engine.on_turn_complete(history)
        self.ready(engine)
        self.assertTrue(engine.store.read()["observations"])
        self.assertIsNone(engine.select_context(history + [{"role": "user", "content": "Continue analysis only."}]))

    def test_human_forget_cli_dry_run_confirm_and_restart(self):
        import subprocess, sys
        engine = self.engine()
        engine.on_turn_complete(conversation(size=45))
        self.ready(engine)
        script = Path(__file__).resolve().parents[1] / "tools/forget.py"
        command = [sys.executable, str(script), "--home", str(self.home), "--session-id", "synthetic"]
        dry = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse(json.loads(dry.stdout)["changed"])
        self.assertTrue(engine.store.read()["sources"])
        confirmed = subprocess.run(command + ["--confirm-plugin-copy-deletion"], capture_output=True, text=True, timeout=10)
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.assertTrue(json.loads(confirmed.stdout)["disabled_tombstone"])
        self.assertEqual(engine.store.read()["sources"], [])
        self.assertTrue(engine.store.read()["disabled"])

    def test_config_model_egress_requires_explicit_pin_and_opt_in(self):
        for values in ({"observer_mode": "model"}, {"observer_mode": "model", "allow_model_calls": True}, {"observer_mode": "model", "allow_model_calls": True, "provider": "auto", "model": "x"}):
            with self.assertRaises(ValueError):
                EngineConfig(**values).validate()
        self.assertEqual(EngineConfig().observer_mode, "extractive")


if __name__ == "__main__":
    unittest.main()
