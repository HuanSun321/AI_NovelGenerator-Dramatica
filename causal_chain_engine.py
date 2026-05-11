# causal_chain_engine.py
# -*- coding: utf-8 -*-
"""
因果链引擎 -- 从章节文本中提取因果关系、追溯上游、检查一致性。
从 Dramatica-Flow 的 NarrativeEngine.extract_causal_links() 移植并扩展。

Copyright (c) dramatica-flow contributors - MIT License
本文件在 AGPL-3.0 项目中使用，遵守两种许可证的要求。
"""
from __future__ import annotations
import json
import logging
import os
import re
from narrative_manager import NarrativeManager

logging.basicConfig(
    filename='app.log',
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ── 因果链提取提示词 ─────────────────────────────────────────

CAUSAL_EXTRACTION_PROMPT = """\
你是一个专业的叙事分析师，专注于分析小说中的因果结构。
请从以下章节正文中提取 2-5 条关键因果链。

章节号：第{chapter_number}章
出场角色：{character_names}

章节正文：
{chapter_text}

每条因果链必须回答以下四个问题：
- 因（cause）：什么触发了这个事件？
- 事（event）：发生了什么？
- 果（consequence）：导致了什么直接后果？
- 决策（affected_decisions）：哪些角色因此做出了什么决策？

请以严格的 JSON 数组格式返回（不要包含任何其他文字）：

```json
[
    {{
        "cause": "触发原因",
        "event": "发生了什么",
        "consequence": "导致什么后果",
        "affected_decisions": [
            {{"character_id": "角色名", "decision": "该角色因此做出的决策"}}
        ],
        "triggered_events": ["可能触发的后续事件描述"]
    }}
]
```

提取规则：
1. 聚焦于推动剧情发展的核心因果关系，忽略日常琐碎动作
2. 每条链应该是完整的"因为A，所以发生了B，导致C"
3. affected_decisions 记录角色因该事件做出的关键选择
4. triggered_events 用自然语言描述可能的下游影响
5. 如果章节内容较短或因果关系简单，2条即可

仅返回 JSON 数组，不要包含任何解释。
"""

# ── 因果一致性检查提示词 ─────────────────────────────────────

CAUSAL_CONSISTENCY_PROMPT = """\
请检查以下新章节内容是否与已有的因果链存在逻辑矛盾。

已有因果链（最近{chain_count}条）：
{existing_chain}

新章节内容：
{chapter_text}

请检查：
1. 新事件是否与已有因果的"果"产生矛盾？（例如：已记录"角色A死亡"的后果，但新章节中角色A仍然活跃）
2. 新事件的"因"是否在已有因果链中有合理铺垫？
3. 是否存在因果断裂——某个重要结果缺少原因，或某个重要原因缺少结果？

如果存在矛盾或不一致，请具体说明；如果逻辑一致，请返回"因果链逻辑一致"。
"""


class CausalChainEngine:
    """
    因果链引擎。
    提取、追溯、检查小说中的因果关系链。
    """

    def __init__(self, llm_adapter):
        self.llm_adapter = llm_adapter

    def extract_from_chapter(
        self,
        chapter_text: str,
        chapter_number: int,
        character_names: list[str],
    ) -> list[dict]:
        """
        从章节文本中提取因果链。
        返回 list[dict]，每个 dict 包含 cause/event/consequence/affected_decisions/triggered_events。
        失败时返回空列表，不阻塞主流程。
        """
        names_str = "、".join(character_names) if character_names else "未知"
        # 截断防止上下文溢出
        max_chars = 6000
        truncated = chapter_text
        if len(truncated) > max_chars:
            truncated = truncated[:max_chars] + "\n...（截断）"

        prompt = CAUSAL_EXTRACTION_PROMPT.format(
            chapter_number=chapter_number,
            character_names=names_str,
            chapter_text=truncated,
        )

        try:
            response = self.llm_adapter.invoke(prompt)
            if not response:
                logging.warning(f"CausalChainEngine: empty response for Ch.{chapter_number}")
                return []
            links = self._parse_links(response, chapter_number)
            logging.info(f"CausalChainEngine: extracted {len(links)} links from Ch.{chapter_number}")
            return links
        except Exception as e:
            logging.error(f"CausalChainEngine.extract_from_chapter failed: {e}")
            return []

    def get_upstream_context(
        self,
        manager: NarrativeManager,
        event_description: str,
        max_depth: int = 3,
        max_chars: int = 1000,
    ) -> str:
        """
        根据事件描述，向上追溯因果链，生成上游上下文。
        用于写作时提供因果背景。
        """
        chain = manager.state.causal_chain
        if not chain:
            return "（暂无因果链记录）"

        # 简单匹配：找与 event_description 关键词重叠度最高的因果链
        keywords = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', event_description))
        if not keywords:
            return self._format_chain_tail(chain, max_chars)

        scored = []
        for cl in chain:
            text = f"{cl.get('cause','')}{cl.get('event','')}{cl.get('consequence','')}"
            overlap = len(keywords & set(re.findall(r'[\w\u4e00-\u9fff]{2,}', text)))
            scored.append((overlap, cl))
        scored.sort(key=lambda x: x[0], reverse=True)

        # 取最相关的节点及其上游
        relevant = [cl for score, cl in scored[:max_depth] if score > 0]
        if not relevant:
            return self._format_chain_tail(chain, max_chars)

        lines = []
        for cl in relevant:
            lines.append(
                f"Ch.{cl['chapter']}：{cl['event']}\n"
                f"  因：{cl['cause']}\n"
                f"  果：{cl['consequence']}"
            )
            if cl.get("affected_decisions"):
                for d in cl["affected_decisions"]:
                    lines.append(f"  → {d.get('character_id', '?')} 决定：{d.get('decision', '?')}")
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def check_causal_consistency(
        self,
        chapter_text: str,
        manager: NarrativeManager,
        max_chain_count: int = 10,
    ) -> str:
        """
        检查新章节内容是否与已有因果链一致。
        返回检查结果文本。失败时返回错误提示，不阻塞。
        """
        chain = manager.state.causal_chain
        if not chain:
            return "（无已有因果链，跳过因果一致性检查）"

        recent = chain[-max_chain_count:]
        chain_text = "\n".join(
            f"Ch.{cl['chapter']}：因 {cl['cause']} → 事 {cl['event']} → 果 {cl['consequence']}"
            for cl in recent
        )

        max_chars = 6000
        truncated = chapter_text
        if len(truncated) > max_chars:
            truncated = truncated[:max_chars] + "\n...（截断）"

        prompt = CAUSAL_CONSISTENCY_PROMPT.format(
            chain_count=len(recent),
            existing_chain=chain_text,
            chapter_text=truncated,
        )

        try:
            response = self.llm_adapter.invoke(prompt)
            if not response:
                return "因果一致性检查无回复"
            return response
        except Exception as e:
            logging.error(f"CausalChainEngine.check_causal_consistency failed: {e}")
            return f"因果一致性检查失败：{e}"

    def backfill_from_existing_chapters(
        self,
        filepath: str,
        character_names: list[str],
    ) -> int:
        """
        批量回填已有章节的因果链。
        读取 chapters/ 目录下的所有章节文件，逐一提取因果链。
        返回成功提取的章节数。
        """
        chapters_dir = os.path.join(filepath, "chapters")
        if not os.path.isdir(chapters_dir):
            logging.warning(f"CausalChainEngine: chapters dir not found: {chapters_dir}")
            return 0

        manager = NarrativeManager(filepath)
        filled = 0

        # 找出已有因果链的章节号，避免重复提取
        existing_chapters = {cl["chapter"] for cl in manager.state.causal_chain}

        for fname in sorted(os.listdir(chapters_dir)):
            if not fname.startswith("chapter_") or not fname.endswith(".txt"):
                continue
            try:
                ch_num = int(fname.replace("chapter_", "").replace(".txt", ""))
            except ValueError:
                continue

            if ch_num in existing_chapters:
                continue

            fpath = os.path.join(chapters_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                continue

            links = self.extract_from_chapter(text, ch_num, character_names)
            for link in links:
                manager.add_causal_link(
                    chapter=ch_num,
                    cause=link.get("cause", ""),
                    event=link.get("event", ""),
                    consequence=link.get("consequence", ""),
                    decisions=link.get("affected_decisions", []),
                )
            if links:
                filled += 1
                logging.info(f"CausalChainEngine: backfilled Ch.{ch_num} with {len(links)} links")

        if filled > 0:
            manager.save()
            manager.sync_to_text_files()
        return filled

    # ── 内部方法 ──────────────────────────────────────────────

    def _parse_links(self, response: str, chapter_number: int) -> list[dict]:
        """解析 LLM 返回的因果链 JSON"""
        text = response.strip()
        # 提取 ```json ... ``` 块
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试找 [ ... ]
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1:
                try:
                    data = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    logging.warning("CausalChainEngine: failed to parse JSON from LLM output")
                    return []
            else:
                return []

        if not isinstance(data, list):
            return []

        # 验证和清理
        valid = []
        for item in data:
            if not isinstance(item, dict):
                continue
            cause = item.get("cause", "").strip()
            event = item.get("event", "").strip()
            consequence = item.get("consequence", "").strip()
            if cause and event and consequence:
                valid.append({
                    "cause": cause,
                    "event": event,
                    "consequence": consequence,
                    "affected_decisions": item.get("affected_decisions", []),
                    "triggered_events": item.get("triggered_events", []),
                })
        return valid

    def _format_chain_tail(self, chain: list[dict], max_chars: int) -> str:
        """格式化最近几条因果链"""
        recent = chain[-5:]
        lines = []
        for cl in recent:
            lines.append(
                f"Ch.{cl['chapter']}：{cl['event']}\n"
                f"  因：{cl['cause']}\n"
                f"  果：{cl['consequence']}"
            )
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text
