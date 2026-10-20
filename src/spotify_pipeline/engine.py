"""Bounded, auditable orchestration. Importing this module makes no API calls.

Only explicit calls to ``enrich``, ``verify`` or ``model_task`` can incur spend.
The CLI adds a separate --execute-paid gate. Production data never uses mocks.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .data import row_sha
from .models import Classification, CompletedRecord, SourceReview, SOURCE_FIELDS
from .providers import (JevProvider, OpenAIProvider, ProviderError,
                        AuthenticationProviderError, MalformedProviderResponse,
                        normalize_usage)
from .storage import (BudgetExceeded, BudgetLedger, ResultStore, atomic_json,
                      atomic_jsonl, canonical, reserve_request_slot, utcnow)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSIFICATION_FIELDS = tuple(Classification.model_fields)
ENTITY_PATTERN = re.compile(r"\b(?:Spotify Premium|Android Auto|Google Home|Chromecast|Bluetooth|CarPlay|AirPlay|Android|Premium|Spotify|Alexa|iOS|lyrics|podcasts)\b", re.IGNORECASE)


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else REPO_ROOT / "config/pipeline.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["_root"] = str(path.resolve().parent.parent)
    return _hydrate(config)


def _hydrate(config: dict) -> dict:
    config = dict(config)
    root = Path(config.get("_root", REPO_ROOT))
    prompts_dir = Path(config.get("prompts_dir", "prompts"))
    if not prompts_dir.is_absolute():
        prompts_dir = root / prompts_dir
    config["_prompts"] = dict(config.get("_prompts") or {
        name: (prompts_dir / f"{name}.md").read_text(encoding="utf-8")
        for name in ("labels", "enrich", "fallback", "verify", "group", "memo")
    })
    config["_root"] = str(root)
    return config


def fingerprint(config: dict) -> str:
    # Operational controls and prices do not affect language judgments.
    keys = ("schema_version", "prompt_version", "models", "reasoning_effort", "max_output_tokens",
            "max_reviews_per_request", "max_batch_input_bytes", "fallback_fraction", "uncertainty_threshold", "_prompts")
    payload = {key: config.get(key) for key in keys}
    payload["provider_request_template"] = JevProvider(api_key="fingerprint-only").build_request("<REVIEW_TEXT>", "<LABEL_PROMPT>")
    payload["classification_schema"] = classification_schema()
    payload["openai_request_template"] = OpenAIProvider.build_request(
        model=config["models"]["verify"], prompt="<ROLE_PROMPT>", payload={"reviews": []},
        schema=classification_schema(), reasoning_effort="none", max_output_tokens=config.get("max_output_tokens", 6000))
    payload["entity_pattern"] = ENTITY_PATTERN.pattern
    payload["engine_logic_version"] = "pilot-v1"
    return "spotify-" + hashlib.sha256(canonical(payload).encode()).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classification_schema() -> dict:
    schema = Classification.model_json_schema()
    schema.pop("title", None)
    schema["properties"] = {"review_id": {"type": "string"}, **schema["properties"]}
    schema["required"] = ["review_id", *schema["required"]]
    schema["additionalProperties"] = False
    return {"type": "object", "properties": {"reviews": {"type": "array", "items": schema}},
            "required": ["reviews"], "additionalProperties": False}


def validate_schema(value: Any, schema: dict, path: str = "output") -> None:
    """Small strict validator for the JSON schema subset emitted by our roles."""
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                validate_schema(value, option, path)
                return
            except ValueError:
                pass
        raise ValueError(f"{path}: no anyOf alternative matched")
    expected = schema.get("type")
    if isinstance(expected, list):
        for alternative in expected:
            try:
                validate_schema(value, {**schema, "type": alternative}, path)
                return
            except ValueError:
                pass
        raise ValueError(f"{path}: no allowed type matched")
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "boolean": isinstance(value, bool),
               "integer": isinstance(value, int) and not isinstance(value, bool),
               "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
               "null": value is None}
    if expected and not matches.get(expected, False):
        raise ValueError(f"{path}: expected {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - set(value)
        properties = schema.get("properties", {})
        if missing or (schema.get("additionalProperties") is False and set(value) - set(properties)):
            raise ValueError(f"{path}: missing or unexpected object fields")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ValueError(f"{path}: array length out of range")
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ValueError(f"{path}: string too short")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(f"{path}: numeric bounds")


class Engine:
    def __init__(self, config: dict, db_path: str | Path, run_dir: str | Path,
                 budget_usd: float = 1.5, workers: int = 1, providers: dict | None = None):
        self.config = _hydrate(config)
        self.label_config = fingerprint(self.config)
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.handoffs = self.run_dir / "handoffs"
        self.handoffs.mkdir(exist_ok=True)
        self.run_id = f"{self.run_dir.name}-{hashlib.sha256(str(self.run_dir).encode()).hexdigest()[:8]}"
        self.budget_usd = float(budget_usd)
        if not 1 <= workers <= min(16, self.config.get("max_workers", 16)):
            raise ValueError("workers must be between 1 and the configured maximum (at most 16)")
        if not 0 <= self.config.get("fallback_fraction", .05) <= .05:
            raise ValueError("fallback fraction must be between 0 and 0.05")
        if not 1 <= self.config.get("max_reviews_per_request", 25) <= 50:
            raise ValueError("requests must contain between 1 and 50 reviews")
        allowed = self.config.get("allowed_models", {"jev": ["jev-1.13.0"], "openai": ["gpt-6-luna"]})
        for role, model in self.config["models"].items():
            provider = "jev" if role == "enrich" else "openai"
            if model not in allowed.get(provider, []):
                raise ValueError(f"Model {model} is not in the explicit {provider} allowlist")
        self.workers = workers
        self.store = ResultStore(db_path)
        ledger_path = Path(self.config.get("ledger_path", "data/spend.sqlite3"))
        if not ledger_path.is_absolute():
            ledger_path = Path(self.config["_root"]) / ledger_path
        self.ledger = BudgetLedger(ledger_path)
        self.providers = providers or {}
        self.started = time.monotonic()
        self.phase = "initial"
        self.rows: list[dict] = []
        self.records: list[dict] = []
        self.cache_hits = 0
        self.task_cache_hits = 0
        self.limitations: list[str] = []
        self.stages: dict = {}
        self._closed = False
        self._stop_dispatch = False
        self._semaphore = asyncio.Semaphore(workers)
        self._last_request_id: str | None = None
        self._verification: list[dict] = []
        self._task_source_request_ids: set[str] = set()
        for prior_handoff in self.handoffs.glob("task-*.json"):
            previous = json.loads(prior_handoff.read_text(encoding="utf-8"))
            if previous.get("source_request_id"):
                self._task_source_request_ids.add(previous["source_request_id"])
        self._export_calls()
        atomic_json(self.run_dir / "configuration.json", {key: value for key, value in self.config.items() if key != "_root"})

    def _provider(self, name: str):
        if name not in self.providers:
            self.providers[name] = (JevProvider(model=self.config["models"]["enrich"]) if name == "jev" else OpenAIProvider())
        provider = self.providers[name]
        if isinstance(provider, (JevProvider, OpenAIProvider)) and not getattr(provider, "_api_key", None):
            raise AuthenticationProviderError(f"Set {provider.env_name} before paid execution; no request was sent", usage_unknown=False)
        return provider

    def _prompt(self, role: str) -> str:
        prompt = self.config["_prompts"][role]
        if role in {"enrich", "fallback", "verify"}:
            prompt = self.config["_prompts"]["labels"] + "\n\n" + prompt
        return prompt

    def _reserve_cost(self, provider: str, request: dict) -> float:
        # UTF-8 bytes bound ordinary tokenizer input conservatively; include a
        # fixed protocol margin. Output is bounded by the actual request cap.
        input_bound = len(canonical(request).encode("utf-8")) + 2048
        rates = self.config["rates"]
        if provider == "jev":
            return input_bound * rates["jev_input"] / 1_000_000
        output_bound = request.get("max_output_tokens", self.config.get("max_output_tokens", 6000))
        return (input_bound * rates["openai_input"] + output_bound * rates["openai_output"]) / 1_000_000

    def _billing(self, provider: str, raw_usage: dict | None) -> dict:
        try:
            normalized = normalize_usage(provider, raw_usage)
        except (ValueError, TypeError) as exc:
            self.limitations.append(f"Provider reported inconsistent usage: {exc}; full reservation retained")
            normalized = None
        if normalized is None:
            return {"input_tokens": None, "output_tokens": None, "billing_items": [], "cost_usd": None,
                    "usage_source": "unknown", "raw_usage": raw_usage}
        total = normalized.get("input_tokens")
        output = normalized.get("output_tokens")
        items = []
        known = total is not None
        if provider == "jev":
            if total is not None:
                items.append({"category": "input", "units": total, "rate_key": "jev_input"})
        else:
            cached = normalized.get("cached_input_tokens")
            if normalized.get("cache_write_tokens", 0):
                self.limitations.append("Unexpected cache-write usage despite explicit cache disabled; charge retained as unknown")
                known = False
            uncached = normalized.get("uncached_input_tokens")
            if cached is None or uncached is None:
                # No invented category split: the hold remains the conservative
                # bill estimate until provider billing can be reconciled.
                known = False
            else:
                items.extend([{"category": "input", "units": uncached, "rate_key": "openai_input"},
                              {"category": "cached_input", "units": cached, "rate_key": "openai_cached_input"}])
            if output is None:
                known = False
            else:
                items.append({"category": "output", "units": output, "rate_key": "openai_output"})
        amount = sum(item["units"] * self.config["rates"][item["rate_key"]] / 1_000_000 for item in items)
        return {"input_tokens": total, "output_tokens": output, "billing_items": items,
                "cost_usd": amount if known else None, "usage_source": "provider" if known else "provider_partial",
                "raw_usage": raw_usage, "normalized_usage": normalized}

    async def _invoke(self, *, provider: str, role: str, purpose: str, model: str,
                      review_ids: list[str], request: dict, dispatch: Callable,
                      validator: Callable | None = None, effort: str | None = None) -> dict:
        if len(review_ids) > 50 and role in {"enrich", "verify"}:
            raise ValueError("A classification request cannot exceed 50 reviews")
        malformed_count = 0
        transient_count = 0
        attempt = 0
        while True:
            if self._stop_dispatch:
                raise BudgetExceeded("Dispatch halted; existing checkpoints were preserved")
            attempt += 1
            request_id = uuid.uuid4().hex
            reserve = self._reserve_cost(provider, request)
            self.ledger.reserve(request_id, self.run_id, reserve,
                                global_cap_usd=self.config.get("global_budget_usd", 18), run_cap_usd=self.budget_usd)
            estimated_input_bound = len(canonical(request).encode("utf-8")) + 2048
            estimated_output_bound = 0 if provider == "jev" else request.get("max_output_tokens", self.config.get("max_output_tokens", 6000))
            limits = self.config.get("tokens_per_second", {"jev": 20000, "openai": 20000})
            token_rate = limits.get(provider, 20000) if isinstance(limits, dict) else limits
            delay = reserve_request_slot(self.ledger, provider, self.config.get("requests_per_second", 5),
                                         estimated_input_bound + estimated_output_bound, token_rate)
            call = {"request_id": request_id, "run_id": self.run_id, "role": role, "purpose": purpose,
                    "is_fallback": purpose == "fallback", "review_ids": review_ids, "provider": provider,
                    "model": model, "requested_model": model, "phase": self.phase, "outcome": "failed",
                    "label_config": self.label_config, "started_at": utcnow(), "attempt": attempt,
                    "workers": self.workers, "reasoning_effort": effort, "reserved_usd": reserve,
                    "schema_version": self.config["schema_version"], "prompt_version": self.config["prompt_version"],
                    "input_tokens": None, "output_tokens": None, "usage_source": "unknown", "cost_usd": None,
                    "estimated_admission_tokens": estimated_input_bound + estimated_output_bound,
                    "token_pacing_limit_per_second": token_rate,
                    "billing_items": [], "error": "in_flight_or_interrupted", "duration_seconds": 0}
            self.store.save_call(call)
            atomic_json(self.handoffs / f"{request_id}.request.json", {"role": role, "purpose": purpose, "provider": provider, "body": request})
            timer = time.monotonic()
            response = None
            api_timer = None
            error = None
            retry = False
            try:
                if delay:
                    await asyncio.sleep(delay)
                api_timer = time.monotonic()
                response = await dispatch()
                data = response.data
                if validator:
                    validator(data)
                call.update(self._billing(provider, response.usage))
                call.update(outcome="succeeded", model=response.model, error=None, provider_request_id=getattr(response, "request_id", None))
                atomic_json(self.handoffs / f"{request_id}.response.json", response.raw)
            except asyncio.CancelledError:
                error = "cancelled_in_flight_usage_unknown"
                call["error"] = error
                raise
            except (ValueError, ValidationError) as exc:
                error = exc
                call["error"] = f"invalid_output: {exc}"
                if response is not None:
                    call.update(self._billing(provider, response.usage))
                    atomic_json(self.handoffs / f"{request_id}.response.json", response.raw)
                malformed_count += 1
                retry = malformed_count <= min(1, self.config.get("malformed_retries", 1))
            except ProviderError as exc:
                error = exc
                call["error"] = f"{type(exc).__name__}: {exc}"
                call["http_status"] = exc.status_code
                call["provider_request_id"] = exc.request_id
                call.update(self._billing(provider, exc.usage))
                if exc.usage is None and not exc.usage_unknown:
                    call.update(cost_usd=0.0, usage_source="not_dispatched", input_tokens=0, output_tokens=0)
                if exc.raw is not None:
                    atomic_json(self.handoffs / f"{request_id}.response.json", exc.raw)
                if isinstance(exc, AuthenticationProviderError):
                    self._stop_dispatch = True
                elif isinstance(exc, MalformedProviderResponse):
                    malformed_count += 1
                    retry = malformed_count <= min(1, self.config.get("malformed_retries", 1))
                elif exc.transient:
                    transient_count += 1
                    retry = transient_count <= self.config.get("transient_retries", 2)
            except Exception as exc:
                error = exc
                call["error"] = f"unexpected_client_error: {type(exc).__name__}: {exc}"
                self._stop_dispatch = True
            finally:
                call["duration_seconds"] = time.monotonic() - timer
                call["admission_wait_seconds"] = delay
                call["api_duration_seconds"] = time.monotonic() - api_timer if api_timer is not None else 0
                call["unknown_charge_hold_usd"] = reserve if call["cost_usd"] is None else 0
                self.ledger.settle(request_id, call["cost_usd"])
                self.store.save_call(call)
                self._last_request_id = request_id
                # SQLite is the durable journal. Append completed attempts in
                # O(1), rebuilding the export only at startup/checkpoints.
                with (self.run_dir / "calls.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(canonical(call) + "\n")
            if error is None:
                return data
            if not retry:
                raise error
            import random
            base_delay = self.config.get("retry_backoff_seconds", 1)
            retry_delay = base_delay * 2 ** (attempt - 1) + random.uniform(0, base_delay / 4)
            if isinstance(error, ProviderError) and error.retry_after:
                try:
                    retry_delay = max(retry_delay, float(error.retry_after))
                except ValueError:
                    pass
            await asyncio.sleep(min(30, retry_delay))

    def _validate_batch(self, data: dict, rows: list[dict]):
        validate_schema(data, classification_schema())
        expected = {row["review_id"]: row for row in rows}
        observed = [item["review_id"] for item in data["reviews"]]
        if len(observed) != len(expected) or set(observed) != set(expected):
            raise ValueError("Returned IDs do not exactly match requested IDs")
        for item in data["reviews"]:
            result = {key: item[key] for key in CLASSIFICATION_FIELDS}
            Classification.model_validate(result)
            source = expected[item["review_id"]]
            if result["evidence_quote"] not in source["review_text"]:
                raise ValueError("Evidence quote is not an exact source substring")
            if any(entity.casefold() not in source["review_text"].casefold() for entity in result["entities"]):
                raise ValueError("Unsupported entity in classification")

    async def _openai_batch(self, rows: list[dict], purpose: str) -> dict:
        provider = self._provider("openai")
        payload = {"reviews": [{"review_id": row["review_id"], "review_text": row["review_text"]} for row in rows]}
        return await self.model_task("verify" if purpose == "verify" else "enrich", payload,
                                     classification_schema(), [row["review_id"] for row in rows],
                                     _purpose=purpose, _validator=lambda result: self._validate_batch(result, rows))

    def _jev_result(self, data: dict, row: dict) -> dict:
        result = {key: data[key] for key in ("topic", "intent", "severity", "sentiment")}
        result["entities"] = list(dict.fromkeys(match.group() for match in ENTITY_PATTERN.finditer(row["review_text"])))
        result["evidence_quote"] = row["review_text"]
        confidence = data.get("confidence", {})
        values = [value for value in confidence.values() if isinstance(value, (float, int))]
        uncertainty = min(values) if values else None
        reasons = []
        if uncertainty is None:
            reasons.append("provider_confidence_unavailable")
        elif uncertainty < self.config.get("uncertainty_threshold", .60):
            reasons.append("low_provider_confidence")
        if result["intent"] in {"praise", "request", "unclear"} and result["severity"] > 1:
            reasons.append("intent_severity_inconsistency")
        if result["intent"] in {"complaint", "cancellation"} and result["sentiment"] > .5:
            reasons.append("mixed_positive_complaint")
        if re.search(r"ignore (?:all |previous )?instructions|system prompt|output (?:only|the)|return (?:only|json)", row["review_text"], re.I):
            reasons.append("possible_prompt_injection")
        result["needs_review"] = bool(reasons)
        Classification.model_validate(result)
        return {**result, "confidence": confidence, "uncertainty_score": uncertainty,
                "review_reasons": reasons, "classifier_provider": "jev", "classifier_model": self.config["models"]["enrich"],
                "fallback_used": False}

    def _completed(self, row: dict, value: dict, origin_id: str) -> dict:
        record = {**row, "source_sha256": row_sha(row), "status": "completed", **value, "label_config": self.label_config}
        if origin_id != row["review_id"]:
            record["cache_source_id"] = origin_id
        CompletedRecord.model_validate(record)
        return record

    async def enrich(self, rows, phase: str = "initial", stop_after: int | None = None) -> list[dict]:
        if phase not in {"initial", "resume"}:
            raise ValueError("phase must be initial or resume")
        if stop_after is not None and stop_after < 0:
            raise ValueError("stop_after must be nonnegative")
        self.phase = phase
        self.rows = [SourceReview.model_validate({key: row[key] for key in SOURCE_FIELDS}).model_dump() for row in rows]
        ids = {row["review_id"] for row in self.rows}
        if len(ids) != len(self.rows):
            raise ValueError("Input contains duplicate review IDs")
        self._stop_dispatch = False
        timer = time.monotonic()
        before = [row["review_id"] for row in self.rows if (old := self.store.record(self.label_config, row["review_id"])) and old.get("status") == "completed" and old["source_sha256"] == row_sha(row)]
        atomic_json(self.run_dir / ("checkpoint_before.json" if phase == "resume" else "checkpoint_start.json"),
                    {"run_id": self.run_id, "label_config": self.label_config, "completed_ids": before, "created_at": utcnow()})
        groups: dict[str, list[dict]] = {}
        self.cache_hits = 0
        for row in self.rows:
            digest = text_hash(row["review_text"])
            if not row["review_text"].strip():
                record = {**row, "source_sha256": row_sha(row), "label_config": self.label_config,
                          "status": "quarantined", "reason": "empty_review_text", "attempt_count": 0}
                self.store.save_record(self.label_config, digest, record)
                continue
            groups.setdefault(digest, []).append(row)
        pending = []
        for digest, members in groups.items():
            cached = self.store.cached(self.label_config, digest)
            if cached and cached["origin_id"] in ids:
                # An origin must still refer to the identical source row.
                origin = next((row for row in members if row["review_id"] == cached["origin_id"]), None)
                prior = self.store.record(self.label_config, cached["origin_id"])
                if origin and prior and prior["source_sha256"] == row_sha(origin):
                    self.cache_hits += len(members)
                    continue
            previous = self.store.record(self.label_config, members[0]["review_id"])
            if previous and previous.get("status") == "quarantined" and previous["source_sha256"] == row_sha(members[0]):
                # Explicit unresolved failures are not paid again on ordinary resume.
                continue
            pending.append((digest, members[0]))
        selected = pending if stop_after is None else pending[:stop_after]
        queue = asyncio.Queue()
        for item in selected:
            queue.put_nowait(item)

        async def worker():
            while not queue.empty() and not self._stop_dispatch:
                try:
                    digest, row = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    provider = self._provider("jev")
                    prompt = self._prompt("enrich")
                    request = provider.build_request(row["review_text"], prompt)
                    result = await self._invoke(provider="jev", role="enrich", purpose="initial_classification",
                                                model=self.config["models"]["enrich"], review_ids=[row["review_id"]], request=request,
                                                dispatch=lambda: provider.classify(row["review_text"], prompt),
                                                validator=lambda data: self._jev_result(data, row))
                    value = self._jev_result(result, row)
                    record = self._completed(row, value, row["review_id"])
                    self.store.save_record(self.label_config, digest, record, cache_value=value)
                except BudgetExceeded as exc:
                    self._stop_dispatch = True
                    self.limitations.append(str(exc))
                except AuthenticationProviderError:
                    self._stop_dispatch = True
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._stop_dispatch:
                        self.limitations.append(f"Execution stopped: {type(exc).__name__}: {exc}")
                        raise
                    record = {**row, "source_sha256": row_sha(row), "label_config": self.label_config,
                              "status": "quarantined", "reason": f"classification_failed:{type(exc).__name__}:{exc}",
                              "attempt_count": sum(row["review_id"] in c["review_ids"] for c in self.store.calls(self.run_id))}
                    self.store.save_record(self.label_config, digest, record)
                finally:
                    queue.task_done()

        tasks = [asyncio.create_task(worker()) for _ in range(min(self.workers, len(selected)))]
        try:
            if tasks:
                await asyncio.gather(*tasks)
            if not self._stop_dispatch and stop_after is None:
                await self._fallback(groups, ids)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            self._materialize(groups, ids)
            self.stages["enrich"] = {"wall_seconds": time.monotonic() - timer, "workers": self.workers,
                                     "input_count": len(self.rows), "unique_nonempty_texts": len(groups), "cache_hits": self.cache_hits}
            completed_ids = [record["review_id"] for record in self.records if record["status"] == "completed"]
            atomic_json(self.run_dir / "checkpoint_after.json", {"run_id": self.run_id, "label_config": self.label_config, "completed_ids": completed_ids, "created_at": utcnow()})
            if stop_after is not None:
                atomic_json(self.run_dir / "checkpoint_before.json", {"run_id": self.run_id, "label_config": self.label_config, "completed_ids": completed_ids, "created_at": utcnow()})
            self.finish()
        return self.records

    async def _fallback(self, groups: dict, ids: set):
        used = 0
        candidates = []
        for digest, members in groups.items():
            cached = self.store.cached(self.label_config, digest)
            if not cached or cached["origin_id"] not in ids:
                continue
            value = cached["value"]
            if value.get("fallback_used"):
                used += 1
            elif value.get("needs_review"):
                contradictions = sum(reason != "low_provider_confidence" for reason in value.get("review_reasons", []))
                score = value.get("uncertainty_score")
                origin = next(row for row in members if row["review_id"] == cached["origin_id"])
                candidates.append((-contradictions, score if score is not None else -1, origin["review_id"], digest, origin))
        quota = max(0, math.floor(len(groups) * self.config.get("fallback_fraction", .05)) - used)
        chosen = sorted(candidates)[:quota]
        fallback_rows = [item[4] for item in chosen]
        by_id = {item[4]["review_id"]: item for item in chosen}
        for batch in self._batches(fallback_rows):
            try:
                output = await self._openai_batch(batch, "fallback")
            except BudgetExceeded as exc:
                self._stop_dispatch = True
                self.limitations.append(str(exc))
                break
            except AuthenticationProviderError:
                raise
            except Exception as exc:
                self.limitations.append(f"Fallback failed; valid Jev records retained with needs_review: {exc}")
                continue
            for item in output["reviews"]:
                _, _, _, digest, row = by_id[item["review_id"]]
                old = self.store.cached(self.label_config, digest)["value"]
                value = {key: item[key] for key in CLASSIFICATION_FIELDS}
                value.update(classifier_provider="openai", classifier_model=self.config["models"]["fallback"],
                             fallback_used=True, fallback_reason=old["review_reasons"], jev_prediction=old)
                self.store.save_record(self.label_config, digest, self._completed(row, value, row["review_id"]), cache_value=value)
        self.stages["fallback"] = {"eligible_unique_texts": len(candidates), "already_used": used,
                                    "maximum_unique_texts": math.floor(len(groups) * self.config.get("fallback_fraction", .05)),
                                    "selected_unique_texts": len(chosen)}

    def _materialize(self, groups: dict, ids: set):
        self.records = []
        reused_new = 0
        for row in self.rows:
            digest = text_hash(row["review_text"])
            cached = self.store.cached(self.label_config, digest) if row["review_text"].strip() else None
            if cached and cached["origin_id"] in ids:
                record = self._completed(row, cached["value"], cached["origin_id"])
                self.store.save_record(self.label_config, digest, record)
                if cached["origin_id"] != row["review_id"]:
                    reused_new += 1
            else:
                record = self.store.record(self.label_config, row["review_id"])
                if not record or record["source_sha256"] != row_sha(row):
                    # Propagate a failed exact-text origin honestly; no classification reuse.
                    members = groups.get(digest, [])
                    failed = self.store.record(self.label_config, members[0]["review_id"]) if members else None
                    reason = failed.get("reason") if failed and failed.get("status") == "quarantined" else None
                    record = {**row, "source_sha256": row_sha(row), "label_config": self.label_config,
                              "status": "quarantined" if reason else "pending", "reason": reason or "not_dispatched_or_interrupted",
                              "attempt_count": failed.get("attempt_count", 0) if reason else 0}
                    self.store.save_record(self.label_config, digest, record)
            self.records.append(record)
        self.stages["exact_text_aliases"] = reused_new
        atomic_jsonl(self.run_dir / "records.jsonl", self.records)

    def _batches(self, rows: list[dict]):
        batch = []
        current_bytes = 0
        estimated_output_tokens = 0
        for row in rows:
            length = len(canonical({"review_id": row["review_id"], "review_text": row["review_text"]}).encode())
            # Quotes repeat original text in structured outputs. Reserve room
            # for that text and fixed label keys rather than counting IDs only.
            output_estimate = math.ceil(len(row["review_text"].encode("utf-8")) / 2) + 160
            output_budget = int(self.config.get("max_output_tokens", 6000) * .8)
            if batch and (len(batch) >= self.config.get("max_reviews_per_request", 25) or
                          current_bytes + length > self.config.get("max_batch_input_bytes", 18000) or
                          estimated_output_tokens + output_estimate > output_budget):
                yield batch
                batch, current_bytes, estimated_output_tokens = [], 0, 0
            batch.append(row)
            current_bytes += length
            estimated_output_tokens += output_estimate
        if batch:
            yield batch

    async def verify(self, rows, records, sample_count: int) -> list[dict]:
        timer = time.monotonic()
        by_id = {record["review_id"]: record for record in records}
        eligible = [{key: row[key] for key in SOURCE_FIELDS} for row in rows if row["review_text"].strip()]
        seed = self.config.get("verification_seed", "spotify-independent-verification-v1")
        eligible.sort(key=lambda row: hashlib.sha256(f"{seed}:{row['review_id']}".encode()).digest())
        selected = eligible[:max(0, sample_count)]
        results, disagreements = [], []
        for batch in self._batches(selected):
            try:
                response = await self._openai_batch(batch, "verify")
                for prediction in response["reviews"]:
                    source = by_id.get(prediction["review_id"], {"status": "missing"})
                    if source.get("status") == "completed":
                        differences = {key: {"enrich": source[key], "verify": prediction[key]}
                                       for key in ("topic", "intent", "severity") if source[key] != prediction[key]}
                        sentiment_error = abs(source["sentiment"] - prediction["sentiment"])
                    else:
                        differences = {"enrichment_status": {"enrich": source.get("status"), "verify": "completed"}}
                        sentiment_error = None
                    entry = {"review_id": prediction["review_id"], "label_config": self.label_config, "status": "completed",
                             "prediction": prediction, "differences": differences, "sentiment_absolute_difference": sentiment_error,
                             "sampling_method": "seeded_sha256_without_replacement", "seed": seed, "blind": True}
                    results.append(entry)
                    if differences or (sentiment_error is not None and sentiment_error > .25):
                        disagreements.append(entry)
            except BudgetExceeded as exc:
                self.limitations.append(f"Verification stopped: {exc}")
                break
            except AuthenticationProviderError:
                raise
            except Exception as exc:
                for row in batch:
                    results.append({"review_id": row["review_id"], "status": "failed", "reason": str(exc), "blind": True})
        self._verification = results
        atomic_jsonl(self.run_dir / "verification.jsonl", results)
        atomic_jsonl(self.run_dir / "disagreements.jsonl", disagreements)
        self.stages["verify"] = {"requested_sample_count": sample_count, "selected": len(selected),
                                 "completed": sum(row["status"] == "completed" for row in results),
                                 "failed": sum(row["status"] == "failed" for row in results),
                                 "unprocessed": len(selected) - len(results), "disagreements": len(disagreements),
                                 "wall_seconds": time.monotonic() - timer, "blind": True}
        self.finish()
        return results

    async def model_task(self, role: str, payload: dict, schema: dict, review_ids: list[str] | None = None,
                         *, _purpose: str | None = None, _validator: Callable | None = None) -> dict:
        if role not in {"enrich", "verify", "group", "memo"}:
            raise ValueError("Invalid model role")
        purpose = _purpose or role
        if purpose == "enrich":
            purpose = "fallback"
        ids = list(review_ids or [])
        model_key = "fallback" if purpose == "fallback" else role
        model = self.config["models"][model_key]
        effort = self.config.get("reasoning_effort", {}).get(model_key, "none")
        prompt = self._prompt(purpose)
        cache_key = hashlib.sha256(canonical({"config": self.label_config, "role": role, "purpose": purpose,
                                             "prompt": prompt, "payload": payload, "schema": schema,
                                             "model": model, "effort": effort, "ids": ids}).encode()).hexdigest()
        cached = self.store.task(cache_key)
        if cached:
            validate_schema(cached["value"], schema)
            if _validator:
                _validator(cached["value"])
            self.task_cache_hits += 1
            self._task_source_request_ids.add(cached["request_id"])
            atomic_json(self.handoffs / f"task-{cache_key}.json", {"role": role, "purpose": purpose,
                        "cache_hit": True, "source_request_id": cached["request_id"], "input": payload, "output": cached["value"]})
            return cached["value"]
        provider = self._provider("openai")
        kwargs = {"model": model, "prompt": prompt, "payload": payload, "schema": schema,
                  "reasoning_effort": effort, "max_output_tokens": self.config.get("max_output_tokens", 6000),
                  "schema_name": "spotify_" + purpose}
        request = provider.build_request(**kwargs)
        def validate(value):
            validate_schema(value, schema)
            if _validator:
                _validator(value)
        result = await self._invoke(provider="openai", role=role, purpose=purpose, model=model,
                                    review_ids=ids, request=request, dispatch=lambda: provider.structured(**kwargs),
                                    validator=validate, effort=effort)
        self.store.save_task(cache_key, role, result, self._last_request_id)
        self._task_source_request_ids.add(self._last_request_id)
        atomic_json(self.handoffs / f"task-{cache_key}.json", {"role": role, "purpose": purpose, "cache_hit": False,
                    "source_request_id": self._last_request_id, "input": payload, "output": result})
        return result

    def _export_calls(self):
        atomic_jsonl(self.run_dir / "calls.jsonl", self.store.calls(self.run_id))

    def summary(self) -> dict:
        calls = self.store.calls(self.run_id)
        totals = self.ledger.totals(self.run_id)
        return {"run_id": self.run_id, "label_config": self.label_config, "input_count": len(self.rows),
                "completed": sum(row["status"] == "completed" for row in self.records),
                "quarantined": sum(row["status"] == "quarantined" for row in self.records),
                "pending": sum(row["status"] == "pending" for row in self.records),
                "unique_texts": len({row["review_text"] for row in self.rows if row["review_text"].strip()}),
                "cache_hits": self.cache_hits, "task_cache_hits": self.task_cache_hits,
                "requests": len(calls), "attempts": len(calls), "failed_attempts": sum(call["outcome"] == "failed" for call in calls),
                "api_cost_usd": totals["spent_usd"], "api_cost_complete": not bool(totals["unknown_charge_hold_usd"] or totals["reserved_usd"]),
                "spending": totals, "global_spending": self.ledger.totals(), "budget_usd": self.budget_usd,
                "global_budget_usd": self.config.get("global_budget_usd", 18),
                "wall_seconds": time.monotonic() - self.started, "phase": self.phase,
                "model_settings": {"models": self.config["models"], "reasoning_effort": self.config.get("reasoning_effort", {})},
                "stages": self.stages, "limitations": list(dict.fromkeys(self.limitations))}

    def finish(self) -> dict:
        self._export_calls()
        ids = {row["review_id"] for row in self.rows}
        historic = [call for call in self.store.calls() if call["label_config"] == self.label_config and
                    (call["run_id"] == self.run_id or call["request_id"] in self._task_source_request_ids or
                     (call["role"] == "enrich" and set(call["review_ids"]) & ids))]
        atomic_jsonl(self.run_dir / "evidence_calls.jsonl", historic)
        summary = self.summary()
        atomic_json(self.run_dir / "run_summary.json", summary)
        return summary

    async def close(self):
        if self._closed:
            return
        for provider in self.providers.values():
            close = getattr(provider, "close", None) or getattr(provider, "aclose", None)
            if close:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        self.store.close()
        self.ledger.close()
        self._closed = True
