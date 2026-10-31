"""
OpenAI-compatible LLM provider implementation.

Works with:
- OpenRouter (https://openrouter.ai/api/v1)
- Ollama (http://localhost:11434/v1 or http://host.docker.internal:11434/v1)
- Any OpenAI-compatible chat completions endpoint (/chat/completions)

Enforces strict JSON parsing, automatic one-time repair on malformed JSON,
and logs execution latency without leaking prompts or patient details.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel, ValidationError

from .base import LLMProvider
from ..errors import LLMResponseError, LLMUnavailable
from ..privacy import _assert_no_residual_regex_phi

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json_payload(raw_text: str) -> str:
    """
    Extracts JSON payload from model output, handling potential markdown fences
    or surrounding conversational commentary.
    """
    text = raw_text.strip()
    # Match markdown code block ```json ... ``` or ``` ... ```
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()

    # If no code block, try finding the first '{' or '[' and last '}' or ']'
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")

    # Check which starts first: object '{' or array '['
    starts_with_bracket = first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace)
    if starts_with_bracket and last_bracket != -1 and last_bracket > first_bracket:
        return text[first_bracket : last_bracket + 1].strip()

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1].strip()

    return text


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 90.0,
        provider_name: str = "openrouter",
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.provider_name = provider_name
        self.transport = transport

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PharmaGuard-PV/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.provider_name == "openrouter":
            headers["HTTP-Referer"] = "https://pharmaguard.local"
            headers["X-Title"] = "PharmaGuard Pharmacovigilance"
        return headers

    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        # Regex-only tripwire enforced on every outbound completion call (including repair retries)
        for msg in messages:
            if isinstance(msg, dict):
                _assert_no_residual_regex_phi(str(msg.get("content", "")))

        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            try:
                response = await client.post(url, headers=self._get_headers(), json=payload)
            except httpx.RequestError as exc:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
                logger.error(
                    "LLM HTTP connection error provider=%s model=%s elapsed_ms=%s error_type=%s",
                    self.provider_name,
                    self.model,
                    elapsed_ms,
                    type(exc).__name__,
                )
                raise LLMUnavailable(f"Unable to reach LLM endpoint: {type(exc).__name__}") from exc

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
        if response.status_code != 200:
            logger.error(
                "LLM HTTP error status=%d provider=%s model=%s elapsed_ms=%s",
                response.status_code,
                self.provider_name,
                self.model,
                elapsed_ms,
            )
            # Safe status description without leaking response body
            raise LLMResponseError(f"LLM API returned status code {response.status_code}")

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Response body is not a JSON object")
            choices = data.get("choices")
            if not isinstance(choices, list) or len(choices) == 0:
                raise ValueError("Response missing valid choices list")
            first_choice = choices[0]
            if not isinstance(first_choice, dict) or "message" not in first_choice:
                raise ValueError("Choice missing message object")
            message = first_choice["message"]
            if not isinstance(message, dict) or "content" not in message:
                raise ValueError("Message missing content")
            content = message["content"]
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            logger.info(
                "LLM completion succeeded provider=%s model=%s elapsed_ms=%s in_tokens=%d out_tokens=%d",
                self.provider_name,
                self.model,
                elapsed_ms,
                tokens_in,
                tokens_out,
            )
            return content or ""
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.error("LLM malformed response envelope error=%s", type(exc).__name__)
            raise LLMResponseError("LLM response did not contain expected choices array") from exc

    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[T],
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> T:
        """
        Requests JSON response, parses payload, validates with Pydantic.
        On validation or JSON syntax failure, executes one repair prompt retry.
        """
        # Append instruction to ensure JSON response
        system_json_hint = "You must respond with valid, parseable JSON only. Do not include markdown code blocks or explanations outside the JSON."
        augmented_messages = list(messages)
        if augmented_messages and augmented_messages[0].get("role") == "system":
            augmented_messages[0] = {
                "role": "system",
                "content": f"{augmented_messages[0]['content']}\n\n{system_json_hint}",
            }
        else:
            augmented_messages.insert(0, {"role": "system", "content": system_json_hint})

        raw_output = await self.complete(
            messages=augmented_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        extracted = extract_json_payload(raw_output)
        try:
            parsed = json.loads(extracted)
            if not isinstance(parsed, (dict, list)):
                raise ValueError("Parsed JSON is not an object or array")
            return schema.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as parse_err:
            logger.warning(
                "LLM structured output validation failed: %s. Initiating one repair retry.",
                type(parse_err).__name__,
            )

            # Repair prompt retry
            repair_messages = list(augmented_messages)
            repair_messages.append({"role": "assistant", "content": raw_output})
            repair_messages.append({
                "role": "user",
                "content": f"The previous output had error: {str(parse_err)[:200]}. Output strictly valid JSON conforming to the schema.",
            })

            retry_output = await self.complete(
                messages=repair_messages,
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            retry_extracted = extract_json_payload(retry_output)
            try:
                retry_parsed = json.loads(retry_extracted)
                if not isinstance(retry_parsed, (dict, list)):
                    raise ValueError("Parsed retry JSON is not an object or array")
                return schema.model_validate(retry_parsed)
            except Exception as final_err:
                logger.error("LLM repair attempt failed: %s", type(final_err).__name__)
                raise LLMResponseError("LLM output could not be parsed into valid structured schema") from final_err


class DisabledLLMProvider(LLMProvider):
    """Fallback provider when LLM is intentionally disabled or unconfigured."""

    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        raise LLMUnavailable("LLM provider is disabled or not configured")

    async def complete_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[T],
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> T:
        raise LLMUnavailable("LLM provider is disabled or not configured")
