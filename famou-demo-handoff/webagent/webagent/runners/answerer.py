"""
runners/answerer.py — B2 澄清阶段的回答策略

提供 HumanAnswerer（终端交互）和 ApiAnswerer（LLM 自动回答）两种实现。
"""

from __future__ import annotations

from typing import Protocol


class Answerer(Protocol):
    """回答澄清问题的接口。"""

    def answer(self, question: str) -> str: ...


class HumanAnswerer:
    """终端交互回答。"""

    def answer(self, question: str) -> str:
        try:
            text = input("请输入回答（直接回车=使用默认值）: ").strip()
        except EOFError:
            text = ""
        if not text:
            text = "使用默认值，继续。"
            print(f"[B2] 空回答，发送: {text!r}")
        return text


class DefaultValueAnswerer:
    """所有澄清问题一律回答「使用默认值」，用作 baseline。"""

    def answer(self, question: str) -> str:
        return "使用默认值，继续。"


ANSWERER_STYLES = {
    "default": (
        "回答要求：\n"
        "- 以业务负责人的口吻回答，只给出答案本身，不解释理由，不重复问题\n"
        "- 如有多个问题，每个问题单独一行直接作答\n"
        "- 不要主动提及评估方式、评分公式、优化目标的具体权重等技术实现细节；"
        "如对方追问，可给出业务层面的定性说明，但不要给出具体数学公式或权重数值\n"
        "- 如所有信息均未覆盖，给出合理的业务默认值即可"
    ),
    "minimal": (
        "回答要求：\n"
        "- 你是一个非常忙碌的业务负责人，回答尽量简短，能一句话说清楚就不要两句\n"
        "- 只给核心结论，不展开解释，不给选项，不反问\n"
        "- 如有多个问题，每个问题用一行简短回答\n"
        "- 不要主动提及评估方式、评分公式等技术细节\n"
        "- 如信息未覆盖，直接给一个默认值，不要说「建议」「可以考虑」"
    ),
}


class ApiAnswerer:
    """基于 LLM + 背景知识的自动回答器，带上下文累积。"""

    def __init__(
        self,
        background: str,
        *,
        instruction_text: str = "",
        information: str = "",
        style: str = "default",
        model: str | None = None,
        base_url: str | None = None,
        auth_token: str | None = None,
    ):
        from .bench_config import (
            ANSWERER_API_BASE_URL,
            ANSWERER_AUTH_TOKEN,
            ANSWERER_MODEL,
        )

        self.model = model or ANSWERER_MODEL
        self.style = style
        self._base_url = base_url or ANSWERER_API_BASE_URL
        self._auth_token = auth_token or ANSWERER_AUTH_TOKEN

        if not self._auth_token:
            raise ValueError(
                "answerer auth_token 未配置。"
                "请在 bench_config.toml [answerer] 中设置 auth_token"
            )

        if style not in ANSWERER_STYLES:
            valid = ", ".join(ANSWERER_STYLES)
            raise ValueError(f"Unknown answerer style: '{style}'. Valid: {valid}")

        # ── 拼装 system prompt ──
        # 三个知识源同级：<instruction> + <background>(gt.json) + <information>
        # answerer 扮演业务方，不主动透露评估公式等技术细节

        knowledge_parts: list[str] = []
        if instruction_text:
            knowledge_parts.append(
                f"<instruction>\n{instruction_text}\n</instruction>"
            )
        knowledge_parts.append(f"<background>\n{background}\n</background>")
        if information:
            knowledge_parts.append(f"<information>\n{information}\n</information>")

        knowledge_block = "\n\n".join(knowledge_parts)

        style_instructions = ANSWERER_STYLES[style]

        self._system = (
            "你是这个业务场景的负责人，正在回答技术团队对需求的澄清问题。\n"
            "以下三块内容都是你掌握的业务知识，回答前请**逐块通读并交叉查阅**，"
            "尤其是 <information> 通常包含具体数值、字段名、坐标、阈值、约束细节——"
            "对方提到 schema、参数、阈值、坐标、公式等具体问题时，必须先到 <information> 里查找现成答案，"
            "不要回答\"我来提供\"或当场拍板：\n\n"
            f"{knowledge_block}\n\n"
            "⚠️ 注意：上述任何位置都可能包含评估公式、评分权重、惩罚系数等内部技术细节——"
            "不要主动向技术团队透露这些；如对方追问，可给出业务层面的定性说明，但不要给具体数学公式或权重数值。\n\n"
            "🔒 **回答程序硬规则**（每个问题都必须按这三步走）：\n\n"
            "**步骤 1：先查 information**\n"
            "在选答案/写答案之前，先到 <information> 中找该问题对应的原文。\n"
            "你的回复**必须以一行 \"查 information：<原文摘录 / 未找到>\" 开头**，再给最终答案。\n\n"
            "**步骤 2：用 information 真值对比选项**\n"
            "- 若 information 真值与某选项完全一致 → 选该选项\n"
            "- 若 information 真值与所有选项都不完全一致 → 必须选 \"其他（请描述）\" 并把 information 原文中的范围/数值/字段名照抄进去\n"
            "- 若 information 未提及该问题 → 才能凭 instruction 判断\n\n"
            "**步骤 3：禁止用弱化词代替具体数值**\n"
            "禁止回答 \"不限定 / 不计 / 不需要 / 灵活 / 由模型自行决定\"，"
            "除非 information 原文里就明确这样写。具体数值、范围、字段名必须照搬 information。\n\n"
            "选择含「请描述」的选项时，必须在选项名后给出具体内容；若无新信息可补充，选否定选项而非空描述。\n\n"
            f"{style_instructions}"
        )
        self._history: list[dict] = []
        self._client = None

    def _get_client(self):
        if self._client is None:
            import os
            import anthropic

            # 临时清除环境变量，防止 SDK 读到 ANTHROPIC_API_KEY 后
            # 同时发送 X-Api-Key 和 Authorization 两个 header，导致千帆 401
            saved = os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                self._client = anthropic.Anthropic(
                    auth_token=self._auth_token,
                    base_url=self._base_url,
                )
            finally:
                if saved is not None:
                    os.environ["ANTHROPIC_API_KEY"] = saved
        return self._client

    def answer(self, question: str) -> str:
        self._history.append({"role": "user", "content": question})

        message = self._get_client().messages.create(
            model=self.model,
            max_tokens=4096,
            system=self._system,
            messages=self._history,
        )

        text = ""
        for block in message.content:
            if hasattr(block, "text"):
                text = block.text.strip()
                break
        if not text:
            raise ValueError(f"API 响应中未找到文本内容: {message.content}")

        self._history.append({"role": "assistant", "content": text})
        return text
