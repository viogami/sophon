"""混合检索: dense + sparse + 标签重叠, 用 RRF 融合。"""
from __future__ import annotations
from . import db, embed

RRF_K = 60


def _rrf(rank_lists: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked in rank_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def retrieve(
    query: str,
    features: dict | None = None,
    top_k: int = 5,
    pool: int = 20,
) -> list[dict]:
    """返回 Top-K 候选 doc 记录。

    features: extract.py 抽取的结构化特征 (可含 hair_color/eye_color/traits/roles)。
    只检索由 catalog 派生的角色卡。
    """
    features = features or {}
    q = embed.embed_one(query)
    character_clause = "where doc_type = 'character'"
    params = {"qd": q["dense"], "pool": pool}

    with db.connect() as conn:
        dense_ids = [r[0] for r in conn.execute(
            f"select id from docs {character_clause} order by embedding <=> %(qd)s limit %(pool)s",
            params,
        ).fetchall()]
        rank_lists = [dense_ids]
        if q["sparse"] is not None:
            sparse_ids = [r[0] for r in conn.execute(
                f"select id from docs {character_clause} order by sparse <#> %(qs)s limit %(pool)s",
                {**params, "qs": q["sparse"]},
            ).fetchall()]
            rank_lists.append(sparse_ids)

        # 标签重叠排名 (软过滤: 作为额外一路, 不做硬 AND 以免召回为 0)
        tags = (features.get("hair_color", []) + features.get("eye_color", [])
                + features.get("traits", []) + features.get("roles", []))
        if tags:
            tag_ids = [r[0] for r in conn.execute(
                f"""select id from docs {character_clause} and
                    (hair_color || eye_color || traits || roles) && %(tags)s
                    order by cardinality(
                        array(select unnest(hair_color || eye_color || traits || roles)
                              intersect select unnest(%(tags)s))) desc
                    limit %(pool)s""",
                {**params, "tags": tags},
            ).fetchall()]
            if tag_ids:
                rank_lists.append(tag_ids)

        gender = features.get("gender")
        if gender:
            gender_ids = [r[0] for r in conn.execute(
                f"""select id from docs {character_clause} and gender = %(gender)s
                    limit %(pool)s""",
                {**params, "gender": gender},
            ).fetchall()]
            if gender_ids:
                rank_lists.append(gender_ids)

        fused = _rrf(rank_lists)
        top_ids = [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])[:top_k]]
        if not top_ids:
            return []

        rows = conn.execute(
            """select d.id, d.doc_type, d.work_id, w.title, d.name, d.aliases, d.gender,
                      d.hair_color, d.eye_color, d.traits, d.roles, d.content, d.source_url
               from docs d left join works w on w.id = d.work_id
               where d.id = any(%s)""",
            (top_ids,),
        ).fetchall()

    by_id = {r[0]: r for r in rows}
    cols = ["id", "doc_type", "work_id", "work_title", "name", "aliases", "gender",
            "hair_color", "eye_color", "traits", "roles", "content", "source_url"]
    result = []
    for did in top_ids:
        r = by_id.get(did)
        if r:
            item = dict(zip(cols, r))
            item["rrf_score"] = round(fused[did], 4)
            result.append(item)
    return result
