"""用 LLM 从自然语言 query 抽取结构化检索特征。失败则降级为空特征。"""
from __future__ import annotations
import json

from . import config

_SYSTEM = """你是动漫角色检索系统的特征抽取器。从用户描述中抽取结构化特征, 只输出 JSON, 不要解释。
字段:
- gender: "男"/"女"/null
- hair_color: 发色数组 (中文, 如 ["红色"])
- eye_color: 眼睛颜色数组
- traits: 性格标签数组 (如 ["傲娇","高冷"])
- roles: 身份/职业数组 (如 ["剑士","学生"])
- keywords: 其他关键线索短语数组 (经历/事件, 如 ["失去妹妹","天台告白"])
无法确定的字段用 null 或空数组。"""

_EXAMPLE = ('{"gender":"女","hair_color":["红色"],'
            '"eye_color":[],"traits":["傲娇"],"roles":[],"keywords":["失去妹妹","双马尾"]}')

_EMPTY = {"gender": None, "hair_color": [], "eye_color": [],
          "traits": [], "roles": [], "keywords": []}


def extract(query: str) -> dict:
    try:
        client = config.llm_client()
        msg = client.messages.create(
            model=config.require_llm_model(),
            max_tokens=512,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"描述: {query}\n\n输出格式示例: {_EXAMPLE}\n\n现在只输出该描述对应的 JSON:",
            }],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].removeprefix("json").strip()
        data = json.loads(text)
        return {**_EMPTY, **data}
    except Exception as e:
        # 降级: 不阻塞检索, 用原 query 进行向量检索。
        print(f"[extract 降级] {type(e).__name__}: {e}")
        return dict(_EMPTY)
