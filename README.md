# 我想吃 token / I Want to Eat Tokens

> **警告 / WARNING**
>
> **这会花掉真钱。它什么有用的事都不做。不要运行，除非你就是想烧掉 token。**
>
> **This spends real money. It does nothing useful. Do not run it unless you intend to burn tokens.**

这是一个笑话 / 整活版本，不是正经工具。

This is a joke / troll (整活) version, not a useful tool.

它只烧掉你自己的钱：消耗的是你自己的 API token。它不会把钱转给作者，也不会把钱转给其他任何人。

It only burns your own money by consuming your own API tokens. It does not transfer money to the author, and it does not transfer money to anyone else.

它真的会消耗 token：这是真实的 API 调用，会产生真实的花费。

It really does consume tokens: real API usage and real spend.

它不是会在后台偷偷消耗 token 的恶意软件。你必须自己提供密钥，并且在任何花费发生之前明确确认。

It is not malware that secretly consumes tokens in the background. You must supply your own key and explicitly confirm before any spend.

没有 `--yes`，也没有在终端里输入 `YES`，它就不会发出任何 API 请求。默认上限很小：256 个 token、0.01 美元的本地估计、最多 20 次调用。没有「无限」这一档。

Without `--yes`, and without typing `YES` in a terminal, it does not send any API request. The default cap is small: 256 tokens, a local estimate of $0.01, and at most 20 calls. There is no unlimited setting.

---

# 中文

## 这到底是什么

有人开玩笑，说想做一个调用大模型的插件：没有目标，没有有用的结果，只是因为「我想吃」。吃到自己设的上限，就说「我吃饱了」。

这个仓库就是那个笑话的命令行版本。它在前台一轮一轮地调用你自己选定的模型接口，把模型回复丢掉，在屏幕上显示吃掉了多少 token、估计花了多少钱，然后停下来。

它是整活，也是一个反面教材：让你看见「一个没有目的的循环」如何变成真账单。

## 四个事实

1. 这是一个笑话 / 整活版本，不是正经工具。
2. 它只烧掉你自己的钱：消耗的是你自己的 API token。它不会把钱转给作者，也不会把钱转给其他任何人。作者不收款，不抽成，不提供代付，页面上也没有任何付款地址。钱只可能出现在你自己的模型供应商账单上。
3. 它真的会消耗 token：这是真实的 API 调用，会产生真实的花费。演练模式除外，演练模式不会联网。
4. 它不是会在后台偷偷消耗 token 的恶意软件。你必须自己提供密钥，并且在任何花费发生之前明确确认。进程结束就结束。它不安装守护进程，不写计划任务，不驻留，不读取别人的密钥文件，也不把密钥发到你没有在警告里看到的地址。

## 它不会做什么

- 不会使用仓库里写死的密钥。仓库里没有真密钥。
- 不会自动读取 `.env`。示例文件里的值全是占位符 `your-own-key-here`。
- 不会在你只是打开帮助、列出服务商、或者拒绝确认的时候联网。
- 不会重试。一次失败就停，避免失败循环把账单放大。
- 不会跟随重定向，也不会理睬 `HTTP_PROXY` / `HTTPS_PROXY`。密钥只发给警告里印出来的那个 URL。
- 不会把模型正文整段打出来。回复被丢掉。
- 不会变成一个有用的聊天工具。请求是写死的一句废话，没有自定义 prompt。

## 安装

需要 Python 3.9 或更高版本。除了标准库，没有第三方依赖。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

先看帮助和预设，这两步不花钱：

```bash
eat-tokens --help
eat-tokens --list-providers
```

## 演练：不联网，不扣费

演练走同一套上限和确认，但用量是假的。

```bash
eat-tokens --dry-run --yes
```

你应该看到警告，然后看到「我吃饱了」和一份用量小结。这一步没有 API 调用。

不带 `--yes`、而且标准输入不是终端时，它直接拒绝，退出码是 2：

```bash
eat-tokens --dry-run
```

在真正的终端里不带 `--yes`，它会先打印警告，然后等你输入大写的 `YES`。其他任何输入都退出，并且不调用 API。

## 真的要吃的时候

先导出**你自己的**密钥。不要用别人的。命令行上的 `--api-key` 会出现在进程列表里，所以更建议用环境变量。

```bash
export DEEPSEEK_API_KEY="你自己的密钥"
eat-tokens --yes
```

默认服务商是 DeepSeek。警告会印出即将收到密钥的完整 URL、模型、上限和估计单价。看完再让它跑。觉得不对就 Ctrl-C，或者根本不要输入 `YES`。

跑起来的时候，标准错误上会有一行行的「吃饭中」：第几口、已经计入的 token、估计金额。吃到上限就在标准输出打印：

```text
我吃饱了
```

下面是调用次数、输入 token、输出 token、合计 token 和估计花费。

## 上限

默认值，也是不传参数时一定会用的值：

| 上限 | 默认 | 你能设到的最大 |
| --- | --- | --- |
| `--max-tokens` | 256 | 1000000 |
| `--budget-usd` | 0.01 | 25 |
| `--max-calls` | 20 | 500 |
| `--completion-tokens` | 16 | 256 |

这三个总上限谁先到就停。单次请求的输出 token 另外被压在 256 以内，避免一口要出一整篇文章。

上限不从环境变量读取。一个忘了关掉的旧变量不能把帽摘掉。

金额上限用的是本地估计，不是供应商账单。token 上限用的是响应里的 `usage`。如果服务商没给 usage，工具把这一口按请求上限估进去，然后停，不再继续。

有的推理模型会在你请求的输出之外再计 reasoning token。DeepSeek 的主机上，本工具会强制关掉 thinking，避免默认的思考模式一口吃掉一大截。Grok、Codex 一类模型仍可能在单次响应里超出请求的数量。循环会在看到那次 usage 之后立刻停。所以单次响应可能比剩余额度略多。这不是一张「花费绝不会超过显示金额」的保单。默认值把这个缺口留得很小。

把上限调高会在警告里再写一行，提醒你这是你自己的钱。

## 服务商

你自己选服务商，自己带密钥。密钥查找顺序是：

1. `--api-key`
2. 环境变量 `EAT_TOKENS_API_KEY`
3. 下表里该服务商自己的环境变量

不会串到别的服务商的变量上。指向任意兼容接口时，更不会悄悄把 `OPENAI_API_KEY` 发出去。

| `--provider` | 协议 | 默认 base URL | 默认模型 | 环境变量 |
| --- | --- | --- | --- | --- |
| `deepseek`（默认） | OpenAI `POST /chat/completions` | `https://api.deepseek.com` | `deepseek-flash` | `DEEPSEEK_API_KEY` |
| `openai` | OpenAI `POST /chat/completions` | `https://api.openai.com/v1` | `gpt-4.1-mini` | `OPENAI_API_KEY` |
| `codex` | OpenAI `POST /chat/completions` | `https://api.openai.com/v1` | `gpt-5.1-codex` | `CODEX_API_KEY`，没有再看 `OPENAI_API_KEY` |
| `grok`（别名 `xai`） | OpenAI `POST /chat/completions` | `https://api.x.ai/v1` | `grok-4.7` | `XAI_API_KEY` |
| `anthropic`（别名 `claude`） | Anthropic `POST /v1/messages` | `https://api.anthropic.com` | `claude-haiku-4-5` | `ANTHROPIC_API_KEY` |
| `compatible`（别名 `custom`、`openai-compatible`） | OpenAI `POST /chat/completions` | 无默认，必须传 `--base-url` | 无默认，必须传 `--model` | 只用 `EAT_TOKENS_API_KEY` 或 `--api-key` |

任何预设都可以用 `--base-url` 和 `--model` 改掉。也可以用环境变量 `EAT_TOKENS_PROVIDER`、`EAT_TOKENS_BASE_URL`、`EAT_TOKENS_MODEL`，但命令行优先。警告里打印的是最终解析结果。

`deepseek-chat` 和 `deepseek-reasoner` 已在 2026-07-24 退役。默认模型因此是现在的 `deepseek-flash`。你仍然可以用 `--model` 指定账户里还接受的名字。

Codex 这一档走的是 OpenAI 兼容的 chat completions，方便你把同一个客户端指到 OpenAI，或者指到另一个兼容该路径的 Codex 端点。它不登录 ChatGPT，也不读取 Codex CLI 的登录文件。ChatGPT 订阅用的 `https://chatgpt.com/backend-api/codex` 说的是 Responses API，不是这里实现的 `/chat/completions`。只提供 `/responses` 的端点，本工具不会去叫，也就不会把密钥送过去。

公网地址必须是 `https`。`http` 只允许本机 `localhost`、`127.0.0.1`、`::1`，方便你打自己的兼容服务。URL 里不能塞账号密码，也不能把密钥放进查询字符串。

### 例子

```bash
# DeepSeek，默认
export DEEPSEEK_API_KEY="你自己的密钥"
eat-tokens --yes

# OpenAI
export OPENAI_API_KEY="你自己的密钥"
eat-tokens --provider openai --yes

# Codex 风格的 chat completions。要换端点就改 base URL 和模型。
export OPENAI_API_KEY="你自己的密钥"
eat-tokens --provider codex --yes
eat-tokens --provider codex \
  --base-url https://example.com/v1 \
  --model gpt-5.1-codex \
  --yes

# xAI Grok
export XAI_API_KEY="你自己的密钥"
eat-tokens --provider grok --yes

# Anthropic Claude
export ANTHROPIC_API_KEY="你自己的密钥"
eat-tokens --provider claude --yes

# 其他 OpenAI 兼容服务。这里不会读取 OPENAI_API_KEY。
export EAT_TOKENS_API_KEY="你自己的密钥"
eat-tokens --provider compatible \
  --base-url https://example.com/v1 \
  --model your-model \
  --input-usd-per-million 1 \
  --output-usd-per-million 2 \
  --yes
```

模型名会过期。某个预设名字被供应商拒绝时，用 `--model` 换成你账户里的名字。调用失败会马上停。

## 估计单价

这些数字只用来在本地提前刹车，不是发票。

| 服务商 | 输入 / 1M token | 输出 / 1M token | 这些数字是什么 |
| --- | --- | --- | --- |
| DeepSeek | 0.30 美元 | 1.20 美元 | 写作时官网价目表上的峰值、缓存未命中价格。非高峰更便宜，所以本地可能会更早停。价格会变，以 [DeepSeek 价目表](https://api-docs.deepseek.com/quick_start/pricing/) 为准。 |
| OpenAI | 0.40 美元 | 1.60 美元 | 本地估计，不是实时报价。 |
| Codex | 1.50 美元 | 6.00 美元 | 故意偏高的本地估计，不是官方标价。 |
| Grok | 5.00 美元 | 15.00 美元 | 故意偏高的本地估计，不是官方标价。 |
| Anthropic | 1.00 美元 | 5.00 美元 | 本地估计，不是官方标价。 |
| compatible | 5.00 美元 | 15.00 美元 | 你没另外标价时的偏高默认值。 |

用 `--input-usd-per-million` 和 `--output-usd-per-million` 改成你知道的单价。两个都必须是有限的正数。

## 停下来的方式

- 报告的 token 达到 `--max-tokens`
- 本地估计金额达到 `--budget-usd`
- 调用次数达到 `--max-calls`
- 再吃一口的保守估计会越过上面任一上限
- HTTP 错误、连不上、超时、没有 usage、或者响应大得不像话
- 你按下 Ctrl-C

达到上限时退出码是 0，并打印「我吃饱了」。出错是 1。你拒绝确认，或者参数不合法，是 2。Ctrl-C 是 130。出错和中断不会假装自己吃饱了。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试不联网。

## 许可

MIT。见 `LICENSE`。许可允许你复制这份代码，不表示运行它是安全的，也不表示作者会替你付账单。

---

# English

## What this is

Someone joked about a plugin that calls a large language model with no goal and no useful result, only because it wants to eat. When it hits the cap it says `我吃饱了` ("I'm full").

This repository is that joke as a command-line program. It sits in the foreground, calls the model API you chose, throws the reply away, shows how many tokens it has eaten and what that probably costs, and then stops.

It is a troll, and it is also an anti-example: a loop with no purpose, attached to a real bill.

## Four facts

1. This is a joke / troll (整活) version, not a useful tool.
2. It only burns your own money by consuming your own API tokens. It does not transfer money to the author, and it does not transfer money to anyone else. The author is not paid, does not take a cut, and does not offer to pay the bill for you. There is no payment address anywhere in this project. The only place a charge can show up is the invoice from the model provider on the account whose key you supplied.
3. It really does consume tokens: real API usage and real spend. The dry-run mode is the exception. Dry-run does not open a network connection.
4. It is not malware that secretly consumes tokens in the background. You must supply your own key and explicitly confirm before any spend. When the process exits, it is gone. It does not install a daemon, does not add a scheduled task, does not stay resident, does not read anyone else's key file, and does not send the key to any address that was not printed in the warning.

## What it will not do

- It will not use a key shipped in the repo. There is no real key in the repo.
- It will not load `.env` for you. Every value in the example file is the placeholder `your-own-key-here`.
- It will not open a connection when you only ask for help, list providers, or refuse to confirm.
- It will not retry. The first failure stops the loop, so a failure cannot multiply the bill.
- It will not follow redirects, and it ignores `HTTP_PROXY` / `HTTPS_PROXY`. The key is sent only to the URL printed in the warning.
- It will not print the model's full reply. The text is discarded.
- It will not turn into a useful chat tool. The prompt is one fixed, useless sentence. There is no custom prompt flag.

## Install

Python 3.9 or newer. The program uses the standard library only.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Help and the provider list do not spend money:

```bash
eat-tokens --help
eat-tokens --list-providers
```

## Dry-run: no network, no spend

Dry-run walks the same caps and the same confirmation, with fake usage.

```bash
eat-tokens --dry-run --yes
```

You should see the warning, then `我吃饱了`, then a short usage summary. That step makes no API call.

With no `--yes`, and with stdin not a terminal, it refuses and exits 2:

```bash
eat-tokens --dry-run
```

In a real terminal, omitting `--yes` prints the warning and waits for the uppercase word `YES`. Anything else exits, and no API call is made.

## When you actually want it to eat

Export **your own** key. Do not use someone else's. `--api-key` shows up in the process list, so an environment variable is the better of the two supported ways.

```bash
export DEEPSEEK_API_KEY="your own key"
eat-tokens --yes
```

DeepSeek is the default provider. The warning prints the exact URL that will receive the key, the model, the caps, and the estimated prices. Read it before you let the process continue. If it looks wrong, press Ctrl-C, or do not type `YES` at all.

While it runs, stderr shows a line per bite: which bite, tokens counted so far, and the estimated cost. When a cap is reached, stdout says:

```text
我吃饱了
```

Under that line: number of calls, input tokens, output tokens, total tokens, and estimated cost.

## Caps

These defaults are what you get when you pass no cap flags:

| Cap | Default | Largest value accepted |
| --- | --- | --- |
| `--max-tokens` | 256 | 1000000 |
| `--budget-usd` | 0.01 | 25 |
| `--max-calls` | 20 | 500 |
| `--completion-tokens` | 16 | 256 |

Whichever of the three total caps is reached first stops the loop. Each request's output is also clamped to at most 256 tokens, so one bite cannot ask for a whole essay.

Caps are not read from the environment. A leftover variable cannot raise them.

The USD cap uses a local estimate, not the provider's invoice. The token cap uses `usage` from the response. If the provider sends no usage, the tool counts that bite at the size it requested and stops. It does not continue blind.

Some reasoning models bill tokens beyond the output you asked for. On a DeepSeek host this tool forces thinking off, so the default thinking mode cannot eat a large hidden budget in one bite. Grok and Codex-style models may still report more tokens than requested. The loop stops as soon as it sees that usage. A single response can therefore land a little past the remaining room. That is not a promise that the real invoice will stay under the number on screen. The defaults keep the gap small.

If you raise the cap, the warning adds a line telling you to confirm that the money is yours.

## Providers

You pick the provider and you bring the key. The key is resolved in this order:

1. `--api-key`
2. the environment variable `EAT_TOKENS_API_KEY`
3. the provider's own variable in the table below

The tool does not fall through into some other provider's variable. The generic compatible preset will not silently send `OPENAI_API_KEY` to a URL you pointed it at.

| `--provider` | Protocol | Default base URL | Default model | Environment variable |
| --- | --- | --- | --- | --- |
| `deepseek` (default) | OpenAI `POST /chat/completions` | `https://api.deepseek.com` | `deepseek-flash` | `DEEPSEEK_API_KEY` |
| `openai` | OpenAI `POST /chat/completions` | `https://api.openai.com/v1` | `gpt-4.1-mini` | `OPENAI_API_KEY` |
| `codex` | OpenAI `POST /chat/completions` | `https://api.openai.com/v1` | `gpt-5.1-codex` | `CODEX_API_KEY`, then `OPENAI_API_KEY` |
| `grok` (alias `xai`) | OpenAI `POST /chat/completions` | `https://api.x.ai/v1` | `grok-4.7` | `XAI_API_KEY` |
| `anthropic` (alias `claude`) | Anthropic `POST /v1/messages` | `https://api.anthropic.com` | `claude-haiku-4-5` | `ANTHROPIC_API_KEY` |
| `compatible` (aliases `custom`, `openai-compatible`) | OpenAI `POST /chat/completions` | none; pass `--base-url` | none; pass `--model` | `EAT_TOKENS_API_KEY` or `--api-key` only |

Every preset accepts `--base-url` and `--model`. You can also set `EAT_TOKENS_PROVIDER`, `EAT_TOKENS_BASE_URL`, and `EAT_TOKENS_MODEL`. Flags win. The warning prints the values that will actually be used.

`deepseek-chat` and `deepseek-reasoner` were retired on 2026-07-24. The default model is the current `deepseek-flash`. You can still pass `--model` if your account accepts another name.

The Codex preset speaks OpenAI-compatible chat completions, so you can point the same client at OpenAI or at another endpoint that accepts that path. It does not log into ChatGPT, and it does not read Codex CLI auth files. The ChatGPT-subscription backend at `https://chatgpt.com/backend-api/codex` speaks the Responses API, not the `/chat/completions` path this tool implements. An endpoint that only offers `/responses` is not called, and the key is not sent there.

Public URLs must be `https`. Plain `http` is allowed only for `localhost`, `127.0.0.1`, and `::1`, so you can point at a compatible server you run yourself. The URL must not contain a username, a password, or the API key.

### Examples

```bash
# DeepSeek, the default
export DEEPSEEK_API_KEY="your own key"
eat-tokens --yes

# OpenAI
export OPENAI_API_KEY="your own key"
eat-tokens --provider openai --yes

# Codex-style chat completions. Change the base URL and model to retarget.
export OPENAI_API_KEY="your own key"
eat-tokens --provider codex --yes
eat-tokens --provider codex \
  --base-url https://example.com/v1 \
  --model gpt-5.1-codex \
  --yes

# xAI Grok
export XAI_API_KEY="your own key"
eat-tokens --provider grok --yes

# Anthropic Claude
export ANTHROPIC_API_KEY="your own key"
eat-tokens --provider claude --yes

# Any other OpenAI-compatible server. OPENAI_API_KEY is not read here.
export EAT_TOKENS_API_KEY="your own key"
eat-tokens --provider compatible \
  --base-url https://example.com/v1 \
  --model your-model \
  --input-usd-per-million 1 \
  --output-usd-per-million 2 \
  --yes
```

Model names go stale. If a preset name is rejected, pass `--model` with a name your account accepts. A failed call stops immediately.

## Estimated prices

These numbers exist so the local brake can trip. They are not an invoice.

| Provider | Input / 1M tokens | Output / 1M tokens | What the number is |
| --- | --- | --- | --- |
| DeepSeek | $0.30 | $1.20 | The published peak, cache-miss rate at the time of writing. Off-peak is cheaper, so the local brake may stop before the real bill reaches the USD cap. Prices change. Check the [DeepSeek pricing page](https://api-docs.deepseek.com/quick_start/pricing/). |
| OpenAI | $0.40 | $1.60 | A local estimate, not a live quote. |
| Codex | $1.50 | $6.00 | A deliberately high local estimate, not an official price. |
| Grok | $5.00 | $15.00 | A deliberately high local estimate, not an official price. |
| Anthropic | $1.00 | $5.00 | A local estimate, not an official price. |
| compatible | $5.00 | $15.00 | The high default used until you set your own rates. |

Override them with `--input-usd-per-million` and `--output-usd-per-million`. Both must be finite and greater than zero.

## How it stops

- Reported tokens reach `--max-tokens`
- The local cost estimate reaches `--budget-usd`
- The number of calls reaches `--max-calls`
- The conservative estimate of one more bite would cross any of those caps
- An HTTP error, a connection failure, a timeout, a missing usage object, or a response that is absurdly large
- You press Ctrl-C

Hitting a cap exits 0 and prints `我吃饱了`. An error exits 1. Refusing to confirm, or passing a bad argument, exits 2. Ctrl-C exits 130. Errors and interrupts do not claim to be full.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests do not use the network.

## License

MIT. See `LICENSE`. The license lets you copy this code. It does not make running it safe, and it does not mean the author pays the bill.
