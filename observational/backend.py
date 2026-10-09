"""Opt-in text-only bridge to an explicitly pinned existing Hermes route.

No tools, no system/profile memory injection, no automatic provider fallback.
Only the OpenAI Codex adapter is enabled in this release. Other providers need
an explicit adapter audit and their own integration test, not a guessed alias.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path


class HermesCompletion:
    def __init__(self, provider: str, model: str, *, timeout: float = 90.0, hermes_home=None):
        if provider != "openai-codex" or not isinstance(model, str) or not model or model != model.strip():
            raise ValueError("Only the explicitly pinned openai-codex route is verified")
        if not 0 < timeout <= 300:
            raise ValueError("Invalid timeout")
        from hermes_constants import get_hermes_home
        self.home = Path(hermes_home or get_hermes_home()).resolve(strict=True)
        self.provider, self.model, self.timeout = provider, model, timeout
        self._lock = threading.Lock()
        self.usage = {"provider": provider, "model": model, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "elapsed_seconds": 0.0, "errors": 0}

    def complete(self, system_prompt: str, user_payload: str, *, authorize=None) -> str:
        if not isinstance(system_prompt, str) or not isinstance(user_payload, str) or len(system_prompt) + len(user_payload) > 320000:
            raise ValueError("Invalid observer payload")
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        from agent.auxiliary_client import resolve_provider_client
        from agent.redact import redact_sensitive_text
        if any(redact_sensitive_text(s, force=True, redact_url_credentials=True) != s for s in (system_prompt, user_payload)):
            raise ValueError("Sensitive observer payload refused")
        token = set_hermes_home_override(str(self.home))
        client = None
        started = time.monotonic()
        try:
            if authorize is not None:
                authorize()
            client, resolved = resolve_provider_client(self.provider, model=self.model, async_mode=False, main_runtime={"provider": self.provider, "model": self.model})
            if client is None or resolved != self.model:
                raise RuntimeError("Pinned observer route unavailable")
            # Resolution can block. Recheck the captured job authorization at
            # completion admission, not only when the worker was queued. A call
            # already admitted here may finish; this is not transport revocation.
            if authorize is not None:
                authorize()
            with self._lock:
                self.usage["calls"] += 1
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_payload}],
                # Codex ignores max_tokens at the adapter boundary; acceptance is
                # separately size/deadline-bounded. This is not a billing-token cap.
                max_tokens=4096,
                timeout=self.timeout,
                extra_body={"reasoning": {"effort": "low"}},
            )
            if time.monotonic() - started > self.timeout:
                raise TimeoutError("Observer deadline exceeded")
            usage = getattr(response, "usage", None)
            with self._lock:
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = getattr(usage, field, None)
                    if type(value) is int and value >= 0:
                        self.usage[field] += value
            choices = getattr(response, "choices", None)
            if not choices or getattr(choices[0].message, "tool_calls", None):
                raise ValueError("Observer did not return plain text")
            text = getattr(choices[0].message, "content", None)
            if not isinstance(text, str) or not text or len(text) > 24000:
                raise ValueError("Invalid observer response")
            return text
        except Exception:
            with self._lock:
                self.usage["errors"] += 1
            raise RuntimeError("Pinned observer call failed; no fallback attempted") from None
        finally:
            with self._lock:
                self.usage["elapsed_seconds"] += time.monotonic() - started
            # The direct resolver creates this client rather than borrowing the
            # shared auxiliary call cache. Close only our own client.
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            reset_hermes_home_override(token)
