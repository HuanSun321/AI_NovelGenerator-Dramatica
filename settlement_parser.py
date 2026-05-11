# settlement_parser.py
# -*- coding: utf-8 -*-
"""
结算表解析器 -- 从章节文本中提取结构化状态变更。
从 Dramatica-Flow 的 PostWriteSettlement 机制移植并适配。

Copyright (c) dramatica-flow contributors - MIT License
本文件在 AGPL-3.0 项目中使用，遵守两种许可证的要求。
"""
from __future__ import annotations
import json
import logging
import re
from narrative_manager import NarrativeManager

logging.basicConfig(
    filename='app.log',
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

SETTLEMENT_PROMPT = """\
你是一个专业的小说编辑助手。请从以下章节正文中提取结构化的"写后结算表"。

章节号：第{chapter_number}章
出场角色：{character_names}

章节正文：
{chapter_text}

请提取以下信息，以严格的 JSON 格式返回（不要包含任何其他文字）：

```json
{{
    "emotional_changes": [
        {{"character_id": "角色名", "emotion": "情感词", "intensity": 7, "trigger": "触发原因"}}
    ],
    "relationship_changes": [
        {{"char_a": "角色A", "char_b": "角色B", "delta": 20, "reason": "变化原因"}}
    ],
    "new_hooks": [
        {{"type": "foreshadow", "description": "伏笔描述"}}
    ],
    "resolved_hooks": [
        "已回收的伏笔描述（如果本章中回收了之前埋设的伏笔）"
    ],
    "info_revealed": [
        {{"character_id": "角色名", "info_key": "信息标识", "content": "信息内容", "source": "witnessed"}}
    ],
    "causal_links": [
        {{"cause": "触发原因", "event": "发生了什么", "consequence": "导致什么后果", "decisions": [{{"character_id": "角色名", "decision": "决策内容"}}], "triggered_events": ["可能触发的后续事件"]}}
    ]
}}
```

提取规则：
1. emotional_changes：提取角色在本章中的情感变化，intensity 1-10
2. relationship_changes：提取角色间关系的变化，delta 为变化量（-100到100的整数）
3. new_hooks：提取本章中新埋设的伏笔、悬念、承诺、冲突
4. resolved_hooks：如果本章回收了之前埋设的伏笔，列出其描述
5. info_revealed：提取角色在本章中新获知的信息，source 为 witnessed/hearsay/deduced/document
6. causal_links：提取本章中的关键因果关系（2-3条）

如果某个字段没有对应内容，返回空列表 []。
仅返回 JSON，不要包含任何解释。
"""


def _extract_character_names(character_state_text: str) -> list[str]:
    """从 character_state.txt 的树形格式中提取角色名"""
    names = []
    for line in character_state_text.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('│') and not stripped.startswith('├') and not stripped.startswith('└'):
            if '：' in stripped:
                name = stripped.split('：')[0].strip()
                if name and len(name) < 20 and not name.startswith('#'):
                    names.append(name)
            elif ':' in stripped:
                name = stripped.split(':')[0].strip()
                if name and len(name) < 20 and not name.startswith('#'):
                    names.append(name)
    return list(dict.fromkeys(names))  # 去重保序


def _safe_parse_json(text: str) -> dict:
    """安全解析 LLM 输出的 JSON"""
    text = text.strip()
    # 尝试提取 ```json ... ``` 块
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试找到第一个 { 和最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    logging.warning("Failed to parse settlement JSON from LLM output")
    return {}


class SettlementParser:
    """
    从章节文本中提取结构化状态变更。
    对应 Dramatica-Flow 的 PostWriteSettlement 机制。
    """

    def __init__(self, llm_adapter):
        self.llm_adapter = llm_adapter

    def extract_settlement(
        self, chapter_text: str, chapter_number: int,
        character_names: list[str]
    ) -> dict:
        """
        调用 LLM 从章节正文中提取结算表。
        失败时返回空结构，不阻塞主流程。
        """
        names_str = "、".join(character_names) if character_names else "未知"
        # 限制章节文本长度防止上下文溢出
        max_chapter_chars = 8000
        if len(chapter_text) > max_chapter_chars:
            chapter_text = chapter_text[:max_chapter_chars] + "\n...（文本截断）"

        prompt = SETTLEMENT_PROMPT.format(
            chapter_number=chapter_number,
            character_names=names_str,
            chapter_text=chapter_text,
        )

        try:
            response = self.llm_adapter.invoke(prompt)
            if not response:
                logging.warning("Settlement extraction: empty LLM response")
                return {}
            result = _safe_parse_json(response)
            logging.info(f"Settlement extracted for Ch.{chapter_number}: {json.dumps(result, ensure_ascii=False)[:200]}")
            return result
        except Exception as e:
            logging.error(f"Settlement extraction failed: {e}")
            return {}

    def apply_to_manager(
        self, settlement: dict, manager: NarrativeManager,
        chapter: int
    ) -> None:
        """将结算表应用到 NarrativeManager"""
        if not settlement:
            return

        # 情感变化
        for ec in settlement.get("emotional_changes", []):
            cid = ec.get("character_id", "")
            if cid:
                manager.record_emotion(
                    character_id=cid,
                    emotion=ec.get("emotion", "未知"),
                    intensity=int(ec.get("intensity", 5)),
                    chapter=chapter,
                    trigger=ec.get("trigger", ""),
                )

        # 关系变化
        for rc in settlement.get("relationship_changes", []):
            char_a = rc.get("char_a", "")
            char_b = rc.get("char_b", "")
            if char_a and char_b:
                manager.update_relationship(
                    char_a=char_a,
                    char_b=char_b,
                    delta=int(rc.get("delta", 0)),
                    chapter=chapter,
                    reason=rc.get("reason", ""),
                )

        # 新开伏笔
        for hook_desc in settlement.get("new_hooks", []):
            if isinstance(hook_desc, dict):
                htype = hook_desc.get("type", "foreshadow")
                desc = hook_desc.get("description", "")
            else:
                htype = "foreshadow"
                desc = str(hook_desc)
            if desc:
                manager.open_hook(
                    hook_type=htype,
                    description=desc,
                    chapter=chapter,
                )

        # 回收伏笔（通过描述匹配）
        for hook_desc in settlement.get("resolved_hooks", []):
            desc = str(hook_desc)
            for h in manager.get_open_hooks():
                if desc and (desc in h["description"] or h["description"] in desc):
                    manager.resolve_hook(h["id"], chapter)
                    break

        # 信息揭示
        for info in settlement.get("info_revealed", []):
            cid = info.get("character_id", "")
            info_key = info.get("info_key", "")
            if cid and info_key:
                manager.learn_info(
                    character_id=cid,
                    info_key=info_key,
                    content=info.get("content", ""),
                    chapter=chapter,
                    source=info.get("source", "witnessed"),
                )

        # 因果链
        for cl in settlement.get("causal_links", []):
            cause = cl.get("cause", "")
            event = cl.get("event", "")
            consequence = cl.get("consequence", "")
            if cause and event and consequence:
                decisions = cl.get("decisions", [])
                manager.add_causal_link(
                    chapter=chapter,
                    cause=cause,
                    event=event,
                    consequence=consequence,
                    decisions=decisions,
                )
