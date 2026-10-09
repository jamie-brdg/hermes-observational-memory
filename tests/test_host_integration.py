"""Exercise the real installed loader and host hook call sites, not mock ABCs."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from observational.engine import EngineConfig, ObservationalEngine

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("om_installer_under_test", ROOT / "tools/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class HostIntegrationTests(unittest.TestCase):
    def test_create_only_install_and_real_user_plugin_discovery(self):
        from plugins.context_engine import load_context_engine, find_engine_dir
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            receipt = installer.install(home)
            self.assertFalse(receipt["activated"])
            self.assertFalse((home / "config.yaml").exists())
            token = set_hermes_home_override(temp)
            try:
                self.assertEqual(find_engine_dir("observational"), home / "plugins/observational")
                engine = load_context_engine("observational")
                self.assertIsNotNone(engine)
                self.assertEqual(engine.name, "observational")
                # Discovery/availability probing must not create memory databases.
                self.assertFalse((home / "observational-memory").exists())
                clone = engine.clone_for_agent()
                self.assertIsNot(clone, engine)
                engine.update_model("synthetic", 64000, "", "", "synthetic", "chat_completions")
                engine.on_session_start("host-loader-fixture", hermes_home=temp, model="synthetic", context_length=64000)
                try:
                    self.assertEqual(engine.context_length, 64000)
                    self.assertEqual(engine.get_status()["source_count"], 0)
                finally:
                    engine.on_session_end("host-loader-fixture", [])
                with self.assertRaises(FileExistsError):
                    installer.install(home)
            finally:
                reset_hermes_home_override(token)
                for name in tuple(sys.modules):
                    if name.startswith("_hermes_user_context_engine.observational"):
                        sys.modules.pop(name, None)

    def test_actual_host_post_turn_and_request_selection_preserve_transcript(self):
        from agent.conversation_loop import _apply_context_engine_selection, _notify_context_engine_turn_complete
        with tempfile.TemporaryDirectory() as temp:
            engine = ObservationalEngine(config=EngineConfig(observe_min_chars=1, max_batch_chars=96000))
            engine.on_session_start("host-hook-fixture", hermes_home=temp, model="synthetic")
            history = []
            for i in range(6):
                history += [{"role": "user", "content": f"Plan {i}: not sent. " + "Old detail. " * 220, "message_uid": f"u{i}"}, {"role": "assistant", "content": "No verified send receipt.", "message_uid": f"a{i}"}]
            before = copy.deepcopy(history)
            agent = SimpleNamespace(context_compressor=engine, session_id="host-hook-fixture", model="synthetic", model_max_context=200000)
            logger = MagicMock()
            try:
                _notify_context_engine_turn_complete(agent, history, usage={"prompt_tokens": 20000}, logger=logger, turn_id="turn-6", interrupted=False)
                self.assertTrue(engine.wait_until_idle(10), engine.get_status())
                request = [{"role": "system", "content": "Real host integration fixture."}] + history + [{"role": "user", "content": "What is unsent?"}]
                out = _apply_context_engine_selection(agent, request, history, request[-1], logger=logger)
                self.assertLess(len(json.dumps(out)), len(json.dumps(request)), engine.get_status())
                self.assertEqual(history, before)
                self.assertEqual(out[-1], request[-1])
                self.assertEqual(out[0], request[0])
                self.assertFalse(logger.warning.called)
            finally:
                engine.on_session_end("host-hook-fixture", history)

    def test_installer_refuses_symlink_without_destination_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home, elsewhere = root / "home", root / "elsewhere"
            home.mkdir()
            elsewhere.mkdir()
            (home / "plugins").symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaises(ValueError):
                installer.install(home)
            self.assertEqual(list(elsewhere.iterdir()), [])
