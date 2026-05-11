# consistency_checker.py
# -*- coding: utf-8 -*-
"""
一致性检查器 -- 扩展了叙事追踪维度的检查。
原始功能 + Dramatica-Flow 移植的情感/关系/伏笔/信息边界/因果链检查。
"""
from llm_adapters import create_llm_adapter

# ============== 扩展后的一致性检查提示词 ==============
CONSISTENCY_PROMPT = """\
请检查下面的小说设定与最新章节是否存在明显冲突或不一致之处：

- 小说设定：
{novel_setting}

- 角色状态（可能包含重要信息）：
{character_state}

- 前文摘要：
{global_summary}

- 已记录的未解决冲突或剧情要点：
{plot_arcs}

- 情感弧线记录：
{emotional_arcs}

- 关系网络记录：
{relationship_matrix}

- 未闭合伏笔：
{pending_hooks}

- 信息边界（谁知道什么）：
{known_info_map}

- 因果链记录：
{causal_chain}

- 最新章节内容：
{chapter_text}

请从以下维度逐一检查：
1. 角色情感连续性：本章角色情感是否与情感弧线记录一致？是否有突兀的情感转变？
2. 关系一致性：角色间互动是否与关系网络记录矛盾？关系变化是否有合理铺垫？
3. 伏笔推进：已到期（逾期）的伏笔是否被推进或回收？新埋设的伏笔是否自然？
4. 信息边界：是否有角色表现出知道他不应知道的信息？信息获取是否有合理来源？
5. 因果连贯：本章事件是否与已有因果链逻辑一致？是否有因果断裂？
6. 设定冲突：是否存在世界观/设定层面的矛盾？
7. 角色行为逻辑：角色行为是否符合其性格和动机？
8. 剧情要点衔接：已记录的未解决冲突是否被正确推进？

如果存在冲突或不一致，请说明；如果在未解决冲突中有被忽略或需要推进的地方，也请提及；否则请返回"无明显冲突"。
"""

# 向后兼容的旧版提示词（当没有叙事追踪数据时使用）
CONSISTENCY_PROMPT_LEGACY = """\
请检查下面的小说设定与最新章节是否存在明显冲突或不一致之处，如有请列出：
- 小说设定：
{novel_setting}

- 角色状态（可能包含重要信息）：
{character_state}

- 前文摘要：
{global_summary}

- 已记录的未解决冲突或剧情要点：
{plot_arcs}  # 若为空可能不输出

- 最新章节内容：
{chapter_text}

如果存在冲突或不一致，请说明；如果在未解决冲突中有被忽略或需要推进的地方，也请提及；否则请返回"无明显冲突"。
"""


def check_consistency(
    novel_setting: str,
    character_state: str,
    global_summary: str,
    chapter_text: str,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float = 0.3,
    plot_arcs: str = "",
    interface_format: str = "OpenAI",
    max_tokens: int = 2048,
    timeout: int = 600,
    # ── 新增参数（可选，向后兼容）──
    emotional_arcs: str = "",
    relationship_matrix: str = "",
    pending_hooks: str = "",
    known_info_map: str = "",
    causal_chain: str = "",
) -> str:
    """
    调用模型做一致性检查。
    扩展了叙事追踪维度：情感连续性、关系一致性、伏笔推进、信息边界、因果连贯。
    新增参数均为可选，不传时使用旧版提示词保持向后兼容。
    """
    # 判断是否有叙事追踪数据
    has_narrative_data = any([
        emotional_arcs.strip(),
        relationship_matrix.strip(),
        pending_hooks.strip(),
        known_info_map.strip(),
        causal_chain.strip(),
    ])

    if has_narrative_data:
        prompt = CONSISTENCY_PROMPT.format(
            novel_setting=novel_setting,
            character_state=character_state,
            global_summary=global_summary,
            plot_arcs=plot_arcs,
            emotional_arcs=emotional_arcs if emotional_arcs.strip() else "（暂无记录）",
            relationship_matrix=relationship_matrix if relationship_matrix.strip() else "（暂无记录）",
            pending_hooks=pending_hooks if pending_hooks.strip() else "（暂无记录）",
            known_info_map=known_info_map if known_info_map.strip() else "（暂无记录）",
            causal_chain=causal_chain if causal_chain.strip() else "（暂无记录）",
            chapter_text=chapter_text,
        )
    else:
        prompt = CONSISTENCY_PROMPT_LEGACY.format(
            novel_setting=novel_setting,
            character_state=character_state,
            global_summary=global_summary,
            plot_arcs=plot_arcs,
            chapter_text=chapter_text,
        )

    llm_adapter = create_llm_adapter(
        interface_format=interface_format,
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )

    # 调试日志
    print("\n[ConsistencyChecker] Prompt >>>", prompt)

    response = llm_adapter.invoke(prompt)
    if not response:
        return "审校Agent无回复"

    # 调试日志
    print("[ConsistencyChecker] Response <<<", response)

    return response
