"""Explicit OpenAI-compatible transport; no automatic tool execution or retries."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.config import Settings

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class AnalystAPIError(RuntimeError):
    """Sanitized API failure, never including headers, credentials or request payload."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials to another endpoint, or follow an unapproved destination.
        return None


@dataclass(frozen=True)
class Completion:
    model: str
    message: dict
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str


def _http_post(url: str, payload: dict, key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SeoulBeautyPrice/0.1",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AnalystAPIError("Analysis response exceeded size limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise AnalystAPIError("Analysis API returned a non-object response")
            return result
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise AnalystAPIError(f"Analysis API HTTP {code}; no retry performed") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AnalystAPIError("Analysis API connection failed; no retry performed") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AnalystAPIError("Analysis API returned invalid JSON") from None


class AnalystClient:
    def __init__(self, settings: Settings, *, transport: Callable | None = None):
        if settings.analyst_provider != "openai_compatible":
            raise ValueError("This transport requires PIPELINE_ANALYST_PROVIDER=openai_compatible")
        if not settings.analyst_base_url or not settings.analyst_api_key:
            raise ValueError("Analysis endpoint and ANALYST_API_KEY must be configured")
        if not settings.model_analyst:
            raise ValueError("MODEL_ANALYST is required")
        self.settings = settings
        self._transport = transport or _http_post

    def complete(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        max_output_tokens: int = 1024,
        timeout: float = 90,
    ) -> Completion:
        if not messages or not 1 <= max_output_tokens <= 8192:
            raise ValueError("Messages and an output token limit between 1 and 8192 are required")
        if not 0 < timeout <= self.settings.analyst_timeout_seconds:
            raise ValueError("Request timeout exceeds configured analysis wall-clock budget")
        payload = {
            "model": self.settings.model_analyst,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "stream": False,
        }
        if tools:
            # Declarations only. Returned calls are data; execution belongs to the M6 loop.
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        raw = self._transport(
            self.settings.analyst_base_url + "/chat/completions",
            payload,
            self.settings.analyst_api_key.get_secret_value(),
            timeout,
        )
        try:
            choice = raw["choices"][0]
            message = choice["message"]
            usage = raw["usage"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError
            tokens = [usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
            if any(type(t) is not int or t < 0 for t in tokens):
                raise ValueError
            if tokens[2] < tokens[0] + tokens[1]:
                raise ValueError
            if tokens[2] > self.settings.analyst_token_limit:
                raise AnalystAPIError("Analysis response exceeded the configured token budget")
            return Completion(
                model=raw.get("model", self.settings.model_analyst),
                message=message,
                prompt_tokens=tokens[0],
                completion_tokens=tokens[1],
                total_tokens=tokens[2],
                finish_reason=choice.get("finish_reason", "unknown"),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise AnalystAPIError(
                "Analysis response missing valid message or token usage"
            ) from None


def check_connection(settings: Settings) -> dict:
    response = AnalystClient(settings).complete(
        [{"role": "user", "content": 'Reply with exactly {"ok":true}. Do not call any tools.'}],
        max_output_tokens=256,
        timeout=90,
    )
    content = response.message.get("content")
    if response.finish_reason != "stop" or not isinstance(content, str):
        raise AnalystAPIError("Analysis connection check did not finish normally")
    try:
        verified = json.loads(content)
    except json.JSONDecodeError:
        raise AnalystAPIError(
            "Analysis connection check did not return the expected JSON"
        ) from None
    if verified != {"ok": True}:
        raise AnalystAPIError("Analysis connection check returned unexpected content")
    return {
        "ok": True,
        "provider": settings.analyst_provider,
        "model": response.model,
        "total_tokens": response.total_tokens,
    }
