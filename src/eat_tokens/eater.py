"""The useless eating loop. It stops on a cap, an error, or an interrupt."""

from __future__ import annotations

from dataclasses import dataclass

from eat_tokens.errors import ConfigError, ProviderError
from eat_tokens.providers import (
    MAX_BUDGET_USD,
    MAX_CALLS,
    MAX_COMPLETION_TOKENS,
    MAX_TOKEN_CAP,
)

CAP_REASONS = frozenset({"token_cap", "budget_cap", "call_cap"})

REASON_TEXT = {
    "token_cap": "达到 token 上限 / hit the token cap",
    "budget_cap": "达到金额估计上限 / hit the estimated USD cap",
    "call_cap": "达到调用次数上限 / hit the call cap",
    "error": "出错后停止 / stopped on error",
    "interrupt": "你中断了 / interrupted",
}


def usd_to_micro(amount: float) -> int:
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ConfigError("金额必须是数字。\nThe amount must be a number.")
    number = float(amount)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ConfigError("金额必须是有限数字。\nThe amount must be finite.")
    return int(round(number * 1_000_000))


def format_usd(micro: int) -> str:
    sign = "-" if micro < 0 else ""
    micro = abs(int(micro))
    whole = micro // 1_000_000
    frac = micro % 1_000_000
    return f"{sign}${whole}.{frac:06d}"


def cost_micro(
    prompt_tokens: int,
    completion_tokens: int,
    input_micro_per_million: int,
    output_micro_per_million: int,
) -> int:
    """Integer micro-USD. price_micro_per_million is USD-per-1M-tokens * 1e6."""

    return (
        prompt_tokens * input_micro_per_million + completion_tokens * output_micro_per_million
    ) // 1_000_000


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class Limits:
    max_tokens: int
    budget_micro: int
    max_calls: int
    completion_tokens: int
    input_micro_per_million: int
    output_micro_per_million: int

    @property
    def budget_usd_label(self) -> str:
        return format_usd(self.budget_micro)


@dataclass
class RunState:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    spent_micro: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class Summary:
    calls: int
    prompt_tokens: int
    completion_tokens: int
    spent_micro: int
    reason: str
    detail: str

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def validate_limits(
    max_tokens: int,
    budget_usd: float,
    max_calls: int,
    completion_tokens: int,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> Limits:
    """Reject unlimited, zero, negative, and non-finite caps. A cap is mandatory."""

    def positive_int(value: int, label: str, ceiling: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{label} 必须是正整数。\n{label} must be a positive integer.")
        if value < 1 or value > ceiling:
            raise ConfigError(
                f"{label} 必须在 1 和 {ceiling} 之间。没有无限档。\n"
                f"{label} must be between 1 and {ceiling}. There is no unlimited setting."
            )
        return value

    tokens = positive_int(max_tokens, "--max-tokens", MAX_TOKEN_CAP)
    calls = positive_int(max_calls, "--max-calls", MAX_CALLS)
    completion = positive_int(completion_tokens, "--completion-tokens", MAX_COMPLETION_TOKENS)
    if isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float)):
        raise ConfigError("--budget-usd 必须是数字。\n--budget-usd must be a number.")
    budget = float(budget_usd)
    if budget != budget or budget in {float("inf"), float("-inf")} or budget <= 0 or budget > MAX_BUDGET_USD:
        raise ConfigError(
            f"--budget-usd 必须大于 0 且不超过 {MAX_BUDGET_USD:g}。没有无限档。\n"
            f"--budget-usd must be greater than 0 and at most {MAX_BUDGET_USD:g}. "
            "There is no unlimited setting."
        )
    budget_micro = usd_to_micro(budget)
    input_micro = usd_to_micro(input_usd_per_million)
    output_micro = usd_to_micro(output_usd_per_million)
    if budget_micro < 1 or input_micro < 1 or output_micro < 1:
        raise ConfigError(
            "金额小到按微美元四舍五入后变成 0。请给一个更大的正数。没有无限档。\n"
            "The amount rounds to zero micro-USD. Use a larger positive number. "
            "There is no unlimited setting."
        )
    return Limits(
        max_tokens=tokens,
        budget_micro=budget_micro,
        max_calls=calls,
        completion_tokens=completion,
        input_micro_per_million=input_micro,
        output_micro_per_million=output_micro,
    )


class DryRunClient:
    """Pretend to eat. No socket, no key, no bill."""

    def complete(self, max_completion_tokens: int) -> Usage:
        return Usage(prompt_tokens=24, completion_tokens=min(4, max_completion_tokens))


def _bite_size(state: RunState, limits: Limits, prompt_est: int) -> int | None:
    """How many completion tokens the next request may ask for, or None to stop."""

    token_room = limits.max_tokens - state.total_tokens - prompt_est
    if token_room < 1:
        return None
    size = min(limits.completion_tokens, token_room)
    while size >= 1:
        extra = cost_micro(
            prompt_est,
            size,
            limits.input_micro_per_million,
            limits.output_micro_per_million,
        )
        if state.spent_micro + extra <= limits.budget_micro:
            return size
        size -= 1
    return None


def _why_no_bite(state: RunState, limits: Limits, prompt_est: int) -> str:
    token_room = limits.max_tokens - state.total_tokens - prompt_est
    if token_room < 1:
        return "token_cap"
    return "budget_cap"


def _finish(state: RunState, reason: str, detail: str) -> Summary:
    return Summary(
        calls=state.calls,
        prompt_tokens=state.prompt_tokens,
        completion_tokens=state.completion_tokens,
        spent_micro=state.spent_micro,
        reason=reason,
        detail=detail,
    )


def eat(limits: Limits, client, prompt_est: int, before=None, after=None) -> Summary:
    """Call `client.complete` until a cap, an error, or Ctrl-C.

    The client is called in the foreground, on this thread, with no retry.
    """

    if prompt_est < 1:
        raise ConfigError("内部错误：prompt 估计无效。\nInternal error: bad prompt estimate.")
    state = RunState()
    while True:
        if state.calls >= limits.max_calls:
            return _finish(state, "call_cap", REASON_TEXT["call_cap"])
        if state.total_tokens >= limits.max_tokens:
            return _finish(state, "token_cap", REASON_TEXT["token_cap"])
        if state.spent_micro >= limits.budget_micro:
            return _finish(state, "budget_cap", REASON_TEXT["budget_cap"])
        size = _bite_size(state, limits, prompt_est)
        if size is None:
            reason = _why_no_bite(state, limits, prompt_est)
            return _finish(state, reason, REASON_TEXT[reason])
        try:
            if before is not None:
                before(state.calls + 1, size)
            usage = client.complete(size)
        except KeyboardInterrupt:
            return _finish(state, "interrupt", REASON_TEXT["interrupt"])
        except ProviderError as exc:
            state.calls += 1
            if exc.billed_unknown:
                state.prompt_tokens += prompt_est
                state.completion_tokens += size
                state.spent_micro += cost_micro(
                    prompt_est,
                    size,
                    limits.input_micro_per_million,
                    limits.output_micro_per_million,
                )
            return _finish(state, "error", str(exc) or REASON_TEXT["error"])
        except Exception:
            # Do not print the raw exception: it can contain request headers.
            return _finish(
                state,
                "error",
                "调用失败，已停止。没有重试。 / The call failed. Stopped. No retry.",
            )
        if not isinstance(usage, Usage):
            return _finish(state, "error", "内部错误：用量不是 Usage。 / Internal error: bad usage.")
        state.calls += 1
        state.prompt_tokens += usage.prompt_tokens
        state.completion_tokens += usage.completion_tokens
        state.spent_micro += cost_micro(
            usage.prompt_tokens,
            usage.completion_tokens,
            limits.input_micro_per_million,
            limits.output_micro_per_million,
        )
        try:
            if after is not None:
                after(state)
        except KeyboardInterrupt:
            return _finish(state, "interrupt", REASON_TEXT["interrupt"])
        if state.total_tokens >= limits.max_tokens:
            return _finish(state, "token_cap", REASON_TEXT["token_cap"])
        if state.spent_micro >= limits.budget_micro:
            return _finish(state, "budget_cap", REASON_TEXT["budget_cap"])
