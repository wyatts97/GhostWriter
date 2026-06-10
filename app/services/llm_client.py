"""OpenAI-compatible LLM client for chat completions with structured output.

Uses a shared httpx.AsyncClient for connection pooling across all requests.
"""

import asyncio
import json
import re
from typing import Any

import httpx
from structlog import get_logger

logger = get_logger(__name__)


def _try_fix_json(content: str) -> dict | None:
    """Attempt to parse JSON from an LLM response using several strategies.

    1. Direct ``json.loads``
    2. Extract from ```json … ``` code fences
    3. Extract outermost ``{ … }`` block
    4. Try to repair common issues (unescaped quotes inside strings)
    """
    # ── 1. Direct ──────────────────────────────────────────────────────
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # ── 2. Code-fenced JSON block ──────────────────────────────────────
    m = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL
    )
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # ── 3. Outermost { … } block ───────────────────────────────────────
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        block = content[brace_start : brace_end + 1]
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            pass

    # ── 4. Heuristic repair — unescaped quotes inside strings ─────────
    #    Strategy: find key-value pairs where the value is a string that
    #    contains an unescaped dq, and escape them.
    _repaired = _heuristic_json_repair(content)
    if _repaired is not None:
        return _repaired

    return None


def _heuristic_json_repair(content: str) -> dict | None:
    """Try to fix common JSON issues — mainly unescaped ``\"`` inside strings."""
    # Only work on the outermost { … } block
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start == -1 or brace_end <= brace_start:
        return None
    block = content[brace_start : brace_end + 1]

    # Escape bare double-quotes that appear *inside* a string value but are
    # NOT already escaped.  This is a best-effort heuristic.
    #
    # Walk character by character tracking string-context.  When we find a
    # double-quote inside a string that isn't preceded by a backslash, escape it.
    chars = list(block)
    n = len(chars)
    in_string = False
    prev_was_escape = False
    fixed = False
    i = 0
    while i < n:
        c = chars[i]
        if c == "\\" and in_string:
            prev_was_escape = not prev_was_escape
            i += 1
            continue
        if c == '"':
            if not in_string:
                in_string = True
                prev_was_escape = False
            elif not prev_was_escape:
                # This dq *ends* the string — but if the next non-whitespace
                # char is not a structural char (,:}]) it's likely an unescaped
                # quote *inside* the value.  Escape it.
                # Peek forward
                j = i + 1
                while j < n and chars[j] in " \t\r\n":
                    j += 1
                if j < n and chars[j] not in (",", ":", "}", "]"):
                    chars.insert(i, "\\")
                    n += 1
                    fixed = True
                    prev_was_escape = False
                    i += 2
                    continue
                else:
                    in_string = False
            else:
                # escaped quote inside string — fine
                prev_was_escape = False
            i += 1
            continue
        prev_was_escape = False
        i += 1

    if not fixed:
        return None

    try:
        return json.loads("".join(chars))
    except json.JSONDecodeError:
        return None


class LlmAuthError(Exception):
    """Raised when the LLM API returns a 401 or 403."""


class LlmRateLimitError(Exception):
    """Raised when the LLM API returns a 429."""


class LlmTimeoutError(Exception):
    """Raised when the LLM API request times out."""


class LlmApiError(Exception):
    """Raised for other LLM API errors."""


class LlmClient:
    """Async client for OpenAI-compatible chat completion APIs.

    Maintains a single httpx.AsyncClient for connection reuse.
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        default_model: str = "gpt-4o",
        timeout: float = 120.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Send a chat completion request and return the full response dict."""
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        return await self._request(payload)

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        output_schema: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Generate a structured JSON response matching the provided schema.

        Uses ``response_format: {"type": "json_object"}`` to request JSON mode.
        If parsing fails on the first attempt, sends a correction message to the
        LLM and retries once.  Also applies several heuristic JSON-recovery
        strategies before giving up.
        """
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        for attempt in range(2):
            response = await self._request(payload)

            try:
                content = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as exc:
                raise LlmApiError(
                    f"LLM response missing content: {exc}"
                ) from exc

            # Try direct parse first, then heuristic recovery
            result = _try_fix_json(content)
            if result is not None:
                return result

            if attempt == 0:
                # Send a correction prompt and retry
                logger.warning(
                    "llm_structured_retry",
                    scheme=output_schema.get("schema", {}).keys() if output_schema else None,
                )
                messages = list(messages)
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your response was not valid JSON.  "
                        "Make sure ALL string values are properly escaped: "
                        "double-quotes inside strings must be backslash-escaped, "
                        "newlines must be \\n, and no trailing commas.  "
                        "Return valid JSON only — no prose before or after."
                    ),
                })
                payload["messages"] = messages
                continue

            raise LlmApiError(
                f"Failed to parse structured response after {attempt + 1} attempt(s). "
                f"Raw response preview: {content[:500]}"
            )

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Make an HTTP request with retry logic and exponential backoff."""
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()

        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage", {})
                    logger.info(
                        "llm_request_success",
                        model=payload.get("model"),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        attempt=attempt,
                    )
                    return data

                if response.status_code == 401 or response.status_code == 403:
                    raise LlmAuthError(
                        f"LLM API authentication failed ({response.status_code}): {response.text}"
                    )
                if response.status_code == 429:
                    if attempt < self.max_retries:
                        wait = 2 ** attempt * 2
                        logger.warning(
                            "llm_rate_limited",
                            attempt=attempt,
                            retry_in_seconds=wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise LlmRateLimitError(
                        f"LLM API rate limited after {self.max_retries} retries"
                    )
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        wait = 2 ** attempt
                        logger.warning(
                            "llm_server_error",
                            status=response.status_code,
                            attempt=attempt,
                            retry_in_seconds=wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise LlmApiError(
                        f"LLM API server error ({response.status_code}): {response.text}"
                    )

                raise LlmApiError(
                    f"LLM API unexpected error ({response.status_code}): {response.text}"
                )

            except httpx.TimeoutException as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "llm_timeout", attempt=attempt, retry_in_seconds=wait
                    )
                    await asyncio.sleep(wait)
                    continue
                raise LlmTimeoutError(
                    f"LLM API timed out after {self.max_retries} attempts"
                ) from exc

            except (LlmAuthError, LlmRateLimitError, LlmApiError):
                raise

            except Exception as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "llm_request_failed",
                        attempt=attempt,
                        retry_in_seconds=wait,
                        error=str(exc),
                    )
                    await asyncio.sleep(wait)
                    continue

                raise LlmApiError(
                    f"LLM API request failed after {self.max_retries} attempts"
                ) from last_exception

        raise LlmApiError(
            f"LLM API request failed after {self.max_retries} attempts"
        ) from last_exception
