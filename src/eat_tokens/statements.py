"""Bilingual sentences that the warning, package text, and README must share.

These are the product identity. They are not a sales pitch and not a
disclaimer tucked in a footnote.
"""

JOKE_ZH = "这是一个笑话 / 整活版本，不是正经工具。"
JOKE_EN = "This is a joke / troll (整活) version, not a useful tool."

MONEY_ZH = (
    "它只烧掉你自己的钱：消耗的是你自己的 API token。"
    "它不会把钱转给作者，也不会把钱转给其他任何人。"
)
MONEY_EN = (
    "It only burns your own money by consuming your own API tokens. "
    "It does not transfer money to the author, and it does not transfer money to anyone else."
)

REAL_ZH = "它真的会消耗 token：这是真实的 API 调用，会产生真实的花费。"
REAL_EN = "It really does consume tokens: real API usage and real spend."

MALWARE_ZH = (
    "它不是会在后台偷偷消耗 token 的恶意软件。"
    "你必须自己提供密钥，并且在任何花费发生之前明确确认。"
)
MALWARE_EN = (
    "It is not malware that secretly consumes tokens in the background. "
    "You must supply your own key and explicitly confirm before any spend."
)

# Order is the order shown in the warning and the README intro.
INTRO_LINES = (
    JOKE_ZH,
    JOKE_EN,
    MONEY_ZH,
    MONEY_EN,
    REAL_ZH,
    REAL_EN,
    MALWARE_ZH,
    MALWARE_EN,
)

INTRO = "\n".join(INTRO_LINES)
