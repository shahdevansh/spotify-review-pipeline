"""Nebius Token Factory single-attempt structured Chat Completions adapter.

Official wire and JSON-schema references, checked 2026-10-19:
https://docs.tokenfactory.nebius.com/quickstart
https://docs.tokenfactory.nebius.com/ai-models-inference/json
https://nebius.com/services/token-factory/models/qwen-models-inference
https://api.tokenfactory.nebius.com/openapi.json
https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16
https://huggingface.co/Qwen/Qwen3.8-27B
https://huggingface.co/zai-org/GLM-5.3-Flash

This module never spends credits on import or request construction. Usage is
provider-reported. Missing cache/reasoning detail is unknown, not a zero claim.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from .providers import (_HTTPProvider, _strict_json_loads, _token_count,
                        ProviderResponse, RefusedProviderResponse, ProviderPolicyError)

NEBIUS_ENDPOINT = "https://api.tokenfactory.nebius.com/v1/chat/completions"
# Only document-verified controls belong here. 'none' on the instruct model is
# architectural non-thinking; it is not an unsupported reasoning_effort flag.
NEBIUS_MODEL_CONTROLS = {
    "Qwen/Qwen3-30B-A3B-Instruct-2507": "instruct",
    "Qwen/Qwen3-235B-A22B-Instruct-2507": "instruct",
    "openai/gpt-oss-120b": "reasoning_effort",
    "nvidia/Nemotron-3_5-Lightning": "template_toggle",
    "Qwen/Qwen3.8-27B": "template_toggle",
    "zai-org/GLM-5.3-Flash": "glm_effort",
}


def validate_nebius_model_settings(model: str, effort: str = "none") -> None:
    if model not in NEBIUS_MODEL_CONTROLS:
        raise ValueError(f"Nebius model {model!r} has no verified request-control configuration")
    kind = NEBIUS_MODEL_CONTROLS[model]
    if kind == "instruct" and effort != "none":
        raise ValueError(f"{model} is a non-thinking instruct model; effort must be none")
    if kind == "reasoning_effort" and effort not in {"low", "medium", "high"}:
        raise ValueError(f"{model} supports low, medium or high reasoning; none is not supported")
    if kind == "template_toggle" and effort != "none":
        raise ValueError(f"{model} currently supports only the explicit thinking-off control in this adapter")
    if kind == "glm_effort" and effort not in {"low", "high"}:
        raise ValueError(f"{model}: use low or high; none/unknown can silently select maximum reasoning")


def normalize_nebius_usage(usage: dict | None) -> dict | None:
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise TypeError("Nebius usage must be an object or None")
    inputs = _token_count(usage.get("prompt_tokens"))
    outputs = _token_count(usage.get("completion_tokens"))
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    cached = _token_count(prompt_details.get("cached_tokens")) if isinstance(prompt_details, dict) else None
    reasoning = _token_count(completion_details.get("reasoning_tokens")) if isinstance(completion_details, dict) else None
    if inputs is not None and cached is not None and cached > inputs:
        raise ValueError("Nebius cached prompt tokens exceed total prompt tokens")
    if outputs is not None and reasoning is not None and reasoning > outputs:
        raise ValueError("Nebius reasoning tokens exceed completion tokens")
    return {"input_tokens": inputs, "output_tokens": outputs,
            "uncached_input_tokens": inputs - cached if inputs is not None and cached is not None else None,
            "cached_input_tokens": cached, "cache_write_tokens": None,
            "reasoning_tokens": reasoning}


class NebiusProvider(_HTTPProvider):
    env_name = "NEBIUS_API_KEY"
    endpoint = NEBIUS_ENDPOINT

    @staticmethod
    def build_request(model: str, prompt: str, payload: Any, schema: dict,
                      *, reasoning_effort: str = "none", max_output_tokens: int = 4096,
                      schema_name: str = "pipeline_output") -> dict:
        validate_nebius_model_settings(model, reasoning_effort)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be nonempty")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("Structured output schema must have an object root")
        if type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", schema_name):
            raise ValueError("schema_name must contain 1-64 letters, digits, _ or -")
        response_schema = copy.deepcopy(schema)
        schema_text = json.dumps(response_schema, ensure_ascii=False, allow_nan=False,
                                 sort_keys=True, separators=(",", ":"))
        # Nebius recommends making the schema visible in the text prompt as
        # well as response_format; the latter alone is insufficient for some
        # hosted reasoning models to infer the required output structure.
        system_prompt = (prompt + "\nReturn exactly one JSON object that satisfies the following JSON Schema. "
                         "Do not add Markdown, commentary, or text after the object.\nJSON Schema:\n" + schema_text)
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": response_schema}},
            "max_completion_tokens": max_output_tokens,
            "temperature": 0,
            "stream": False,
            "n": 1,
        }
        control = NEBIUS_MODEL_CONTROLS[model]
        if control in {"reasoning_effort", "glm_effort"}:
            body["reasoning_effort"] = reasoning_effort
        elif control == "template_toggle":
            body["chat_template_kwargs"] = {"enable_thinking": reasoning_effort != "none"}
        return body

    async def structured(self, model: str, prompt: str, payload: Any, schema: dict,
                         *, reasoning_effort: str = "none", max_output_tokens: int = 4096,
                         schema_name: str = "pipeline_output") -> ProviderResponse:
        request = self.build_request(model, prompt, payload, schema, reasoning_effort=reasoning_effort,
                                     max_output_tokens=max_output_tokens, schema_name=schema_name)
        raw, request_id = await self._post(request)
        actual_model = raw.get("model")
        if not isinstance(actual_model, str) or not actual_model:
            raise self._malformed("Nebius response is missing its model ID", raw, request_id)
        if actual_model != model:
            raise ProviderPolicyError("Nebius returned an undeclared model", status_code=200, raw=raw,
                                      usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else None,
                                      request_id=request_id)
        choices = raw.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise self._malformed("Expected exactly one Nebius completion choice", raw, request_id)
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise self._malformed("Nebius completion has no assistant message", raw, request_id)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else None
        if message.get("refusal"):
            raise RefusedProviderResponse("Nebius model refused the structured task", status_code=200,
                                          raw=raw, usage=usage, request_id=request_id)
        if choice.get("finish_reason") != "stop":
            raise self._malformed("Nebius completion stopped before a complete structured answer", raw, request_id)
        if message.get("tool_calls"):
            raise self._malformed("Nebius returned tool calls for a structured-only task", raw, request_id)
        text = message.get("content")
        if not isinstance(text, str):
            raise self._malformed("Nebius completion content is not a string", raw, request_id)
        try:
            data = _strict_json_loads(text)
        except (ValueError, TypeError):
            raise self._malformed("Nebius completion is not strict JSON", raw, request_id) from None
        if not isinstance(data, dict):
            raise self._malformed("Nebius structured output is not an object", raw, request_id)
        return ProviderResponse(data=data, raw=raw, usage=usage, model=actual_model,
                                request_id=request_id or (raw.get("id") if isinstance(raw.get("id"), str) else None))
