"""基于候选资料生成回答，强制引用来源，不确定时给出多个候选。"""
from __future__ import annotations

from . import config

_SYSTEM = """你是动漫角色识别助手。严格遵守:
1. 只能依据下方提供的【候选资料】作答, 绝不使用资料外的知识, 绝不编造。
2. 每条结论必须标注来源, 格式为 [doc:<id>]。
3. 若资料能确定答案, 给出角色名 + 依据 + 所属作品。
4. 若无法确定, 列出 2~3 个可能候选并给出各自的置信度(高/中/低), 说明区分依据。
5. 若候选资料与问题明显无关, 直接说"根据现有资料无法确定"。
"""


def _format_candidates(candidates: list[dict]) -> str:
    blocks = []
    for c in candidates:
        tags = "、".join(c.get("hair_color", []) + c.get("eye_color", [])
                         + c.get("traits", []) + c.get("roles", []))
        blocks.append(
            f"[doc:{c['id']}] ({c['doc_type']}) {c.get('name') or ''} "
            f"| 作品: {c.get('work_title') or '未知'} | 标签: {tags}\n{c['content']}"
        )
    return "\n\n".join(blocks) if blocks else "(无候选)"


def generate(query: str, candidates: list[dict]) -> str:
    client = config.llm_client()
    prompt = (
        f"用户问题: {query}\n\n"
        f"【候选资料】\n{_format_candidates(candidates)}\n"
        "\n请依据以上资料作答。"
    )
    msg = client.messages.create(
        model=config.require_llm_model(),
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text
