"""Exact-evidence contracts shared by the observer, store and engine.

These contracts establish what was *said*, not whether it is true.  No source
text is executable instruction, no kind is a verified state, and validation
never repairs or normalizes supplied identity/evidence.  Only stdlib imports.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re
import unicodedata
from typing import Any


KINDS = frozenset({"intent", "reported_outcome", "preference", "constraint",
                   "correction", "fact", "tool_output", "other"})
ATTRIBUTIONS = {"user": "user_statement", "assistant": "assistant_statement",
                "tool": "tool_output"}
_SOURCE_KEYS = frozenset({"id", "ordinal", "role", "text", "wire", "digest",
                          "message_uid", "occurred_at"})
_OBSERVATION_KEYS = frozenset({"id", "source_ids", "quote", "kind", "priority",
                               "attribution", "observed_at"})
_WIRE_KEYS = frozenset({"role", "content", "name", "tool_calls", "tool_call_id"})
_UTC_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                      r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)\Z")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_JSON_DEPTH = 64


def _json_value(value: Any, ancestors: set[int], depth: int) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    value_type = type(value)
    if value is None or value_type in (bool, int):
        return
    if value_type is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("JSON strings must be valid UTF-8") from None
        return
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if value_type not in (dict, list):
        raise ValueError("Value is not a strict JSON type")
    identity = id(value)
    if identity in ancestors:
        raise ValueError("JSON containers must not be cyclic")
    ancestors.add(identity)
    try:
        if value_type is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError("JSON object keys must be strings")
                _json_value(key, ancestors, depth + 1)
                _json_value(item, ancestors, depth + 1)
        else:
            for item in value:
                _json_value(item, ancestors, depth + 1)
    finally:
        ancestors.remove(identity)


def canonical_json(value: Any) -> str:
    """Return strict, deterministic JSON without coercion or text normalization."""
    _json_value(value, set(), 0)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise ValueError("Value cannot be represented as canonical JSON") from None


def digest_wire(wire: dict) -> str:
    """Hash exact canonical message wire data, not a generated summary."""
    if type(wire) is not dict:
        raise ValueError("wire must be a JSON object")
    return hashlib.sha256(canonical_json(wire).encode("utf-8")).hexdigest()


def _identifier(value: Any, field: str) -> None:
    if (type(value) is not str or not value or value != value.strip()
            or any(unicodedata.category(char).startswith("C") for char in value)):
        raise ValueError(field + " must be a nonblank identifier without boundary whitespace or controls")


def _exact_keys(value: Any, keys: frozenset, field: str) -> None:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(field + " has missing or unknown fields")


def _validate_timestamp(value: Any) -> datetime:
    if type(value) is not str or _UTC_ISO.fullmatch(value) is None:
        raise ValueError("observed_at must be an explicit UTC ISO timestamp with seconds")
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        # Python 3.9's fromisoformat only accepts some fraction widths. strptime
        # accepts the full 1..6-digit ISO microsecond range without rewriting it.
        pattern = "%Y-%m-%dT%H:%M:%S" + (".%f" if "." in normalized else "") + "%z"
        return datetime.strptime(normalized, pattern)
    except ValueError:
        raise ValueError("observed_at is not a valid UTC timestamp") from None


def _validate_wire(wire: dict) -> str:
    if not set(wire).issubset(_WIRE_KEYS) or "role" not in wire:
        raise ValueError("wire has missing or unsupported fields")
    role = wire["role"]
    if type(role) is not str or role not in ATTRIBUTIONS:
        raise ValueError("wire.role is unsupported")
    if "name" in wire:
        _identifier(wire["name"], "wire.name")
    if "tool_call_id" in wire:
        if role != "tool":
            raise ValueError("wire.tool_call_id requires the tool role")
        _identifier(wire["tool_call_id"], "wire.tool_call_id")
    if "tool_calls" in wire:
        calls = wire["tool_calls"]
        if role != "assistant" or type(calls) is not list or not calls:
            raise ValueError("wire.tool_calls requires a nonempty assistant call list")
        seen = set()
        for call in calls:
            _exact_keys(call, frozenset({"id", "type", "function"}), "wire.tool_calls item")
            _identifier(call["id"], "wire.tool_calls id")
            if call["id"] in seen:
                raise ValueError("wire.tool_calls has duplicate call IDs")
            seen.add(call["id"])
            if call["type"] != "function":
                raise ValueError("wire.tool_calls type must be function")
            function = call["function"]
            _exact_keys(function, frozenset({"name", "arguments"}), "wire.tool_calls function")
            _identifier(function["name"], "wire.tool_calls function name")
            if type(function["arguments"]) is not str:
                raise ValueError("wire.tool_calls arguments must be a string")
    content = wire.get("content")
    if type(content) is str:
        return content
    if content is None and role == "assistant" and wire.get("tool_calls"):
        return ""
    raise ValueError("wire.content must be plain text (or null for assistant tool calls)")


def validate_sources(sources: list[dict]) -> list[dict]:
    """Validate an ordered source snapshot, return detached JSON copies.

    A digest binds wire bytes; role/text must independently match those bytes.
    Secret filtering, turn pairing and namespace authorization belong to the
    ingestion/store boundary, not this syntactic evidence validator.
    """
    if type(sources) is not list:
        raise ValueError("sources must be a list")
    seen_ids = set()
    previous_ordinal = -1
    result = []
    for candidate in sources:
        # Validate precisely the detached value that will be returned. Checking
        # a caller-owned object after serializing it could validate newer fields
        # but return an earlier, invalid role/digest/metadata snapshot.
        source = json.loads(canonical_json(candidate))
        _exact_keys(source, _SOURCE_KEYS, "source")
        _identifier(source["id"], "source.id")
        if source["id"] in seen_ids:
            raise ValueError("sources contain a duplicate id")
        seen_ids.add(source["id"])
        ordinal = source["ordinal"]
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError("source.ordinal must be a nonnegative integer")
        if ordinal <= previous_ordinal:
            raise ValueError("source ordinals must be unique and strictly increasing")
        previous_ordinal = ordinal
        role = source["role"]
        if type(role) is not str or role not in ATTRIBUTIONS:
            raise ValueError("source.role is unsupported")
        if type(source["text"]) is not str:
            raise ValueError("source.text must be a string")
        if type(source["message_uid"]) is not str:
            raise ValueError("source.message_uid must be a string")
        if source["occurred_at"] is not None and type(source["occurred_at"]) is not str:
            raise ValueError("source.occurred_at must be a string or null")
        digest = source["digest"]
        if type(digest) is not str or _HEX_DIGEST.fullmatch(digest) is None:
            raise ValueError("source.digest must be lowercase SHA256 hex")
        if digest != digest_wire(source["wire"]):
            raise ValueError("source.digest does not match wire")
        wire_text = _validate_wire(source["wire"])
        if role != source["wire"]["role"]:
            raise ValueError("source.role does not match wire.role")
        if source["text"] != wire_text:
            raise ValueError("source.text does not match wire.content")
        result.append(source)
    return result


def _evidence_fields(source_ids: Any, quote: Any, kind: Any) -> None:
    if type(source_ids) is not list or not source_ids:
        raise ValueError("source_ids must be a nonempty list")
    seen = set()
    for source_id in source_ids:
        _identifier(source_id, "source_ids item")
        if source_id in seen:
            raise ValueError("source_ids must not contain duplicates")
        seen.add(source_id)
    if type(quote) is not str or not quote.strip():
        raise ValueError("quote must be a nonblank exact substring")
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("kind is unsupported")


def observation_id(source_ids: list[str], quote: str, kind: str) -> str:
    """Stable evidence identity; reference order is not part of that identity."""
    _evidence_fields(source_ids, quote, kind)
    payload = {"version": 1, "source_ids": sorted(source_ids), "quote": quote, "kind": kind}
    return "obs_" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _observation_shape(observation: Any) -> dict:
    observation = json.loads(canonical_json(observation))
    _exact_keys(observation, _OBSERVATION_KEYS, "observation")
    _evidence_fields(observation["source_ids"], observation["quote"], observation["kind"])
    expected = observation_id(observation["source_ids"], observation["quote"], observation["kind"])
    if type(observation["id"]) is not str or observation["id"] != expected:
        raise ValueError("observation.id does not match evidence identity")
    priority = observation["priority"]
    if type(priority) is not int or not 0 <= priority <= 3:
        raise ValueError("observation.priority must be an integer from 0 through 3")
    attribution = observation["attribution"]
    if type(attribution) is not str or attribution not in ATTRIBUTIONS.values():
        raise ValueError("observation.attribution is unsupported")
    _validate_timestamp(observation["observed_at"])
    return observation


def _observation_batch(observations: Any) -> list[dict]:
    if type(observations) is not list:
        raise ValueError("observations must be a list")
    seen = set()
    result = []
    for candidate in observations:
        observation = _observation_shape(candidate)
        if observation["id"] in seen:
            raise ValueError("observations contain a duplicate id")
        seen.add(observation["id"])
        result.append(observation)
    return result


def validate_observations(observations: list[dict], sources: list[dict]) -> list[dict]:
    """Validate an entire batch atomically against exact source evidence."""
    by_id = {source["id"]: source for source in validate_sources(sources)}
    result = _observation_batch(observations)
    for observation in result:
        roles = set()
        for source_id in observation["source_ids"]:
            if source_id not in by_id:
                raise ValueError("observation references an unknown source id")
            source = by_id[source_id]
            if observation["quote"] not in source["text"]:
                raise ValueError("observation.quote is not an exact substring of every source")
            roles.add(source["role"])
        if len(roles) != 1:
            raise ValueError("observation source roles must not be mixed")
        if observation["attribution"] != ATTRIBUTIONS[next(iter(roles))]:
            raise ValueError("observation.attribution does not match its source role")
    return result


def render_observation(obs: dict) -> str:
    """Full metadata + escaped evidence as one JSON line, including its newline.

    The enclosing engine must label the whole block as untrusted remembered
    statements. JSON quoting prevents raw line injection but is not a promise
    that an LLM will ignore hostile text. No field implies verified truth.
    """
    return canonical_json(_observation_shape(obs)) + "\n"


def _recency_key(observed_at: str) -> int:
    dt = _validate_timestamp(observed_at)
    return (((dt.toordinal() * 24 + dt.hour) * 60 + dt.minute) * 60 + dt.second) * 1000000 + dt.microsecond


def reflect(observations: list[dict], max_chars: int) -> list[str]:
    """Select stored IDs only, charging complete rendered record lengths.

    Corrections, constraints and intentions lead; within each tier, higher
    priority then newer UTC observation times win. Later log positions break
    equal-time ties. Oversized records are skipped, never clipped or erased.
    This function has no sources: callers must validate source linkage before
    storing records. It still validates shape, identity and duplicate IDs.
    """
    if type(max_chars) is not int or max_chars < 0:
        raise ValueError("max_chars must be a nonnegative integer")
    candidates = _observation_batch(observations)
    tier = {"correction": 0, "constraint": 1, "intent": 2}
    ranked = sorted(enumerate(candidates), key=lambda pair: (
        tier.get(pair[1]["kind"], 3), -pair[1]["priority"],
        -_recency_key(pair[1]["observed_at"]), -pair[0], pair[1]["id"]))
    active = []
    remaining = max_chars
    for _, observation in ranked:
        cost = len(render_observation(observation))
        if cost <= remaining:
            active.append(observation["id"])
            remaining -= cost
    return active
