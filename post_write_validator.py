# post_write_validator.py
# -*- coding: utf-8 -*-
"""
写后验证器 -- 零 LLM 的硬规则质量检查。
从 Dramatica-Flow 的 PostWriteValidator 移植。

Copyright (c) dramatica-flow contributors - MIT License
本文件在 AGPL-3.0 项目中使用，遵守两种许可证的要求。
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


# ── 规则常量 ──────────────────────────────────────────────────

# 规则1：AI 标记词（每3000字上限1次）
AI_MARKER_WORDS = [
    "仿佛", "忽然", "竟然", "不禁", "居然",
    "顿时", "蓦然", "霎时", "陡然",
]

# 规则2：绝对禁止句式（severity=error，触发即失败）
FORBIDDEN_PHRASES = [
    "全场震惊", "众人哗然", "所有人都惊呆了",
    "空气中弥漫着", "一股强大的气息",
]

# 规则3：元叙事 / 编剧腔
META_NARRATIVE_PATTERNS: list[tuple[str, str]] = [
    (r"核心动机", "元叙事术语"),
    (r"叙事节奏", "元叙事术语"),
    (r"人物弧线", "元叙事术语"),
    (r"故事线", "元叙事术语"),
    (r"这一刻.*命运", "编剧旁白"),
    (r"谁也没有想到", "上帝视角"),
    (r"殊不知", "上帝视角"),
]

# 规则4：报告式语言
REPORT_STYLE_PATTERNS: list[str] = [
    r"分析了.{0,10}局势",
    r"从.{0,6}角度来看",
    r"综合考虑",
]

# 规则5：集体反应套话
COLLECTIVE_PATTERNS: list[str] = [
    r"在场之人皆",
    r"众人齐声",
    r"一时间.{0,6}哗然",
]


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    rule: str
    severity: str           # "error" | "warning"
    description: str
    excerpt: str = ""


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    word_count: int = 0


# ── 验证器 ──────────────────────────────────────────────────

class PostWriteValidator:
    """
    零 LLM 的写后验证器，检查 9 条硬规则。
    不调用任何外部 API，纯正则 + 计数。
    """

    def __init__(self, custom_forbidden_words: list[str] | None = None):
        self.custom_forbidden_words = custom_forbidden_words or []

    def validate(self, content: str, target_words: int) -> ValidationResult:
        issues: list[ValidationIssue] = []
        word_count = len(content)

        # ── 规则 1：AI 标记词密度 ──
        for word in AI_MARKER_WORDS:
            count = len(re.findall(word, content))
            if count == 0:
                continue
            per_3000 = (count / word_count) * 3000 if word_count > 0 else 0
            if per_3000 > 1:
                issues.append(ValidationIssue(
                    rule="AI_MARKER_DENSITY",
                    severity="warning",
                    description=f"「{word}」出现 {count} 次（每3000字 {per_3000:.1f} 次，上限 1 次）",
                    excerpt=word,
                ))

        # ── 规则 2：禁止句式 ──
        for phrase in FORBIDDEN_PHRASES:
            if phrase in content:
                issues.append(ValidationIssue(
                    rule="FORBIDDEN_PHRASE",
                    severity="error",
                    description=f"禁止句式：「{phrase}」",
                    excerpt=phrase,
                ))

        # ── 规则 3：元叙事 ──
        for pattern, label in META_NARRATIVE_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                issues.append(ValidationIssue(
                    rule="META_NARRATIVE",
                    severity="warning",
                    description=f"{label}：「{matches[0]}」（共 {len(matches)} 处）",
                    excerpt=matches[0],
                ))

        # ── 规则 4：报告式语言 ──
        for pattern in REPORT_STYLE_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                issues.append(ValidationIssue(
                    rule="REPORT_STYLE",
                    severity="warning",
                    description=f"报告式语言：「{matches[0]}」",
                    excerpt=matches[0],
                ))

        # ── 规则 5：集体反应套话 ──
        for pattern in COLLECTIVE_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                issues.append(ValidationIssue(
                    rule="COLLECTIVE_REACTION",
                    severity="warning",
                    description=f"集体反应套话：「{matches[0]}」",
                    excerpt=matches[0],
                ))

        # ── 规则 6：连续"了"字 ──
        sentences = re.split(r"[。！？!?]", content)
        max_consecutive_le = 0
        consecutive = 0
        for s in sentences:
            if "了" in s:
                consecutive += 1
                max_consecutive_le = max(max_consecutive_le, consecutive)
            else:
                consecutive = 0
        if max_consecutive_le >= 6:
            issues.append(ValidationIssue(
                rule="CONSECUTIVE_LE",
                severity="warning",
                description=f"连续 {max_consecutive_le} 句含「了」字（上限 6 句）",
            ))

        # ── 规则 7：段落过长 ──
        paragraphs = [p for p in re.split(r"\n{2,}", content) if p.strip()]
        long_paragraphs = [p for p in paragraphs if len(p) > 300]
        if len(long_paragraphs) >= 2:
            issues.append(ValidationIssue(
                rule="LONG_PARAGRAPH",
                severity="warning",
                description=f"{len(long_paragraphs)} 个段落超过 300 字",
            ))

        # ── 规则 8：字数偏差 ──
        if target_words > 0:
            deviation = abs(word_count - target_words) / target_words
            if deviation > 0.2:
                issues.append(ValidationIssue(
                    rule="WORD_COUNT_DEVIATION",
                    severity="warning",
                    description=f"实际 {word_count} 字，目标 {target_words} 字，偏差 {deviation*100:.0f}%（上限 20%）",
                ))

        # ── 规则 9：自定义禁止词 ──
        for word in self.custom_forbidden_words:
            count = len(re.findall(re.escape(word), content))
            if count > 1:
                issues.append(ValidationIssue(
                    rule="CUSTOM_FORBIDDEN_WORD",
                    severity="warning",
                    description=f"自定义禁止词「{word}」出现 {count} 次（每章上限 1 次）",
                    excerpt=word,
                ))

        has_error = any(i.severity == "error" for i in issues)
        return ValidationResult(passed=not has_error, issues=issues, word_count=word_count)

    def summarize(self, results: list[ValidationResult]) -> dict[str, int]:
        """统计所有章节的规则触发频率"""
        counts: dict[str, int] = {}
        for r in results:
            for issue in r.issues:
                counts[issue.rule] = counts.get(issue.rule, 0) + 1
        return counts

    def format_report(self, result: ValidationResult) -> str:
        """格式化验证结果为可读文本"""
        if result.passed and not result.issues:
            return f"✅ 验证通过（{result.word_count} 字）"
        status = "❌ 验证失败" if not result.passed else "⚠️ 有警告"
        lines = [f"{status}（{result.word_count} 字，{len(result.issues)} 个问题）"]
        for issue in result.issues:
            icon = "❌" if issue.severity == "error" else "⚠️"
            lines.append(f"  {icon} [{issue.rule}] {issue.description}")
        return "\n".join(lines)
