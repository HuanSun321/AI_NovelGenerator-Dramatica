# narrative_state.py
# -*- coding: utf-8 -*-
"""
从 Dramatica-Flow 移植的核心叙事状态数据结构。
原始来源：dramatica-flow/core/types/state.py (MIT License)
适配为 AI_NovelGenerator 的文本文件 + JSON 双轨存储。

Copyright (c) dramatica-flow contributors - MIT License
本文件在 AGPL-3.0 项目中使用，遵守两种许可证的要求。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import os


# ── 枚举定义 ──────────────────────────────────────────────────

class RelationshipType(str, Enum):
    ALLY = "ally"
    ENEMY = "enemy"
    NEUTRAL = "neutral"
    FAMILY = "family"
    MENTOR = "mentor"
    RIVAL = "rival"
    ROMANTIC = "romantic"


class HookType(str, Enum):
    FORESHADOW = "foreshadow"
    PROMISE = "promise"
    MYSTERY = "mystery"
    CONFLICT = "conflict"


class HookStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class EmotionalSnapshot:
    character_id: str
    emotion: str
    intensity: int          # 1-10
    chapter: int
    trigger: str


@dataclass
class RelationshipDelta:
    chapter: int
    delta: int
    reason: str


@dataclass
class RelationshipRecord:
    character_a: str
    character_b: str
    type: str               # RelationshipType value
    strength: int           # -100 to 100
    known_to: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str:
        return ":".join(sorted([self.character_a, self.character_b]))


@dataclass
class KnownInfoRecord:
    character_id: str
    info_key: str
    content: str
    learned_in_chapter: int
    source: str             # "witnessed"/"hearsay"/"deduced"/"document"


@dataclass
class Hook:
    id: str
    type: str               # HookType value
    description: str
    planted_in_chapter: int
    expected_resolution_range: list[int]  # [earliest, latest]
    status: str = "open"    # HookStatus value
    resolved_in_chapter: int | None = None


@dataclass
class AffectedDecision:
    character_id: str
    decision: str


@dataclass
class CausalLink:
    id: str
    chapter: int
    cause: str
    event: str
    consequence: str
    affected_decisions: list[dict] = field(default_factory=list)
    triggered_events: list[str] = field(default_factory=list)


# ── 聚合状态 ──────────────────────────────────────────────────

@dataclass
class NarrativeState:
    """聚合所有叙事追踪状态，对应 Dramatica-Flow 的 WorldState 精简版"""
    current_chapter: int = 0
    emotional_snapshots: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    known_info: list[dict] = field(default_factory=list)
    pending_hooks: list[dict] = field(default_factory=list)
    causal_chain: list[dict] = field(default_factory=list)


# ── 工具函数 ──────────────────────────────────────────────────

def load_narrative_state(filepath: str) -> NarrativeState:
    """从 narrative_state.json 加载，不存在则返回空状态"""
    state_file = os.path.join(filepath, "narrative_state.json")
    if not os.path.exists(state_file):
        return NarrativeState()
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return NarrativeState(
            current_chapter=data.get("current_chapter", 0),
            emotional_snapshots=data.get("emotional_snapshots", []),
            relationships=data.get("relationships", []),
            known_info=data.get("known_info", []),
            pending_hooks=data.get("pending_hooks", []),
            causal_chain=data.get("causal_chain", []),
        )
    except (json.JSONDecodeError, KeyError):
        return NarrativeState()


def save_narrative_state(state: NarrativeState, filepath: str) -> None:
    """保存到 narrative_state.json"""
    state_file = os.path.join(filepath, "narrative_state.json")
    data = {
        "current_chapter": state.current_chapter,
        "emotional_snapshots": state.emotional_snapshots,
        "relationships": state.relationships,
        "known_info": state.known_info,
        "pending_hooks": state.pending_hooks,
        "causal_chain": state.causal_chain,
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_RELATIONSHIP_KEYWORDS = {
    "对手": "rival", "敌对": "enemy", "敌人": "enemy",
    "盟友": "ally", "同伴": "ally", "朋友": "ally",
    "师徒": "mentor", "导师": "mentor", "师父": "mentor",
    "恋人": "romantic", "情侣": "romantic", "爱人": "romantic",
    "家人": "family", "父子": "family", "母子": "family",
    "兄弟": "family", "姐妹": "family", "亲属": "family",
    "怀疑": "skeptic", "质疑": "skeptic",
}


def parse_relationship_type(text: str) -> str:
    """从中文关系描述推断 RelationshipType"""
    text_lower = text.lower()
    for keyword, rel_type in _RELATIONSHIP_KEYWORDS.items():
        if keyword in text_lower:
            return rel_type
    return "neutral"
