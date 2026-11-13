"""Provider presets. Every preset still spends only the key the user supplies."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from eat_tokens.errors import ConfigError

# Placeholder strings shipped in .env.example. Never a real credential.
PLACEHOLDER_KEYS = frozenset(
    {
        "your-own-key-here",
        "sk-your-own-key-here",
        "replace-me",
        "changeme",
    }
)

DEFAULT_MAX_TOKENS = 256
DEFAULT_BUDGET_USD = 0.01
DEFAULT_MAX_CALLS = 20
DEFAULT_COMPLETION_TOKENS = 16
DEFAULT_TIMEOUT_SECONDS = 45

# Sanity ceilings. The default is small; these only stop typos and "unlimited".
MAX_TOKEN_CAP = 1_000_000
MAX_BUDGET_USD = 25.0
MAX_CALLS = 500
MAX_COMPLETION_TOKENS = 256
MAX_USD_PER_MILLION = 1_000.0
MIN_API_KEY_LENGTH = 8

PROMPT = "只回答一个字：吃"
PROMPT_ESTIMATE_OVERHEAD = 16


def estimate_prompt_tokens(text: str) -> int:
    """Over-estimate prompt tokens so the loop stops a bite early.

    One token per character is high for English and close to typical
    Chinese tokenization, plus a fixed framing overhead.
    """

    return len(text) + PROMPT_ESTIMATE_OVERHEAD


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    protocol: str  # "openai" or "anthropic"
    base_url: str
    model: str
    env_vars: tuple[str, ...]
    input_usd_per_million: float
    output_usd_per_million: float
    # True when this preset talks to a host that bills hidden reasoning
    # unless we explicitly turn thinking off. The actual request flag is
    # decided from the resolved host, not from this hint.
    prefers_thinking_disabled: bool = False


@dataclass(frozen=True)
class ResolvedProvider:
    id: str
    protocol: str
    base_url: str
    endpoint_url: str
    model: str
    env_vars: tuple[str, ...]
    input_usd_per_million: float
    output_usd_per_million: float
    disable_thinking: bool


# Prices are local brakes, not invoices. DeepSeek's pair is the published
# peak cache-miss rate (the expensive end of that card). The others are
# deliberate local estimates so the USD cap trips early; override them.
PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        id="deepseek",
        protocol="openai",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        env_vars=("DEEPSEEK_API_KEY",),
        input_usd_per_million=0.30,
        output_usd_per_million=1.20,
        prefers_thinking_disabled=True,
    ),
    "openai": ProviderSpec(
        id="openai",
        protocol="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        env_vars=("OPENAI_API_KEY",),
        input_usd_per_million=0.40,
        output_usd_per_million=1.60,
    ),
    "codex": ProviderSpec(
        id="codex",
        protocol="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-5.1-codex",
        env_vars=("CODEX_API_KEY", "OPENAI_API_KEY"),
        input_usd_per_million=1.50,
        output_usd_per_million=6.00,
    ),
    "grok": ProviderSpec(
        id="grok",
        protocol="openai",
        base_url="https://api.x.ai/v1",
        model="grok-4.7",
        env_vars=("XAI_API_KEY",),
        input_usd_per_million=5.00,
        output_usd_per_million=15.00,
    ),
    "anthropic": ProviderSpec(
        id="anthropic",
        protocol="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-haiku-4-5",
        env_vars=("ANTHROPIC_API_KEY",),
        input_usd_per_million=1.00,
        output_usd_per_million=5.00,
    ),
    "compatible": ProviderSpec(
        id="compatible",
        protocol="openai",
        base_url="",
        model="",
        env_vars=(),
        input_usd_per_million=5.00,
        output_usd_per_million=15.00,
    ),
}

ALIASES = {
    "xai": "grok",
    "claude": "anthropic",
    "custom": "compatible",
    "openai-compatible": "compatible",
    "openai_compatible": "compatible",
}


def canonical_provider_id(name: str) -> str:
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    if key not in PROVIDERS:
        known = ", ".join(list(PROVIDERS) + sorted(set(ALIASES)))
        raise ConfigError(
            f"不认识的服务商 {name!r}。可选：{known}\n"
            f"Unknown provider {name!r}. Choose one of: {known}"
        )
    return key


def validate_base_url(url: str) -> str:
    """Accept only the URL the user can read back in the warning."""

    candidate = url.strip()
    if not candidate or any(ch.isspace() for ch in candidate) or "\\" in candidate:
        raise ConfigError(
            "base URL 不合法。\nThe base URL is invalid."
        )
    if len(candidate) > 2048:
        raise ConfigError(
            "base URL 太长。\nThe base URL is too long."
        )
    parsed = urlparse(candidate)
    host = parsed.hostname
    if parsed.scheme not in {"https", "http"} or not host:
        raise ConfigError(
            "base URL 只能是 http 或 https，而且必须有主机名。\n"
            "The base URL must be http or https and must include a host."
        )
    if parsed.username or parsed.password:
        raise ConfigError(
            "base URL 里不能带账号或密码。密钥只走请求头。\n"
            "The base URL must not contain credentials. The key goes in a header."
        )
    if parsed.scheme == "http" and host.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigError(
            "公网地址必须用 https。只有本机 http 可以用来打你自己的兼容服务。\n"
            "Public base URLs must be https. Plain http is only allowed for localhost."
        )
    return candidate.rstrip("/")


def _host_is_deepseek(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host == "api.deepseek.com" or host.endswith(".deepseek.com")


def endpoint_url(protocol: str, base_url: str) -> str:
    base = base_url.rstrip("/")
    if protocol == "anthropic":
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _positive_price(value: float, flag: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{flag} 必须是正数。\n{flag} must be a positive number.")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")} or number <= 0:
        raise ConfigError(
            f"{flag} 必须是有限的正数，不能是 0 或无限。\n"
            f"{flag} must be a finite number greater than zero."
        )
    if number > MAX_USD_PER_MILLION:
        raise ConfigError(
            f"{flag} 大得不像单价。\n{flag} is unreasonably large."
        )
    return number


def resolve_provider(
    name: str,
    base_url: str | None,
    model: str | None,
    input_usd_per_million: float | None,
    output_usd_per_million: float | None,
) -> ResolvedProvider:
    spec = PROVIDERS[canonical_provider_id(name)]
    chosen_base = base_url if base_url else spec.base_url
    chosen_model = model.strip() if model else spec.model
    if not chosen_base or not chosen_model:
        raise ConfigError(
            "这个服务商没有默认地址或默认模型。请同时传入 --base-url 和 --model。\n"
            "This provider has no default URL or model. Pass both --base-url and --model."
        )
    if len(chosen_model) > 200 or any(ch.isspace() for ch in chosen_model):
        raise ConfigError(
            "模型名不合法。\nThe model name is invalid."
        )
    clean_base = validate_base_url(chosen_base)
    protocol = spec.protocol
    return ResolvedProvider(
        id=spec.id,
        protocol=protocol,
        base_url=clean_base,
        endpoint_url=endpoint_url(protocol, clean_base),
        model=chosen_model,
        env_vars=spec.env_vars,
        input_usd_per_million=_positive_price(
            spec.input_usd_per_million if input_usd_per_million is None else input_usd_per_million,
            "--input-usd-per-million",
        ),
        output_usd_per_million=_positive_price(
            spec.output_usd_per_million if output_usd_per_million is None else output_usd_per_million,
            "--output-usd-per-million",
        ),
        disable_thinking=_host_is_deepseek(clean_base),
    )


def validate_api_key(key: str) -> str:
    cleaned = key.strip()
    if any(ch in cleaned for ch in "\r\n\x00"):
        raise ConfigError(
            "密钥里不能有换行。\nThe API key must be a single line."
        )
    if cleaned in PLACEHOLDER_KEYS or cleaned.lower() in PLACEHOLDER_KEYS:
        raise ConfigError(
            "这是仓库里的占位符，不是密钥。请换成你自己的密钥。\n"
            "That is the placeholder from the repo, not a key. Put your own key in."
        )
    if len(cleaned) < MIN_API_KEY_LENGTH or len(cleaned) > 4096:
        raise ConfigError(
            "密钥长度不像一个真的 API key。\nThe API key length does not look usable."
        )
    return cleaned


def resolve_api_key(provider: ResolvedProvider, flag_key: str | None) -> tuple[str, str]:
    """Return (key, source label). Never returns a key we did not name."""

    if flag_key is not None and flag_key.strip():
        return validate_api_key(flag_key), "--api-key"
    generic = os.environ.get("EAT_TOKENS_API_KEY", "")
    if generic.strip():
        return validate_api_key(generic), "EAT_TOKENS_API_KEY"
    for env_name in provider.env_vars:
        value = os.environ.get(env_name, "")
        if value.strip():
            return validate_api_key(value), env_name
    expected = ", ".join(provider.env_vars) if provider.env_vars else "(none)"
    raise ConfigError(
        "没有找到你自己的密钥，所以不会调用 API。\n"
        "No API key was found, so no API call will be made.\n"
        "传入 --api-key，或设置 EAT_TOKENS_API_KEY"
        + (f"，或设置 {expected}。" if provider.env_vars else "。")
        + "\nPass --api-key, or set EAT_TOKENS_API_KEY"
        + (f", or set {expected}." if provider.env_vars else ".")
    )


def catalog_lines() -> list[str]:
    lines = []
    for spec in PROVIDERS.values():
        base = spec.base_url or "(required --base-url)"
        model = spec.model or "(required --model)"
        envs = ", ".join(spec.env_vars) if spec.env_vars else "EAT_TOKENS_API_KEY or --api-key"
        lines.append(
            f"{spec.id:<12} {spec.protocol:<10} {base}\n"
            f"             model={model}\n"
            f"             env={envs}"
        )
    return lines
