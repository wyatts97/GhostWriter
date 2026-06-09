"""OpenAI-compatible LLM client for chat completions with structured output."""

import json
import logging
from typing import Any

import httpx
from structlog import get_logger

logger = get_logger(__name__)


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

    Works with OpenAI, Anthropic (via /v1 proxy), Deepseek, Gemini,
    and any provider that exposes an OpenAI-compatible /v1/chat/completions endpoint.
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
        output_schema: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Generate a structured JSON response matching the provided schema.

        Uses the response_format parameter to request JSON mode.
        Returns the parsed JSON object.
        """
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        response = await self._request(payload)

        try:
            content = response["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.error("llm_structured_parse_failed", error=str(exc), response=response)
            raise LlmApiError(
                f"Failed to parse structured response: {exc}"
            ) from exc

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Make an HTTP request with retry logic."""
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()

        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)

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
                        import asyncio

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
                        import asyncio

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
                    import asyncio

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
                    import asyncio

                    await asyncio.sleep(wait)
                    continue
                raise LlmApiError(
                    f"LLM request failed after {self.max_retries} attempts: {exc}"
                ) from exc

        # Should not reach here, but just in case
        raise LlmApiError(f"LLM request failed after {self.max_retries} attempts")

    @staticmethod
    def count_tokens(text: str) -> int:
        """Rough token estimate (4 chars per token)."""
        return len(text) // 4
