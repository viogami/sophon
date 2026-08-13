"""从 catalog 事实层生成可检索的角色 RAG 文档。"""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable

from psycopg.types.json import Jsonb

from . import db, embed

BATCH_SIZE = 64

ROLE_KEYWORDS = (
    "学生", "老师", "教师", "会长", "委员", "偶像", "歌手", "声优", "演员", "主播",
    "UP主", "画师", "作家", "侦探", "警察", "医生", "护士", "军人", "士兵", "杀手",
    "忍者", "剑士", "骑士", "魔法", "巫女", "公主", "王子", "皇帝", "国王", "女王",
    "姐姐", "妹妹", "哥哥", "弟弟", "父亲", "母亲", "女儿", "儿子", "吸血鬼", "机器人",
    "AI", "舰娘",
)

COLOR_ALIASES = {
    "黑": "黑色", "白": "白色", "金": "金色", "蓝": "蓝色", "棕": "棕色",
    "茶": "棕色", "银": "银色", "红": "红色", "赤": "红色", "紫": "紫色",
    "橙": "橙色", "绿": "绿色", "粉": "粉色", "灰": "灰色",
}


class Progress:
    """轻量终端进度条。"""

    def __init__(self, label: str, total: int) -> None:
        self.label = label
        self.total = total
        self.current = 0
        self.started_at = time.monotonic()
        self.last_render_at = 0.0

    def start(self) -> None:
        self._render(force=True)

    def advance(self, count: int) -> None:
        self.current += count
        self._render(force=self.current >= self.total)

    def finish(self) -> None:
        self._render(force=True)
        print(flush=True)

    def _render(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_render_at < 0.2:
            return
        self.last_render_at = now
        elapsed = int(now - self.started_at)
        minutes, seconds = divmod(elapsed, 60)
        if self.total:
            ratio = min(self.current / self.total, 1)
            filled = int(ratio * 20)
            bar = "#" * filled + "-" * (20 - filled)
            detail = f"[{bar}] {self.current:,}/{self.total:,} ({ratio:.1%})"
        else:
            detail = f"{self.current:,} rows"
        print(f"\r[{minutes:02d}:{seconds:02d}] {self.label}: {detail}", end="", flush=True)


def _chunks(items: list[dict], size: int) -> Iterable[list[dict]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize_color(value: str) -> str:
    value = value.strip().removesuffix("色").removesuffix("发").removesuffix("瞳")
    if value in COLOR_ALIASES:
        return COLOR_ALIASES[value]
    return value + "色" if len(value) == 1 else value


def _split_attributes(attributes: list[str]) -> tuple[list[str], list[str]]:
    traits = []
    roles = []
    for attribute in attributes:
        if any(keyword in attribute for keyword in ROLE_KEYWORDS):
            roles.append(attribute)
        else:
            traits.append(attribute)
    return traits, roles


def _line(label: str, values: Iterable[str] | str | None) -> str | None:
    if values is None:
        return None
    if isinstance(values, str):
        return f"{label}: {values}" if values else None
    text = "、".join(value for value in values if value)
    return f"{label}: {text}" if text else None


def _content(document: dict) -> str:
    profile = document["profile"]
    birthday = "".join(
        part for part in (
            f"{profile['birth_year']}年" if profile.get("birth_year") else "",
            f"{profile['birth_month']}月" if profile.get("birth_month") else "",
            f"{profile['birth_day']}日" if profile.get("birth_day") else "",
        ) if part
    )
    lines = [
        _line("角色", document["name"]),
        _line("所属作品", document["work_titles"]),
        _line("别名", document["aliases"]),
        _line("性别", document["gender"]),
        _line("发色", document["hair_color"]),
        _line("瞳色", document["eye_color"]),
        _line("萌点/属性", document["traits"]),
        _line("身份", document["roles"]),
        _line("声优", document["voice_actors"]),
        _line("生日", birthday),
        _line("星座", profile.get("zodiac")),
        _line("血型", profile.get("blood_type")),
        _line("年龄", profile.get("age_text")),
        _line("身高", profile.get("height_text")),
        _line("体重", profile.get("weight_text")),
    ]
    return "\n".join(line for line in lines if line)


def _load_projection_batch(conn, characters: list[tuple]) -> tuple[list[dict], list[dict]]:
    """读取一批有效角色及其关联事实，返回该批次的 works 和 documents。"""
    character_ids = [row[0] for row in characters]
    if not character_ids:
        return [], []

    def grouped(query: str) -> dict[int, list[tuple]]:
        values: dict[int, list[tuple]] = defaultdict(list)
        for row in conn.execute(query, (character_ids,)).fetchall():
            values[row[0]].append(row[1:])
        return values

    names = grouped(
        """select character_id, name from catalog_character_names
           where character_id = any(%s) order by character_id, name"""
    )
    attributes = grouped(
        """select ca.character_id, a.name from catalog_character_attributes ca
           join catalog_attributes a on a.id = ca.attribute_id
           where ca.character_id = any(%s) order by ca.character_id, a.name"""
    )
    physical_traits = grouped(
        """select character_id, trait_type, value from catalog_character_physical_traits
           where character_id = any(%s) order by character_id, trait_type, value"""
    )
    works = grouped(
        """select cw.character_id, w.id, w.title from catalog_character_works cw
           join catalog_works w on w.id = cw.work_id
           where cw.character_id = any(%s) order by cw.character_id, w.title"""
    )
    voice_credits = grouped(
        """select vc.character_id, p.display_name from catalog_character_voice_credits vc
           join catalog_people p on p.id = vc.person_id
           where vc.character_id = any(%s) order by vc.character_id, p.display_name"""
    )
    profile_rows = conn.execute(
        """select character_id, birth_year, birth_month, birth_day, zodiac, blood_type,
                  age_text, height_text, weight_text
           from catalog_character_profiles where character_id = any(%s)""",
        (character_ids,),
    ).fetchall()

    profiles = {
        row[0]: dict(zip(
            ("birth_year", "birth_month", "birth_day", "zodiac", "blood_type", "age_text", "height_text", "weight_text"),
            row[1:],
        ))
        for row in profile_rows
    }
    rag_works: dict[int, dict] = {}
    documents = []
    for character_id, name, gender, source_url in characters:
        character_works = works.get(character_id, [])
        for work_id, title in character_works:
            rag_works[work_id] = {
                "id": f"catalog-work:{work_id}",
                "title": title,
                "aliases": [],
                "type": None,
                "meta": {"catalog_work_id": work_id},
            }
        attribute_names = _unique(value[0] for value in attributes.get(character_id, []))
        traits, roles = _split_attributes(attribute_names)
        hair_color = _unique(
            _normalize_color(value)
            for trait_type, value in physical_traits.get(character_id, [])
            if trait_type == "hair_color"
        )
        eye_color = _unique(
            _normalize_color(value)
            for trait_type, value in physical_traits.get(character_id, [])
            if trait_type == "eye_color"
        )
        document = {
            "source_key": f"catalog:character:{character_id}",
            "doc_type": "character",
            "work_id": f"catalog-work:{character_works[0][0]}" if character_works else None,
            "name": name,
            "aliases": _unique(value[0] for value in names.get(character_id, []) if value[0] != name),
            "gender": {"female": "女", "male": "男"}.get(gender),
            "hair_color": hair_color,
            "eye_color": eye_color,
            "traits": traits,
            "roles": roles,
            "work_titles": _unique(title for _, title in character_works),
            "voice_actors": _unique(value[0] for value in voice_credits.get(character_id, [])),
            "profile": profiles.get(character_id, {}),
            "source_url": source_url,
            "meta": {
                "catalog_character_id": character_id,
                "catalog_work_ids": [work_id for work_id, _ in character_works],
            },
        }
        document["content"] = _content(document)
        documents.append(document)
    return list(rag_works.values()), documents


def _iter_character_batches(conn, batch_size: int) -> Iterable[list[tuple]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """select id, display_name, gender, source_url
               from catalog_characters
               where source_code = %s and is_active = true
               order by id""",
            ("moegirl-dataset",),
        )
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            yield batch


def _embedding_text(document: dict) -> str:
    parts = [document["name"], *document["aliases"], *document["hair_color"], *document["eye_color"]]
    parts.extend(document["traits"] + document["roles"] + [document["content"]])
    return " ".join(part for part in parts if part)


def rebuild(batch_size: int = BATCH_SIZE, reset: bool = True) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    # 在清空已有索引前先校验远程配置或准备显式启用的本地模型。
    print(embed.description(), flush=True)
    embed.prepare()
    print("准备 RAG 投影: 扫描 catalog 事实层并流式生成文档", flush=True)

    with db.connect() as conn:
        if reset:
            print("清空既有 RAG 文档...", flush=True)
            conn.execute("truncate docs restart identity cascade")
            conn.execute("truncate works cascade")

        work_progress = Progress("写入 works", 0)
        doc_progress = Progress("生成并写入 RAG 文档", 0)
        batch_progress = Progress("扫描 catalog", 0)
        work_progress.start()
        doc_progress.start()
        batch_progress.start()
        seen_work_ids: set[int] = set()
        scanned_characters = 0
        written_documents = 0

        with db.connect_catalog() as catalog_conn:
            for character_batch in _iter_character_batches(catalog_conn, batch_size):
                batch_works, batch_documents = _load_projection_batch(catalog_conn, character_batch)
                batch_progress.advance(len(character_batch))
                scanned_characters += len(character_batch)

                new_work_rows = []
                for work in batch_works:
                    work_id = work["id"]
                    if work_id in seen_work_ids:
                        continue
                    seen_work_ids.add(work_id)
                    new_work_rows.append(
                        (work["id"], work["title"], work["aliases"], work["type"], Jsonb(work["meta"]))
                    )
                if new_work_rows:
                    with conn.cursor() as cursor:
                        cursor.executemany(
                            """insert into works (id, title, aliases, type, meta) values (%s, %s, %s, %s, %s)
                               on conflict (id) do update set title = excluded.title, aliases = excluded.aliases,
                                 type = excluded.type, meta = excluded.meta""",
                            new_work_rows,
                        )
                    work_progress.advance(len(new_work_rows))

                if batch_documents:
                    vectors = embed.embed([_embedding_text(document) for document in batch_documents])
                    doc_rows = [
                        (
                            document["source_key"], document["doc_type"], document["work_id"], document["name"],
                            document["aliases"], document["gender"], document["hair_color"], document["eye_color"],
                            document["traits"], document["roles"], document["content"], document["source_url"],
                            Jsonb(document["meta"]), vector["dense"], vector["sparse"],
                        )
                        for document, vector in zip(batch_documents, vectors)
                    ]
                    with conn.cursor() as cursor:
                        cursor.executemany(
                            """insert into docs
                               (source_key, doc_type, work_id, name, aliases, gender, hair_color, eye_color,
                                traits, roles, content, source_url, meta, embedding, sparse)
                               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                               on conflict (source_key) where source_key is not null do update set
                                 doc_type = excluded.doc_type, work_id = excluded.work_id, name = excluded.name,
                                 aliases = excluded.aliases, gender = excluded.gender, hair_color = excluded.hair_color,
                                 eye_color = excluded.eye_color, traits = excluded.traits, roles = excluded.roles,
                                 content = excluded.content, source_url = excluded.source_url, meta = excluded.meta,
                                 embedding = excluded.embedding, sparse = excluded.sparse""",
                            doc_rows,
                        )
                    doc_progress.advance(len(batch_documents))
                    written_documents += len(batch_documents)

        batch_progress.finish()
        work_progress.finish()
        doc_progress.finish()
        print(
            f"RAG 构建完成: {len(seen_work_ids):,} 部作品、"
            f"{written_documents:,} 个角色文档、{scanned_characters:,} 个 catalog 角色。",
            flush=True,
        )
