# narrative_manager.py
# -*- coding: utf-8 -*-
"""
叙事状态管理器 -- 读写 narrative_state.json + 生成可读文本文件。
从 Dramatica-Flow 的 StateManager 移植并适配。

Copyright (c) dramatica-flow contributors - MIT License
本文件在 AGPL-3.0 项目中使用，遵守两种许可证的要求。
"""
from __future__ import annotations
import os
import uuid
from narrative_state import (
    NarrativeState, EmotionalSnapshot, RelationshipRecord,
    KnownInfoRecord, Hook, CausalLink, AffectedDecision,
    RelationshipType, HookType, HookStatus,
    load_narrative_state, save_narrative_state, parse_relationship_type,
)


class NarrativeManager:
    """
    叙事状态管理器。
    双轨存储：narrative_state.json（权威数据源）+ 可读 .txt 文件（视图）。
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.state: NarrativeState = load_narrative_state(filepath)

    def save(self) -> None:
        save_narrative_state(self.state, self.filepath)

    # ── 原子操作 ──────────────────────────────────────────────

    def record_emotion(
        self, character_id: str, emotion: str, intensity: int,
        chapter: int, trigger: str
    ) -> None:
        snap = {
            "character_id": character_id,
            "emotion": emotion,
            "intensity": max(1, min(10, intensity)),
            "chapter": chapter,
            "trigger": trigger,
        }
        self.state.emotional_snapshots.append(snap)
        self.save()

    def update_relationship(
        self, char_a: str, char_b: str, delta: int,
        chapter: int, reason: str
    ) -> None:
        key = ":".join(sorted([char_a, char_b]))
        rel = None
        for r in self.state.relationships:
            rkey = ":".join(sorted([r["character_a"], r["character_b"]]))
            if rkey == key:
                rel = r
                break
        if rel is None:
            rel = {
                "character_a": char_a,
                "character_b": char_b,
                "type": "neutral",
                "strength": 0,
                "known_to": [],
                "history": [],
            }
            self.state.relationships.append(rel)
        rel["strength"] = max(-100, min(100, rel["strength"] + delta))
        rel["history"].append({
            "chapter": chapter, "delta": delta, "reason": reason
        })
        if rel["strength"] >= 50:
            rel["type"] = "ally"
        elif rel["strength"] <= -50:
            rel["type"] = "enemy"
        else:
            rel["type"] = "neutral"
        self.save()

    def learn_info(
        self, character_id: str, info_key: str, content: str,
        chapter: int, source: str = "witnessed"
    ) -> None:
        if self.character_knows(character_id, info_key):
            return
        self.state.known_info.append({
            "character_id": character_id,
            "info_key": info_key,
            "content": content,
            "learned_in_chapter": chapter,
            "source": source,
        })
        self.save()

    def open_hook(
        self, hook_type: str, description: str, chapter: int,
        resolution_range: tuple[int, int] | None = None
    ) -> str:
        hook_id = f"hook_{uuid.uuid4().hex[:8]}"
        if resolution_range is None:
            resolution_range = (chapter + 3, chapter + 25)
        hook = {
            "id": hook_id,
            "type": hook_type,
            "description": description,
            "planted_in_chapter": chapter,
            "expected_resolution_range": list(resolution_range),
            "status": "open",
            "resolved_in_chapter": None,
        }
        self.state.pending_hooks.append(hook)
        self.save()
        return hook_id

    def resolve_hook(self, hook_id: str, chapter: int) -> None:
        for h in self.state.pending_hooks:
            if h["id"] == hook_id:
                h["status"] = "resolved"
                h["resolved_in_chapter"] = chapter
                break
        self.save()

    def add_causal_link(
        self, chapter: int, cause: str, event: str, consequence: str,
        decisions: list[dict] | None = None
    ) -> None:
        link_id = f"cl_{uuid.uuid4().hex[:8]}"
        link = {
            "id": link_id,
            "chapter": chapter,
            "cause": cause,
            "event": event,
            "consequence": consequence,
            "affected_decisions": decisions or [],
            "triggered_events": [],
        }
        self.state.causal_chain.append(link)
        self.save()

    # ── 查询 ──────────────────────────────────────────────────

    def get_latest_emotion(self, character_id: str) -> dict | None:
        latest = None
        for snap in self.state.emotional_snapshots:
            if snap["character_id"] == character_id:
                if latest is None or snap["chapter"] > latest["chapter"]:
                    latest = snap
        return latest

    def get_relationship(self, char_a: str, char_b: str) -> dict | None:
        key = ":".join(sorted([char_a, char_b]))
        for r in self.state.relationships:
            rkey = ":".join(sorted([r["character_a"], r["character_b"]]))
            if rkey == key:
                return r
        return None

    def get_open_hooks(self) -> list[dict]:
        return [h for h in self.state.pending_hooks if h["status"] == "open"]

    def get_overdue_hooks(self, current_chapter: int) -> list[dict]:
        return [
            h for h in self.get_open_hooks()
            if current_chapter > h["expected_resolution_range"][1]
        ]

    def character_knows(self, character_id: str, info_key: str) -> bool:
        return any(
            i["character_id"] == character_id and i["info_key"] == info_key
            for i in self.state.known_info
        )

    # ── 文本导出（供 LLM 上下文注入）──────────────────────────

    def get_emotional_context(self, max_chars: int = 600) -> str:
        if not self.state.emotional_snapshots:
            return "（暂无情感记录）"
        chars: dict[str, list[dict]] = {}
        for snap in self.state.emotional_snapshots:
            cid = snap["character_id"]
            chars.setdefault(cid, []).append(snap)
        lines = []
        for cid, snaps in chars.items():
            recent = snaps[-5:]
            lines.append(f"【{cid}】")
            for s in recent:
                lines.append(
                    f"  Ch.{s['chapter']} {s['emotion']}（{s['intensity']}/10）"
                    f"：{s['trigger']}"
                )
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def get_relationship_context(self, max_chars: int = 500) -> str:
        if not self.state.relationships:
            return "（暂无关系记录）"
        lines = []
        for r in self.state.relationships:
            a, b = r["character_a"], r["character_b"]
            strength = r["strength"]
            rel_type = r["type"]
            sign = "+" if strength >= 0 else ""
            recent_reason = ""
            if r["history"]:
                last = r["history"][-1]
                recent_reason = f"（最近：{last['reason']}）"
            lines.append(f"{a} ↔ {b}：{rel_type}，强度 {sign}{strength}{recent_reason}")
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def get_hooks_context(self, max_chars: int = 400) -> str:
        open_hooks = self.get_open_hooks()
        if not open_hooks:
            return "（暂无未闭合伏笔）"
        lines = []
        for h in open_hooks:
            overdue = self.state.current_chapter > h["expected_resolution_range"][1]
            flag = " ⚠️逾期" if overdue else ""
            lines.append(
                f"[{h['id']}] {h['type']}：{h['description']} "
                f"（Ch.{h['planted_in_chapter']} 植入，"
                f"预计 Ch.{h['expected_resolution_range'][0]}-"
                f"{h['expected_resolution_range'][1]} 回收）{flag}"
            )
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def get_causal_context(self, max_chars: int = 800) -> str:
        if not self.state.causal_chain:
            return "（暂无因果链记录）"
        recent = self.state.causal_chain[-5:]
        lines = []
        for cl in recent:
            lines.append(
                f"Ch.{cl['chapter']}：{cl['event']}\n"
                f"  因：{cl['cause']}\n"
                f"  果：{cl['consequence']}"
            )
            if cl.get("affected_decisions"):
                for d in cl["affected_decisions"]:
                    lines.append(f"  → {d.get('character_id', '?')} 决定：{d.get('decision', '?')}")
            if cl.get("triggered_events"):
                for te in cl["triggered_events"]:
                    lines.append(f"  下游触发：{te}")
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def get_causal_links_for_chapter(self, chapter: int) -> list[dict]:
        """获取指定章节的所有因果链"""
        return [cl for cl in self.state.causal_chain if cl["chapter"] == chapter]

    def get_causal_links_by_character(self, character_id: str) -> list[dict]:
        """获取涉及指定角色的所有因果链（在 cause/event/consequence/decisions 中出现）"""
        results = []
        for cl in self.state.causal_chain:
            text = f"{cl.get('cause','')}{cl.get('event','')}{cl.get('consequence','')}"
            if character_id in text:
                results.append(cl)
                continue
            for d in cl.get("affected_decisions", []):
                if d.get("character_id") == character_id:
                    results.append(cl)
                    break
        return results

    def get_unresolved_consequences(self) -> list[dict]:
        """
        获取尚未被后续因果链覆盖的"果"。
        即某条链的 consequence 中的关键事件，没有在后续链的 cause 中出现。
        可用于发现因果断裂。
        """
        if len(self.state.causal_chain) < 2:
            return []
        unresolved = []
        for i, cl in enumerate(self.state.causal_chain[:-1]):
            consequence = cl.get("consequence", "")
            if not consequence:
                continue
            # 检查后续链中是否有引用此后果的
            consequence_keywords = set(
                kw for kw in consequence if len(kw) >= 2
            ) if len(consequence) < 100 else set(consequence[:50].split())
            found_reference = False
            for later_cl in self.state.causal_chain[i + 1:]:
                later_text = f"{later_cl.get('cause','')}{later_cl.get('event','')}"
                if any(kw in later_text for kw in consequence_keywords if len(kw) >= 2):
                    found_reference = True
                    break
            if not found_reference:
                unresolved.append(cl)
        return unresolved

    def get_info_boundary_context(
        self, character_id: str, max_chars: int = 400
    ) -> str:
        if not character_id:
            return "（未指定视角角色）"
        infos = [
            i for i in self.state.known_info
            if i["character_id"] == character_id
        ]
        if not infos:
            return f"{character_id} 暂无已知信息记录"
        lines = [f"【{character_id} 已知信息】"]
        for i in infos:
            lines.append(
                f"  - {i['info_key']}：{i['content']} "
                f"（来源：{i['source']}，Ch.{i['learned_in_chapter']}）"
            )
        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    # ── 文本文件持久化 ────────────────────────────────────────

    def sync_to_text_files(self) -> None:
        self._write_emotional_arcs_txt()
        self._write_relationship_matrix_txt()
        self._write_foreshadow_tracker_txt()
        self._write_causal_chain_txt()
        self._write_known_info_map_txt()

    def _write_emotional_arcs_txt(self) -> None:
        path = os.path.join(self.filepath, "emotional_arcs.txt")
        chars: dict[str, list[dict]] = {}
        for snap in self.state.emotional_snapshots:
            chars.setdefault(snap["character_id"], []).append(snap)
        lines = ["# 情感弧线\n"]
        for cid, snaps in chars.items():
            lines.append(f"\n## {cid}")
            for s in snaps:
                lines.append(
                    f"- Ch.{s['chapter']} {s['emotion']}（强度 {s['intensity']}/10）"
                    f"：{s['trigger']}"
                )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _write_relationship_matrix_txt(self) -> None:
        path = os.path.join(self.filepath, "relationship_matrix.txt")
        lines = ["# 关系网络矩阵\n"]
        if self.state.relationships:
            lines.append("\n## 活跃关系\n")
            lines.append("| 角色A | 角色B | 类型 | 强度 | 最近变化 |")
            lines.append("|---|---|---|---|---|")
            for r in self.state.relationships:
                recent = ""
                if r["history"]:
                    last = r["history"][-1]
                    sign = "+" if last["delta"] >= 0 else ""
                    recent = f"Ch.{last['chapter']}: {sign}{last['delta']}（{last['reason']}）"
                sign = "+" if r["strength"] >= 0 else ""
                lines.append(
                    f"| {r['character_a']} | {r['character_b']} "
                    f"| {r['type']} | {sign}{r['strength']} | {recent} |"
                )
            lines.append("\n## 关系历史\n")
            for r in self.state.relationships:
                if r["history"]:
                    a, b = r["character_a"], r["character_b"]
                    lines.append(f"### {a} ↔ {b}")
                    for h in r["history"]:
                        sign = "+" if h["delta"] >= 0 else ""
                        lines.append(
                            f"- Ch.{h['chapter']}: {sign}{h['delta']}（{h['reason']}）"
                        )
                    lines.append("")
        else:
            lines.append("（暂无关系记录）")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _write_foreshadow_tracker_txt(self) -> None:
        path = os.path.join(self.filepath, "foreshadow_tracker.txt")
        lines = ["# 伏笔追踪器\n"]
        open_hooks = self.get_open_hooks()
        resolved = [
            h for h in self.state.pending_hooks if h["status"] == "resolved"
        ]
        if open_hooks:
            lines.append("\n## 未闭合伏笔\n")
            lines.append("| ID | 类型 | 描述 | 植入章 | 预计回收 | 状态 |")
            lines.append("|---|---|---|---|---|---|")
            for h in open_hooks:
                r = h["expected_resolution_range"]
                overdue = self.state.current_chapter > r[1]
                flag = " ⚠️逾期" if overdue else ""
                lines.append(
                    f"| {h['id']} | {h['type']} | {h['description']} "
                    f"| Ch.{h['planted_in_chapter']} | Ch.{r[0]}-Ch.{r[1]} "
                    f"| {h['status']}{flag} |"
                )
        if resolved:
            lines.append("\n## 已回收伏笔\n")
            lines.append("| ID | 类型 | 描述 | 植入章 | 回收章 |")
            lines.append("|---|---|---|---|---|")
            for h in resolved:
                lines.append(
                    f"| {h['id']} | {h['type']} | {h['description']} "
                    f"| Ch.{h['planted_in_chapter']} | Ch.{h['resolved_in_chapter']} |"
                )
        if not open_hooks and not resolved:
            lines.append("（暂无伏笔记录）")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _write_causal_chain_txt(self) -> None:
        path = os.path.join(self.filepath, "causal_chain.txt")
        lines = ["# 因果链日志\n"]
        if not self.state.causal_chain:
            lines.append("（暂无因果链记录）")
        else:
            for cl in self.state.causal_chain:
                lines.append(f"\n## Ch.{cl['chapter']} — {cl['event']}")
                lines.append(f"- 因：{cl['cause']}")
                lines.append(f"- 果：{cl['consequence']}")
                if cl.get("affected_decisions"):
                    for d in cl["affected_decisions"]:
                        lines.append(
                            f"- → {d.get('character_id', '?')} 决定：{d.get('decision', '?')}"
                        )
                if cl.get("triggered_events"):
                    for te in cl["triggered_events"]:
                        lines.append(f"- 下游触发：{te}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _write_known_info_map_txt(self) -> None:
        path = os.path.join(self.filepath, "known_info_map.txt")
        lines = ["# 信息边界地图（谁知道什么）\n"]
        if not self.state.known_info:
            lines.append("（暂无信息边界记录）")
        else:
            chars: dict[str, list[dict]] = {}
            for info in self.state.known_info:
                chars.setdefault(info["character_id"], []).append(info)
            for cid, infos in chars.items():
                lines.append(f"\n## {cid} 知道的信息\n")
                lines.append("| 信息 | 来源 | 得知章节 |")
                lines.append("|---|---|---|")
                for i in infos:
                    lines.append(
                        f"| {i['info_key']}：{i['content']} "
                        f"| {i['source']} | Ch.{i['learned_in_chapter']} |"
                    )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
