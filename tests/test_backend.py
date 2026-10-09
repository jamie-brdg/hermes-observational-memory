import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hermes_constants import get_hermes_home
from observational.backend import HermesCompletion


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.backend = HermesCompletion("openai-codex", "synthetic-model", timeout=20, hermes_home=self.home)
        self.create = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"observations": []}', tool_calls=None))], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=7, total_tokens=17)))
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)), close=Mock())

    def tearDown(self):
        self.tmp.cleanup()

    def test_pinned_profile_route_no_tools_and_usage(self):
        original = get_hermes_home()
        def resolve(provider, **kwargs):
            self.assertEqual(get_hermes_home(), self.home.resolve())
            self.assertEqual(provider, "openai-codex")
            self.assertEqual(kwargs["model"], "synthetic-model")
            return self.client, "synthetic-model"
        with patch("agent.auxiliary_client.resolve_provider_client", side_effect=resolve) as resolver:
            self.assertEqual(self.backend.complete("observer instructions", "synthetic source"), '{"observations": []}')
        self.assertEqual(get_hermes_home(), original)
        self.assertEqual(resolver.call_count, 1)
        params = self.create.call_args.kwargs
        self.assertNotIn("tools", params)
        self.assertEqual(params["timeout"], 20)
        self.assertEqual(params["model"], "synthetic-model")
        self.assertEqual(len(params["messages"]), 2)
        self.assertEqual(self.backend.usage["total_tokens"], 17)
        self.assertEqual(self.backend.usage["calls"], 1)
        self.client.close.assert_called_once()

    def test_unavailable_or_changed_model_has_no_call_or_fallback(self):
        for resolved in [(None, None), (self.client, "other-model")]:
            with self.subTest(resolved=resolved[1]):
                with patch("agent.auxiliary_client.resolve_provider_client", return_value=resolved) as resolver:
                    with self.assertRaisesRegex(RuntimeError, "no fallback attempted"):
                        self.backend.complete("system", "data")
                    self.assertEqual(resolver.call_count, 1)
        self.create.assert_not_called()

    def test_exception_is_sanitized_and_profile_reset(self):
        original = get_hermes_home()
        self.create.side_effect = RuntimeError("SOURCE_CONTENT_MUST_NOT_ESCAPE")
        with patch("agent.auxiliary_client.resolve_provider_client", return_value=(self.client, "synthetic-model")):
            with self.assertRaises(RuntimeError) as error:
                self.backend.complete("system", "data")
        self.assertNotIn("SOURCE_CONTENT", str(error.exception))
        self.assertEqual(get_hermes_home(), original)
        self.client.close.assert_called_once()
        self.assertEqual(self.backend.usage["errors"], 1)

    def test_model_output_bound_and_tool_call_rejection(self):
        for message in [SimpleNamespace(content="x" * 24001, tool_calls=None), SimpleNamespace(content="hello", tool_calls=[{"id": "no-tools"}]), SimpleNamespace(content=None, tool_calls=None)]:
            with self.subTest(kind=type(message.content).__name__):
                self.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
                with patch("agent.auxiliary_client.resolve_provider_client", return_value=(self.client, "synthetic-model")):
                    with self.assertRaises(RuntimeError):
                        self.backend.complete("system", "data")

    def test_auto_unverified_and_whitespace_routes_are_refused(self):
        for provider, model in [("auto", "x"), ("moa", "x"), ("openrouter", "x"), ("openai-codex", " x ")]:
            with self.assertRaises(ValueError):
                HermesCompletion(provider, model, hermes_home=self.home)

    def test_sensitive_payload_is_refused_before_provider_resolution(self):
        fake = "sk-" + "A" * 50
        with patch("agent.auxiliary_client.resolve_provider_client") as resolver:
            with self.assertRaises(ValueError):
                self.backend.complete("system", "api_key=" + fake)
        resolver.assert_not_called()
