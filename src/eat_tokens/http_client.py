"""One foreground HTTP call. No retries, no redirects, no proxy env, no logs of the key."""

from __future__ import annotations

import json
from urllib import error, request
from urllib.parse import quote, urlparse

from eat_tokens.errors import ConfigError, ProviderError
from eat_tokens.eater import Usage
from eat_tokens.providers import MAX_COMPLETION_TOKENS, PROMPT, ResolvedProvider

USER_AGENT = "i-want-to-eat-tokens/0.1 (joke; foreground; no-retry)"
ANTHROPIC_VERSION = "2023-06-01"
MAX_RESPONSE_BYTES = 1_000_000
MAX_ERROR_BYTES = 500
MAX_USAGE_NUMBER = 1_000_000_000


class NoRedirect(request.HTTPRedirectHandler):
    """A redirect would send the key to a host the user did not confirm."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError(f"服务商返回了重定向 ({code})，已拒绝跟随。 / Refusing HTTP redirect ({code}).")


class _NoFile(request.FileHandler):
    def file_open(self, req):
        raise ProviderError("拒绝 file URL。 / Refusing a file URL.")


class _NoFTP(request.FTPHandler):
    def ftp_open(self, req):
        raise ProviderError("拒绝 ftp URL。 / Refusing an ftp URL.")


class _NoData(request.DataHandler):
    def data_open(self, req):
        raise ProviderError("拒绝 data URL。 / Refusing a data URL.")


def make_opener() -> request.OpenerDirector:
    """Direct HTTPS/HTTP only.

    Passing ProxyHandler({}) suppresses urllib's default proxy handler,
    which would honor HTTP_PROXY / HTTPS_PROXY. An empty ProxyHandler
    defines no protocol methods, so CPython then drops it. Nothing in
    this opener reads those variables. File, ftp, and data handlers are
    replaced so a bad URL cannot touch the local disk.
    """

    return request.build_opener(
        request.ProxyHandler({}),
        NoRedirect(),
        _NoFile(),
        _NoFTP(),
        _NoData(),
    )


def redact(text: str, secret: str | None) -> str:
    if not secret or not text:
        return text
    redacted = text.replace(secret, "[redacted]")
    encoded = quote(secret, safe="")
    if encoded and encoded != secret:
        redacted = redacted.replace(encoded, "[redacted]")
    return redacted


def _token_count(value, label: str) -> int:
    if isinstance(value, bool):
        raise ProviderError(f"{label} 不是整数。 / {label} is not an integer.", billed_unknown=True)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise ProviderError(f"{label} 不是整数。 / {label} is not an integer.", billed_unknown=True)
    if value < 0 or value > MAX_USAGE_NUMBER:
        raise ProviderError(f"{label} 无法采用。 / {label} is unusable.", billed_unknown=True)
    return value


def usage_from_payload(payload: object) -> Usage:
    """Read token counts and drop every other field, including model text."""

    if not isinstance(payload, dict):
        raise ProviderError(
            "响应不是 JSON 对象。已停止。 / Response was not a JSON object. Stopped.",
            billed_unknown=True,
        )
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ProviderError(
            "响应里没有 usage。已停止，避免在不知道花了多少的情况下继续。 / "
            "Response had no usage object. Stopped instead of continuing blind.",
            billed_unknown=True,
        )
    if "prompt_tokens" in usage:
        prompt = _token_count(usage.get("prompt_tokens"), "prompt_tokens")
    elif "input_tokens" in usage:
        prompt = _token_count(usage.get("input_tokens"), "input_tokens")
    else:
        raise ProviderError(
            "usage 里没有输入 token。已停止。 / usage had no input token count. Stopped.",
            billed_unknown=True,
        )
    if "completion_tokens" in usage:
        completion = _token_count(usage.get("completion_tokens"), "completion_tokens")
    elif "output_tokens" in usage:
        completion = _token_count(usage.get("output_tokens"), "output_tokens")
    else:
        raise ProviderError(
            "usage 里没有输出 token。已停止。 / usage had no output token count. Stopped.",
            billed_unknown=True,
        )
    if "total_tokens" in usage:
        reported = _token_count(usage.get("total_tokens"), "total_tokens")
        if reported > prompt + completion:
            # Keep the larger bill. The extra is treated as output.
            completion = reported - prompt
    return Usage(prompt_tokens=prompt, completion_tokens=completion)


def build_request(
    provider: ResolvedProvider,
    api_key: str,
    max_completion_tokens: int,
) -> request.Request:
    if not 1 <= max_completion_tokens <= MAX_COMPLETION_TOKENS:
        raise ConfigError(
            "单次输出 token 超出安全范围。\nPer-call completion tokens are outside the safety range."
        )
    if api_key and api_key in provider.endpoint_url:
        raise ConfigError(
            "密钥出现在 URL 里，已拒绝。\nRefusing to put the API key in the URL."
        )
    if provider.protocol == "anthropic":
        body = {
            "model": provider.model,
            "max_tokens": max_completion_tokens,
            "messages": [{"role": "user", "content": PROMPT}],
        }
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": USER_AGENT,
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
    else:
        body = {
            "model": provider.model,
            "messages": [{"role": "user", "content": PROMPT}],
            "stream": False,
        }
        host = (urlparse(provider.base_url).hostname or "").lower()
        # Presets named openai/codex always speak the newer token field.
        # A custom preset does too when the host really is OpenAI, not a
        # lookalike domain that merely contains the letters.
        openai_family = provider.id in {"openai", "codex"} or host == "api.openai.com" or host.endswith(".openai.com")
        if openai_family:
            # Newer OpenAI models bill against max_completion_tokens.
            body["max_completion_tokens"] = max_completion_tokens
        else:
            body["max_tokens"] = max_completion_tokens
        if provider.disable_thinking:
            # DeepSeek thinks by default, and thinking can ignore a tiny
            # max_tokens budget. Force it off so one bite stays small.
            body["thinking"] = {"type": "disabled"}
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": USER_AGENT,
            "authorization": "Bearer " + api_key,
        }
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return request.Request(
        provider.endpoint_url,
        data=raw,
        headers=headers,
        method="POST",
    )


def _read_capped(response, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ProviderError(
            "响应太大，已丢弃并停止。 / Response was too large. Discarded and stopped.",
            billed_unknown=True,
        )
    return data


def parse_success_body(raw: bytes) -> Usage:
    if raw.lstrip().startswith(b"data:"):
        raise ProviderError(
            "服务商返回了流式输出。本工具不读取、不打印流，并立刻停止。 / "
            "Provider returned a stream. This tool does not read or print it, and stops.",
            billed_unknown=True,
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(
            "响应不是 JSON。已停止。 / Response was not JSON. Stopped.",
            billed_unknown=True,
        ) from None
    return usage_from_payload(payload)


class HttpClient:
    """Sends the key only to the endpoint the user just confirmed."""

    def __init__(self, provider: ResolvedProvider, api_key: str, timeout: float, opener=None) -> None:
        self.provider = provider
        self.api_key = api_key
        self.timeout = timeout
        self.opener = opener if opener is not None else make_opener()

    def complete(self, max_completion_tokens: int) -> Usage:
        req = build_request(self.provider, self.api_key, max_completion_tokens)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = _read_capped(response, MAX_RESPONSE_BYTES)
        except ProviderError:
            raise
        except error.HTTPError as exc:
            snippet = b""
            try:
                snippet = exc.read(MAX_ERROR_BYTES)
            except Exception:
                snippet = b""
            text = redact(snippet.decode("utf-8", errors="replace"), self.api_key)
            text = " ".join(text.split())
            raise ProviderError(f"HTTP {exc.code}: {text[:300]}".rstrip()) from None
        except error.URLError:
            raise ProviderError(
                "连不上你配置的地址。已停止，没有重试。 / "
                "Could not connect to the URL you configured. Stopped, no retry."
            ) from None
        except TimeoutError:
            raise ProviderError(
                "请求超时。已停止，没有重试。 / The request timed out. Stopped, no retry."
            ) from None
        return parse_success_body(raw)
