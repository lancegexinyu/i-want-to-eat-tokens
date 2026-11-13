"""Foreground joke CLI. It does not start itself, and it does not hide the bill."""

from __future__ import annotations

import argparse
import math
import os
import sys

from eat_tokens import __version__
from eat_tokens.eater import (
    CAP_REASONS,
    REASON_TEXT,
    DryRunClient,
    Summary,
    eat,
    format_usd,
    validate_limits,
)
from eat_tokens.errors import ConfigError
from eat_tokens.http_client import HttpClient, redact
from eat_tokens.providers import (
    DEFAULT_BUDGET_USD,
    DEFAULT_COMPLETION_TOKENS,
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    PROMPT,
    catalog_lines,
    estimate_prompt_tokens,
    resolve_api_key,
    resolve_provider,
)
from eat_tokens.statements import INTRO_LINES

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_INTERRUPTED = 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eat-tokens",
        description="\n".join(INTRO_LINES)
        + "\n\n默认不运行。加上 --yes，或在终端输入 YES，才会开始。\n"
        "It does not run by default. Pass --yes, or type YES in a terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="服务商 / providers:\n" + "\n".join(catalog_lines()),
    )
    parser.add_argument("--version", action="version", version=f"eat-tokens {__version__}")
    parser.add_argument(
        "--provider",
        default=None,
        help="deepseek (default), openai, codex, grok/xai, anthropic/claude, compatible/custom",
    )
    parser.add_argument("--base-url", default=None, help="override the provider base URL")
    parser.add_argument("--model", default=None, help="override the model name")
    parser.add_argument(
        "--api-key",
        default=None,
        help="your own key. Prefer an env var so it does not show up in the process list.",
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument(
        "--completion-tokens",
        type=int,
        default=DEFAULT_COMPLETION_TOKENS,
        help=f"max output tokens requested per call (1..256, default {DEFAULT_COMPLETION_TOKENS})",
    )
    parser.add_argument("--input-usd-per-million", type=float, default=None)
    parser.add_argument("--output-usd-per-million", type=float, default=None)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="I understand this spends my own money, does nothing useful, and pays nobody else.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="walk the same loop with fake usage. No network and no key.",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="print provider presets and exit. Does not spend.",
    )
    return parser


def _env_or_flag(flag_value: str | None, env_name: str) -> str | None:
    if flag_value is not None and str(flag_value).strip():
        return str(flag_value).strip()
    env_value = os.environ.get(env_name, "")
    if env_value.strip():
        return env_value.strip()
    return None


def render_warning(resolved, limits, key_source: str, dry_run: bool) -> str:
    price_in = format_usd(limits.input_micro_per_million)
    price_out = format_usd(limits.output_micro_per_million)
    lines = [
        "=" * 72,
        "警告 / WARNING",
        *INTRO_LINES,
        "",
        "这个进程在前台跑。Ctrl-C 会停。它不安装后台服务，也不写密钥到磁盘。",
        "This process stays in the foreground. Ctrl-C stops it. It installs no",
        "background service and it does not write the key to disk.",
        "",
        f"服务商 / provider: {resolved.id} ({resolved.protocol})",
        f"密钥只会发给这个地址 / the key is sent only to: {resolved.endpoint_url}",
        f"模型 / model: {resolved.model}",
        f"密钥来源 / key source: {key_source}",
        f"上限 / caps: {limits.max_tokens} tokens, {limits.budget_usd_label}, {limits.max_calls} calls",
        f"每次最多请求 / per call at most: {limits.completion_tokens} output tokens",
        f"本地估计单价 / local estimate per 1M tokens: input {price_in}, output {price_out}",
        "金额是本地估计，不是供应商账单。token 上限看的是服务商返回的 usage。",
        "The USD figure is a local estimate, not your provider's bill.",
        "The token cap uses the usage the provider reports.",
        "模型正文会被丢掉，不会整段打印。 / Model text is discarded, not printed.",
        f"固定的废话请求 / fixed useless prompt: {PROMPT}",
    ]
    if limits.max_tokens > 10_000 or limits.budget_micro > 1_000_000:
        lines.extend(
            [
                "",
                "你把上限设得比较高。确认这是你自己的钱。",
                "You set a high cap. Confirm this is your own money.",
            ]
        )
    if dry_run:
        lines.extend(
            [
                "",
                "演练模式：不会联网，不会扣费。",
                "Dry-run: no network and no spend.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "这次会真正调用 API 并花钱。",
                "This will really call the API and spend money.",
            ]
        )
    lines.append("=" * 72)
    return "\n".join(lines)


def confirmed(args, stdin, stderr) -> bool:
    if args.yes:
        print("已收到 --yes。 / Received --yes.", file=stderr)
        return True
    is_tty = bool(getattr(stdin, "isatty", lambda: False)())
    if not is_tty:
        print(
            "没有确认，拒绝运行。加上 --yes，或在终端里输入 YES。没有调用 API。\n"
            "Refusing to run without confirmation. Pass --yes, or type YES in a terminal. "
            "No API call was made.",
            file=stderr,
        )
        return False
    print("输入 YES 才开始。其他任何输入都会退出，并且不会调用 API。", file=stderr)
    print("Type YES to start. Anything else quits, and no API call is made.", file=stderr)
    answer = stdin.readline()
    if answer.strip() == "YES":
        return True
    print(
        "未输入 YES，已退出。没有调用 API。\nYou did not type YES. Exited. No API call was made.",
        file=stderr,
    )
    return False


def render_summary(summary: Summary, dry_run: bool) -> str:
    lines = [
        f"停止原因 / stop: {REASON_TEXT.get(summary.reason, summary.reason)}",
        f"调用次数 / calls: {summary.calls}",
        f"输入 tokens / input tokens: {summary.prompt_tokens}",
        f"输出 tokens / output tokens: {summary.completion_tokens}",
        f"合计 tokens / total tokens: {summary.total_tokens}",
        f"估计花费 / estimated cost: {format_usd(summary.spent_micro)}",
        "模型回复已丢弃 / model text discarded",
    ]
    if summary.detail and summary.detail != REASON_TEXT.get(summary.reason):
        lines.append(f"详情 / detail: {summary.detail}")
    if dry_run:
        lines.append("演练，没有联网，没有扣费。 / Dry-run: no network and no spend.")
    if summary.calls == 0 and summary.reason in CAP_REASONS:
        lines.append(
            "一口都没吃成：保守估计一口就会超过上限。\n"
            "Not even one bite: the conservative estimate of a single call would cross the cap."
        )
    return "\n".join(lines)


def _status_line(state, limits) -> str:
    return (
        f"吃饭中 / eating  第 {state.calls} 口  "
        f"tokens {state.total_tokens}/{limits.max_tokens}  "
        f"est {format_usd(state.spent_micro)}/{limits.budget_usd_label}"
    )


def main(argv=None, stdin=None, stdout=None, stderr=None, client_factory=None) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_providers:
        print("\n".join(INTRO_LINES), file=stdout)
        print("", file=stdout)
        print("\n".join(catalog_lines()), file=stdout)
        print("\n列出来不会花钱。 / Listing providers does not spend money.", file=stdout)
        return EXIT_OK

    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 120:
            raise ConfigError(
                "--timeout 必须大于 0 且不超过 120 秒。\n"
                "--timeout must be greater than 0 and at most 120 seconds."
            )
        provider_name = _env_or_flag(args.provider, "EAT_TOKENS_PROVIDER") or "deepseek"
        base_url = _env_or_flag(args.base_url, "EAT_TOKENS_BASE_URL")
        model = _env_or_flag(args.model, "EAT_TOKENS_MODEL")
        resolved = resolve_provider(
            provider_name,
            base_url,
            model,
            args.input_usd_per_million,
            args.output_usd_per_million,
        )
        limits = validate_limits(
            args.max_tokens,
            args.budget_usd,
            args.max_calls,
            args.completion_tokens,
            resolved.input_usd_per_million,
            resolved.output_usd_per_million,
        )
    except ConfigError as exc:
        print(redact(str(exc), args.api_key), file=stderr)
        return EXIT_REFUSED

    key = None
    key_source = None
    if not args.dry_run:
        try:
            key, key_source = resolve_api_key(resolved, args.api_key)
        except ConfigError as exc:
            # Print the warning first so a missing key still shows what this is.
            print(
                render_warning(resolved, limits, "（还没找到密钥 / no key found yet）", dry_run=False),
                file=stderr,
            )
            print(redact(str(exc), args.api_key), file=stderr)
            return EXIT_REFUSED

    key_label = "（演练，不使用密钥 / dry-run, no key）" if args.dry_run else key_source
    print(render_warning(resolved, limits, key_label, args.dry_run), file=stderr)
    if not confirmed(args, stdin, stderr):
        return EXIT_REFUSED

    if args.dry_run:
        client = DryRunClient()
    else:
        factory = client_factory or HttpClient
        client = factory(resolved, key, args.timeout)

    def before(index: int, size: int) -> None:
        print(
            f"要下口了 / about to take bite {index}, asking for {size} output tokens",
            file=stderr,
            flush=True,
        )

    tty = bool(getattr(stderr, "isatty", lambda: False)())

    def after(state) -> None:
        line = _status_line(state, limits)
        if tty:
            print("\r" + line, end="", file=stderr, flush=True)
        else:
            print(line, file=stderr, flush=True)

    try:
        summary = eat(
            limits,
            client,
            estimate_prompt_tokens(PROMPT),
            before=before,
            after=after,
        )
    except KeyboardInterrupt:
        if tty:
            print(file=stderr)
        print(
            "已停下，没有继续吃。 / Stopped. Did not keep eating.",
            file=stderr,
        )
        return EXIT_INTERRUPTED

    if tty:
        print(file=stderr)
    secret = key
    if summary.reason in CAP_REASONS:
        print("我吃饱了", file=stdout)
    elif summary.reason == "interrupt":
        print("已停下，没有继续吃。 / Stopped. Did not keep eating.", file=stderr)
    print(redact(render_summary(summary, args.dry_run), secret), file=stdout)
    if summary.reason == "error":
        return EXIT_ERROR
    if summary.reason == "interrupt":
        return EXIT_INTERRUPTED
    return EXIT_OK
