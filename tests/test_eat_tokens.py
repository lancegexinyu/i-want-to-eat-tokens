"""Safety tests. None of these open a network connection."""

from __future__ import annotations

import io
import json
import os
import threading
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from urllib import request

from eat_tokens import __doc__ as PACKAGE_DOC
from eat_tokens import __version__
from eat_tokens.cli import main
from eat_tokens.eater import (
    CAP_REASONS,
    DryRunClient,
    Usage,
    cost_micro,
    eat,
    usd_to_micro,
    validate_limits,
)
from eat_tokens.errors import ConfigError, ProviderError
from eat_tokens.http_client import (
    NoRedirect,
    build_request,
    make_opener,
    parse_success_body,
    redact,
    usage_from_payload,
)
from eat_tokens.providers import (
    PLACEHOLDER_KEYS,
    PROMPT,
    PROVIDERS,
    estimate_prompt_tokens,
    resolve_api_key,
    resolve_provider,
    validate_api_key,
    validate_base_url,
)
from eat_tokens.statements import INTRO_LINES

ROOT = Path(__file__).resolve().parents[1]
KEY_ENVS = (
    "EAT_TOKENS_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "XAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "EAT_TOKENS_PROVIDER",
    "EAT_TOKENS_BASE_URL",
    "EAT_TOKENS_MODEL",
    "EAT_TOKENS_MAX_TOKENS",
    "EAT_TOKENS_BUDGET_USD",
)
KEY = "unit-test-key-value"


@contextmanager
def clean_env():
    saved = {name: os.environ.get(name) for name in KEY_ENVS}
    for name in KEY_ENVS:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_cli(argv, factory=None, stdin=None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    if stdin is None:
        stdin = io.StringIO("")
    code = main(argv, stdin=stdin, stdout=stdout, stderr=stderr, client_factory=factory)
    return code, stdout.getvalue(), stderr.getvalue()


class BoomFactory:
    def __init__(self, *args, **kwargs):
        raise AssertionError("client was constructed")


class CountingClient:
    def __init__(self, usage=None, error=None):
        self.usage = usage or Usage(10, 4)
        self.error = error
        self.sizes = []

    def complete(self, size):
        self.sizes.append(size)
        if self.error is not None:
            raise self.error
        return self.usage


class TestStatements(unittest.TestCase):
    def test_intro_is_in_the_package_readme_and_warning(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(PACKAGE_DOC, "\n".join(INTRO_LINES))
        for line in INTRO_LINES:
            self.assertIn(line, readme)
            self.assertIn(line, project)
            self.assertIn(line, PACKAGE_DOC)
        # Both languages get a full guide, not a one-line English footnote.
        self.assertIn("# 中文", readme)
        self.assertIn("# English", readme)
        self.assertLess(readme.index("# 中文"), readme.index("# English"))
        for heading in ("## 安装", "## Install", "## 服务商", "## Providers", "## 上限", "## Caps"):
            self.assertIn(heading, readme)

    def test_readme_lists_every_preset(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for spec in PROVIDERS.values():
            if spec.base_url:
                self.assertIn(spec.base_url, readme)
            if spec.model:
                self.assertIn(spec.model, readme)
            for env_name in spec.env_vars:
                self.assertIn(env_name, readme)
        self.assertIn("EAT_TOKENS_API_KEY", readme)
        self.assertIn("我吃饱了", readme)
        self.assertNotIn("sk-", readme.replace("sk-your-own-key-here", ""))

    def test_example_env_is_placeholders_only(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("your-own-key-here", text)
        for line in text.splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            value = line.split("=", 1)[1].strip()
            self.assertIn(value, PLACEHOLDER_KEYS)

    def test_source_does_not_start_background_work(self):
        blob = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py"))
        for word in ("subprocess", "threading", "multiprocessing", "os.fork", "crontab", "nohup", "atexit"):
            self.assertNotIn(word, blob)


class TestCaps(unittest.TestCase):
    def test_cost_math_matches_price_per_million(self):
        self.assertEqual(
            cost_micro(1_000_000, 0, usd_to_micro(0.30), usd_to_micro(1.20)),
            usd_to_micro(0.30),
        )
        self.assertEqual(
            cost_micro(0, 1_000_000, usd_to_micro(0.30), usd_to_micro(1.20)),
            usd_to_micro(1.20),
        )

    def test_rejects_unlimited_zero_and_non_finite(self):
        bad = [
            (0, 0.01, 1, 1),
            (-1, 0.01, 1, 1),
            (10, 0, 1, 1),
            (10, -1, 1, 1),
            (10, float("inf"), 1, 1),
            (10, float("nan"), 1, 1),
            (10, 0.01, 0, 1),
            (10, 0.01, 1, 0),
            (10, 0.01, 10_000, 1),
            (10_000_001, 0.01, 1, 1),
        ]
        for tokens, budget, calls, completion in bad:
            with self.assertRaises(ConfigError):
                validate_limits(tokens, budget, calls, completion, 0.30, 1.20)
        with self.assertRaises(ConfigError):
            validate_limits(10, 0.01, 1, 1, 0, 1.20)
        with self.assertRaises(ConfigError):
            validate_limits(10, 0.01, 1, 1, float("inf"), 1.20)

    def test_dry_run_stops_inside_the_default_token_cap(self):
        limits = validate_limits(256, 0.01, 20, 16, 0.30, 1.20)
        summary = eat(limits, DryRunClient(), estimate_prompt_tokens(PROMPT))
        self.assertIn(summary.reason, CAP_REASONS)
        self.assertGreaterEqual(summary.calls, 1)
        self.assertLessEqual(summary.total_tokens, 256)
        self.assertLess(summary.spent_micro, usd_to_micro(0.01))

    def test_call_cap_and_token_overshoot_and_budget(self):
        client = CountingClient(Usage(1, 1))
        limits = validate_limits(10_000, 10, 3, 16, 0.30, 1.20)
        summary = eat(limits, client, estimate_prompt_tokens(PROMPT))
        self.assertEqual(summary.reason, "call_cap")
        self.assertEqual(summary.calls, 3)
        self.assertEqual(len(client.sizes), 3)

        fat = CountingClient(Usage(80, 30))
        limits = validate_limits(100, 10, 20, 16, 0.30, 1.20)
        summary = eat(limits, fat, estimate_prompt_tokens(PROMPT))
        self.assertEqual(summary.reason, "token_cap")
        self.assertEqual(summary.calls, 1)
        self.assertGreaterEqual(summary.total_tokens, 100)

        pricey = CountingClient()
        limits = validate_limits(100_000, 0.01, 20, 16, 100_000, 100_000)
        summary = eat(limits, pricey, estimate_prompt_tokens(PROMPT))
        self.assertEqual(summary.reason, "budget_cap")
        self.assertEqual(pricey.sizes, [])
        self.assertEqual(summary.calls, 0)

    def test_error_stops_without_another_call(self):
        client = CountingClient(error=ProviderError("missing usage", billed_unknown=True))
        limits = validate_limits(10_000, 10, 20, 16, 0.30, 1.20)
        summary = eat(limits, client, estimate_prompt_tokens(PROMPT))
        self.assertEqual(summary.reason, "error")
        self.assertEqual(len(client.sizes), 1)
        self.assertEqual(summary.calls, 1)
        self.assertGreater(summary.total_tokens, 0)

        client = CountingClient(error=ProviderError("HTTP 401"))
        summary = eat(limits, client, estimate_prompt_tokens(PROMPT))
        self.assertEqual(len(client.sizes), 1)
        self.assertEqual(summary.prompt_tokens, 0)

    def test_interrupt_stops(self):
        client = CountingClient(error=KeyboardInterrupt())
        limits = validate_limits(10_000, 10, 20, 16, 0.30, 1.20)
        summary = eat(limits, client, estimate_prompt_tokens(PROMPT))
        self.assertEqual(summary.reason, "interrupt")
        self.assertEqual(len(client.sizes), 1)


class TestProviders(unittest.TestCase):
    def test_endpoints(self):
        cases = {
            "deepseek": "https://api.deepseek.com/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
            "codex": "https://api.openai.com/v1/chat/completions",
            "grok": "https://api.x.ai/v1/chat/completions",
            "xai": "https://api.x.ai/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "claude": "https://api.anthropic.com/v1/messages",
        }
        for name, url in cases.items():
            resolved = resolve_provider(name, None, None, None, None)
            self.assertEqual(resolved.endpoint_url, url)
        self.assertEqual(resolve_provider("deepseek", None, None, None, None).model, "deepseek-flash")
        self.assertEqual(resolve_provider("openai", None, None, None, None).model, "gpt-4.1-mini")
        self.assertEqual(resolve_provider("codex", None, None, None, None).model, "gpt-5.1-codex")
        self.assertEqual(resolve_provider("grok", None, None, None, None).model, "grok-4.7")
        self.assertEqual(resolve_provider("anthropic", None, None, None, None).model, "claude-haiku-4-5")

    def test_overrides_and_rejections(self):
        resolved = resolve_provider(
            "codex", "https://example.com/v1", "my-codex", None, None
        )
        self.assertEqual(resolved.endpoint_url, "https://example.com/v1/chat/completions")
        self.assertEqual(resolved.model, "my-codex")
        resolved = resolve_provider(
            "openai", "https://api.openai.com/v1/chat/completions", None, None, None
        )
        self.assertEqual(resolved.endpoint_url, "https://api.openai.com/v1/chat/completions")
        resolved = resolve_provider("anthropic", "https://api.anthropic.com/v1", None, None, None)
        self.assertEqual(resolved.endpoint_url, "https://api.anthropic.com/v1/messages")
        with self.assertRaises(ConfigError):
            resolve_provider("compatible", None, None, None, None)
        with self.assertRaises(ConfigError):
            resolve_provider("nope", None, None, None, None)
        with self.assertRaises(ConfigError):
            validate_base_url("http://example.com/v1")
        with self.assertRaises(ConfigError):
            validate_base_url("file:///etc/passwd")
        with self.assertRaises(ConfigError):
            validate_base_url("https://user:pass@api.deepseek.com")
        self.assertEqual(validate_base_url("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")

    def test_keys_do_not_cross_providers(self):
        with clean_env():
            os.environ["OPENAI_API_KEY"] = KEY
            deepseek = resolve_provider("deepseek", None, None, None, None)
            with self.assertRaises(ConfigError):
                resolve_api_key(deepseek, None)
            compatible = resolve_provider(
                "compatible", "https://example.com/v1", "m", None, None
            )
            with self.assertRaises(ConfigError):
                resolve_api_key(compatible, None)
            openai = resolve_provider("openai", None, None, None, None)
            key, source = resolve_api_key(openai, None)
            self.assertEqual(key, KEY)
            self.assertEqual(source, "OPENAI_API_KEY")
            os.environ["EAT_TOKENS_API_KEY"] = "generic-key-value"
            key, source = resolve_api_key(openai, None)
            self.assertEqual(source, "EAT_TOKENS_API_KEY")
            key, source = resolve_api_key(openai, "flag-key-value!!")
            self.assertEqual(source, "--api-key")
            self.assertEqual(key, "flag-key-value!!")

    def test_placeholder_and_short_keys_are_rejected(self):
        for placeholder in PLACEHOLDER_KEYS:
            with self.assertRaises(ConfigError):
                validate_api_key(placeholder)
        with self.assertRaises(ConfigError):
            validate_api_key("short")
        with self.assertRaises(ConfigError):
            validate_api_key("line\nbreak-key")


class TestHttp(unittest.TestCase):
    def _body(self, req):
        return json.loads(req.data.decode("utf-8"))

    def test_request_shapes_and_key_placement(self):
        deepseek = resolve_provider("deepseek", None, None, None, None)
        req = build_request(deepseek, KEY, 16)
        body = self._body(req)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["max_tokens"], 16)
        self.assertNotIn("max_completion_tokens", body)
        self.assertFalse(body["stream"])
        self.assertEqual(body["messages"][0]["content"], PROMPT)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertIsNone(req.get_header("X-api-key"))
        self.assertNotIn(KEY, req.full_url)
        self.assertNotIn(KEY.encode(), req.data)

        openai = resolve_provider("openai", None, None, None, None)
        body = self._body(build_request(openai, KEY, 16))
        self.assertEqual(body["max_completion_tokens"], 16)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("thinking", body)

        codex = resolve_provider("codex", None, None, None, None)
        body = self._body(build_request(codex, KEY, 8))
        self.assertEqual(body["model"], "gpt-5.1-codex")
        self.assertEqual(body["max_completion_tokens"], 8)

        grok = resolve_provider("grok", None, None, None, None)
        body = self._body(build_request(grok, KEY, 16))
        self.assertEqual(body["max_tokens"], 16)
        self.assertNotIn("thinking", body)
        self.assertEqual(
            build_request(grok, KEY, 16).full_url,
            "https://api.x.ai/v1/chat/completions",
        )

        claude = resolve_provider("claude", None, None, None, None)
        req = build_request(claude, KEY, 16)
        body = self._body(req)
        self.assertEqual(body["max_tokens"], 16)
        self.assertEqual(body["model"], "claude-haiku-4-5")
        self.assertEqual(req.get_header("X-api-key"), KEY)
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        self.assertIsNone(req.get_header("Authorization"))
        self.assertNotIn(KEY, req.full_url)

        custom = resolve_provider("compatible", "https://api.deepseek.com", "deepseek-flash", None, None)
        body = self._body(build_request(custom, KEY, 8))
        self.assertEqual(body["thinking"]["type"], "disabled")
        self.assertIn("max_tokens", body)

        lookalike = resolve_provider(
            "compatible", "https://api.openai.com.evil.example/v1", "m", None, None
        )
        body = self._body(build_request(lookalike, KEY, 8))
        self.assertIn("max_tokens", body)
        self.assertNotIn("max_completion_tokens", body)
        self.assertNotIn("thinking", body)

    def test_usage_parsing_discards_model_text(self):
        payload = {
            "choices": [{"message": {"content": "X" * 5000}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
        usage = usage_from_payload(payload)
        self.assertEqual(usage, Usage(10, 2))
        self.assertNotIn("X" * 20, str(usage))
        bigger = usage_from_payload(
            {"usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 20}}
        )
        self.assertEqual(bigger, Usage(3, 17))
        with self.assertRaises(ProviderError) as ctx:
            parse_success_body(b'data: {"choices":[{"delta":{"content":"hello"}}]}')
        self.assertTrue(ctx.exception.billed_unknown)

    def test_redirects_are_refused_and_proxies_are_ignored(self):
        handler = NoRedirect()
        with self.assertRaises(ProviderError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/steal")
        saved = os.environ.get("https_proxy")
        os.environ["https_proxy"] = "http://127.0.0.1:9"
        try:
            opener = make_opener()
        finally:
            if saved is None:
                os.environ.pop("https_proxy", None)
            else:
                os.environ["https_proxy"] = saved
        self.assertTrue(any(isinstance(item, NoRedirect) for item in opener.handlers))
        self.assertFalse(any(type(item) is request.HTTPRedirectHandler for item in opener.handlers))
        self.assertFalse(any(type(item) is request.ProxyHandler for item in opener.handlers))
        self.assertFalse(any(type(item) is request.FileHandler for item in opener.handlers))
        with self.assertRaises(ProviderError):
            opener.open(request.Request("file:///etc/passwd"))

    def test_redact(self):
        self.assertEqual(redact(f"see {KEY} please", KEY), "see [redacted] please")


class TestCli(unittest.TestCase):
    def test_help_and_list_do_not_construct_a_client(self):
        with clean_env():
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--help"], client_factory=BoomFactory)
            self.assertEqual(ctx.exception.code, 0)
            self.assertIn("整活", stdout.getvalue())
            code, out, err = run_cli(["--list-providers"], factory=BoomFactory)
            self.assertEqual(code, 0)
            self.assertIn("api.deepseek.com", out)
            self.assertIn("api.anthropic.com", out)
            self.assertIn("api.x.ai", out)
            self.assertIn("gpt-5.1-codex", out)

    def test_refuses_without_confirmation_and_does_not_call(self):
        with clean_env():
            threads = threading.active_count()
            code, out, err = run_cli(["--dry-run"], factory=BoomFactory)
            self.assertEqual(code, 2)
            self.assertNotIn("我吃饱了", out)
            self.assertIn("拒绝运行", err)
            for line in INTRO_LINES:
                self.assertIn(line, err)
            self.assertEqual(threading.active_count(), threads)
            stdin = io.StringIO("no\n")
            stdin.isatty = lambda: True
            code, out, err = run_cli(["--dry-run"], factory=BoomFactory, stdin=stdin)
            self.assertEqual(code, 2)
            self.assertNotIn("我吃饱了", out)

    def test_dry_run_yes_is_full_and_offline(self):
        with clean_env():
            os.environ["EAT_TOKENS_MAX_TOKENS"] = "999999"
            os.environ["EAT_TOKENS_BUDGET_USD"] = "1000"
            code, out, err = run_cli(["--dry-run", "--yes"], factory=BoomFactory)
            self.assertEqual(code, 0)
            self.assertIn("我吃饱了", out)
            self.assertIn("256 tokens", err)
            self.assertIn("$0.010000", err)
            self.assertIn("演练模式", err)
            self.assertNotIn("这次会真正调用", err)
            self.assertIn("https://api.deepseek.com/chat/completions", err)
            for line in INTRO_LINES:
                self.assertIn(line, err)
            self.assertNotIn("999999", err)

    def test_confirmed_run_uses_only_the_selected_key(self):
        seen = {}

        def factory(provider, api_key, timeout):
            seen["key"] = api_key
            seen["url"] = provider.endpoint_url
            seen["model"] = provider.model
            return CountingClient(Usage(10, 4))

        with clean_env():
            os.environ["OPENAI_API_KEY"] = "openai-key-should-not-be-used"
            code, out, err = run_cli(
                ["--yes", "--provider", "deepseek", "--api-key", KEY, "--max-calls", "2"],
                factory=factory,
            )
            self.assertEqual(code, 0)
            self.assertEqual(seen["key"], KEY)
            self.assertEqual(seen["url"], "https://api.deepseek.com/chat/completions")
            self.assertNotIn("openai-key-should-not-be-used", out + err)
            self.assertNotIn(KEY, out + err)
            self.assertIn("我吃饱了", out)
            self.assertIn("--api-key", err)
            self.assertIn("这次会真正调用", err)

    def test_missing_key_and_unknown_flags(self):
        with clean_env():
            os.environ["OPENAI_API_KEY"] = KEY
            code, out, err = run_cli(["--yes", "--provider", "deepseek"], factory=BoomFactory)
            self.assertEqual(code, 2)
            self.assertNotIn("我吃饱了", out)
            self.assertNotIn(KEY, out + err)
            code, out, err = run_cli(
                [
                    "--yes",
                    "--provider",
                    "compatible",
                    "--base-url",
                    "https://example.com/v1",
                    "--model",
                    "m",
                ],
                factory=BoomFactory,
            )
            self.assertEqual(code, 2)
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--daemon"], client_factory=BoomFactory)
            self.assertEqual(ctx.exception.code, 2)
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--prompt", "hello"], client_factory=BoomFactory)
            self.assertEqual(ctx.exception.code, 2)

    def test_error_and_interrupt_do_not_claim_to_be_full(self):
        def error_factory(provider, api_key, timeout):
            return CountingClient(error=ProviderError(f"boom {api_key}"))

        with clean_env():
            code, out, err = run_cli(
                ["--yes", "--api-key", KEY, "--provider", "openai"],
                factory=error_factory,
            )
            self.assertEqual(code, 1)
            self.assertNotIn("我吃饱了", out)
            self.assertNotIn(KEY, out + err)
            self.assertIn("[redacted]", out)

        def interrupt_factory(provider, api_key, timeout):
            return CountingClient(error=KeyboardInterrupt())

        with clean_env():
            code, out, err = run_cli(
                ["--yes", "--api-key", KEY, "--provider", "grok"],
                factory=interrupt_factory,
            )
            self.assertEqual(code, 130)
            self.assertNotIn("我吃饱了", out)
            self.assertIn("已停下", err)

    def test_high_cap_is_called_out(self):
        with clean_env():
            code, out, err = run_cli(
                ["--dry-run", "--yes", "--max-tokens", "20000", "--budget-usd", "2", "--max-calls", "1"],
                factory=BoomFactory,
            )
            self.assertEqual(code, 0)
            self.assertIn("你把上限设得比较高", err)
            self.assertIn("我吃饱了", out)

    def test_version_matches_package(self):
        self.assertEqual(__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
