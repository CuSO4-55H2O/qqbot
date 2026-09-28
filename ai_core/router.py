"""智能路由：把"自然语言 → 某个 bot 功能"做成单步 LLM 判定。

设计约定：
- 单步：模型判一次 {target, trigger}，由调用方（FeatureSmartRouter）执行一次，无循环。
- 判定本身**不计入用户 token 配额**（配额由被调用的功能自己算）。
- trigger 必须是原功能"认得"的精确触发串。
- 判不出 → target='null'，调用方静默。

功能集合与各自的说明文字都来自 `constant.FEATURE_MANIFEST`，这里不再手写一份——
原先「加一个可路由功能要同改四处」的第四处就是本文件。
"""

from __future__ import annotations

import asyncio
import json
import re

from ai_core.llm import build_chat
from constant import LLM_TARGETS, ROUTABLE_SPECS

_ROUTE_TIMEOUT = 20

SYSTEM = (
    "你是 QQ 机器人的意图路由。用户发来一句普通消息，你判断它想触发机器人的哪个功能，只输出 JSON。\n"
    '输出格式：{"target": "...", "trigger": "..."}\n'
    "target 只能从下面给的集合里选；trigger 是该功能真正认得的精确触发句（原样会去执行的那句）。\n"
    "拿不准、或者只是闲聊（没有想用机器人功能）时：target 必须为 null，trigger 为空串。"
)


def _feature_lines(image_keys: list[str], in_group: bool) -> list[str]:
    """按 llm_order 排出各功能的说明行；image 那行要填上当前可用关键词。"""
    image_line = "、".join(image_keys) if image_keys else "（无）"
    return [
        spec.llm_doc.format(image_keys=image_line)
        for spec in ROUTABLE_SPECS
        if in_group or not spec.llm_group_only
    ]


def _build_user(text: str, *, in_group: bool, chat_allowed: bool,
                image_keys: list[str]) -> str:
    parts = [
        "功能说明：",
        *_feature_lines(image_keys, in_group),
    ]
    if not chat_allowed:
        parts.append("注意：本条不算点名机器人，所以 **禁止选 chat**。")
    parts.append("")
    parts.append("判断规则：有明确功能意图才给该功能；点名机器人才给 chat；群内问历史才给 rag；")
    parts.append("否则 null（别硬凑）。trigger 必须能被原功能直接执行，不要加工描述。")
    parts.append("")
    parts.append("示例：")
    parts.append('用户：搁浅的死鲸鱼 -> {"target":"image","trigger":"死鲸鱼"}')
    parts.append('用户：生成一个六面骰 -> {"target":"dice","trigger":"d6"}')
    parts.append('用户：来个漂流瓶 -> {"target":"bottle","trigger":"捞漂流瓶"}')
    parts.append('用户：以前我们聊过那家店在哪 -> {"target":"rag","trigger":""}')
    parts.append('用户（点名）：ai 掷两个骰子 -> {"target":"chat","trigger":""}')
    parts.append('用户：哈哈哈哈笑死 -> {"target":"null","trigger":""}')
    parts.append("")
    parts.append("用户消息：")
    parts.append(text)
    return "\n".join(parts)


def _extract_target(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        m = re.search(r"\{.*\}", raw, re.S)
        raw = m.group(0) if m else ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, dict):
        return {}
    return {
        "target": str(data.get("target") or "").strip().lower(),
        "trigger": str(data.get("trigger") or "").strip(),
    }


_ALLOWED = set(LLM_TARGETS) | {"null"}


async def smart_route(text: str, *, in_group: bool, chat_allowed: bool,
                      image_keys: list[str], now: float | None = None) -> dict:
    """单步判定。返回 {target, trigger}；任何异常/超时 → {target:'null', trigger:''}。"""
    if not text:
        return {"target": "null", "trigger": ""}
    user = _build_user(text, in_group=in_group, chat_allowed=chat_allowed,
                       image_keys=image_keys)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        llm = build_chat(request_timeout=_ROUTE_TIMEOUT)
        resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=_ROUTE_TIMEOUT)
        content = getattr(resp, "content", "") or ""
        content = content if isinstance(content, str) else str(content)
        out = _extract_target(content)
    except Exception:
        return {"target": "null", "trigger": ""}

    target = out.get("target")
    if target not in _ALLOWED:
        return {"target": "null", "trigger": ""}
    # 场景约束兜底：rag 需要群、chat 需要点名；不在场景内一律降级 null
    if target == "rag" and not in_group:
        target = "null"
    if target == "chat" and not chat_allowed:
        target = "null"
    if target in ("image", "dice", "bottle", "capoo", "hsd", "op") and not out.get("trigger"):
        target = "null"
    return {"target": target, "trigger": out.get("trigger", "")}
