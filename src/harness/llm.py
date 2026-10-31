"""Thin wrapper around the OpenAI-compatible chat completions API.

Adds retry with exponential backoff for transient failures: rate limits
(429), server errors (5xx), and connection errors.
"""

from __future__ import annotations

import time

from openai import APIStatusError, APIConnectionError, OpenAI, RateLimitError


class LLM:
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "deepseek-v4-pro",
        temperature: float = 0.0,
        max_retries: int = 3,
        backoff: float = 5.0,
    ):
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is not set. Set it in your environment before running."
            )
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.backoff = backoff
        self.client = OpenAI(api_key=api_key, base_url=base_url or None)

    def complete(self, messages: list[dict]) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                return (response.choices[0].message.content or "").strip()
            except RateLimitError as exc:
                last_error = exc
            except APIConnectionError as exc:
                last_error = exc
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    last_error = exc
                else:
                    raise
            self._backoff(attempt, last_error)

        raise RuntimeError(
            f"LLM request failed after {self.max_retries} retries: {last_error}"
        ) from last_error

    def _backoff(self, attempt: int, error: Exception | None) -> None:
        delay = self.backoff * (2 ** attempt)
        if isinstance(error, RateLimitError):
            print(
                f"rate limited (429). retrying in {delay:.0f}s "
                f"(attempt {attempt + 1}/{self.max_retries})"
            )
        else:
            print(
                f"LLM request error: {error}. retrying in {delay:.0f}s "
                f"(attempt {attempt + 1}/{self.max_retries})"
            )
        time.sleep(delay)
