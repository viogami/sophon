"""萌娘 DB 第一阶段结构化落库。"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import replace

from psycopg.types.json import Jsonb

from .. import db
from ..importers.moegirl import MoeGirlDataset, SOURCE_CODE

BATCH_SIZE = 1_000


class Progress:
    """无需额外依赖的终端进度显示。"""

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
            detail = "0 rows"
        print(f"\r[{minutes:02d}:{seconds:02d}] {self.label}: {detail}", end="", flush=True)


def _chunks(rows: Iterable[tuple], size: int = BATCH_SIZE) -> Iterable[list[tuple]]:
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _execute_many(
    conn,
    query: str,
    rows: Iterable[tuple],
    *,
    label: str,
    total: int,
    batch_size: int = BATCH_SIZE,
) -> None:
    progress = Progress(label, total)
    progress.start()
    for batch in _chunks(rows, batch_size):
        with conn.cursor() as cursor:
            cursor.executemany(query, batch)
        progress.advance(len(batch))
    progress.finish()


def _json_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _lookup_ids(conn, table: str, source_keys: Sequence[str]) -> dict[str, int]:
    if not source_keys:
        return {}
    rows = conn.execute(
        f"select source_key, id from {table} where source_code = %s and source_key = any(%s)",
        (SOURCE_CODE, list(source_keys)),
    ).fetchall()
    return {source_key: entity_id for source_key, entity_id in rows}


def _changed_characters(conn, characters: Sequence[dict]) -> tuple[tuple[dict, ...], int]:
    """以 source_records 的组合载荷哈希识别需要写入的角色。"""
    source_keys = [character["source_key"] for character in characters]
    stored_hashes: dict[str, str] = {}
    for key_batch in _chunks(source_keys, BATCH_SIZE):
        rows = conn.execute(
            """select external_key, payload_hash from source_records
               where source_code = %s and record_kind = %s and external_key = any(%s)""",
            (SOURCE_CODE, "character", key_batch),
        ).fetchall()
        stored_hashes.update(rows)

    changed = tuple(
        character
        for character in characters
        if stored_hashes.get(character["source_key"]) != character["payload_hash"]
    )
    return changed, len(characters) - len(changed)


def _sync_character_activity(conn, source_keys: list[str]) -> None:
    """完整快照中不存在的角色保留历史，但不再作为有效数据参与后续派生。"""
    conn.execute(
        """update catalog_characters set is_active = false
           where source_code = %s and not (source_key = any(%s))""",
        (SOURCE_CODE, source_keys),
    )
    conn.execute(
        """update catalog_characters set is_active = true
           where source_code = %s and source_key = any(%s)""",
        (SOURCE_CODE, source_keys),
    )


def _delete_character_details(conn, character_ids: list[int]) -> None:
    if not character_ids:
        return
    tables = (
        "catalog_character_names",
        "catalog_character_images",
        "catalog_character_attributes",
        "catalog_character_physical_traits",
        "catalog_character_subjects",
        "catalog_character_works",
        "catalog_character_voice_credits",
        "catalog_character_external_refs",
    )
    print(f"同步角色明细: 清理 {len(character_ids):,} 个角色的旧关联", flush=True)
    for index, table in enumerate(tables, start=1):
        conn.execute(f"delete from {table} where character_id = any(%s)", (character_ids,))
        print(f"\r同步角色明细: 已清理 {index}/{len(tables)} 张关联表", end="", flush=True)
    print(flush=True)


def _reset_catalog(conn) -> None:
    conn.execute("truncate catalog_external_redirects, source_registry restart identity cascade")


def load(dataset: MoeGirlDataset, reset: bool = False, changed_only: bool = False) -> None:
    """写入事实层；不生成 docs、不计算 embedding、不触碰既有 RAG 表。"""
    started_at = time.monotonic()
    snapshot_character_keys = [character["source_key"] for character in dataset.characters]

    with db.connect_catalog() as conn:
        if reset:
            print("重置第一阶段 catalog/source 表...", flush=True)
            _reset_catalog(conn)

        print("注册数据源...", flush=True)
        conn.execute(
            """insert into source_registry (source_code, display_name, homepage, metadata)
               values (%s, %s, %s, %s)
               on conflict (source_code) do update set
                 display_name = excluded.display_name,
                 homepage = excluded.homepage,
                 metadata = excluded.metadata,
                 updated_at = now()""",
            (
                SOURCE_CODE,
                "Moegirl Dataset",
                "https://github.com/zhuobinggang/moegirl-dataset",
                Jsonb({"import_stage": "catalog-v1"}),
            ),
        )

        if changed_only:
            print("比对角色原始载荷哈希...", flush=True)
            changed_characters, unchanged_count = _changed_characters(conn, dataset.characters)
            dataset = replace(dataset, characters=changed_characters)
            print(
                f"差异检测完成: {len(changed_characters):,} 个新增或变化，"
                f"{unchanged_count:,} 个跳过。",
                flush=True,
            )

        character_count = len(dataset.characters)
        name_count = sum(len(character["names"]) for character in dataset.characters)
        image_count = sum(
            1
            for character in dataset.characters
            for image in character["images"]
            if isinstance(image, dict) and isinstance(image.get("url"), str)
        )
        character_attribute_count = sum(len(character["attributes"]) for character in dataset.characters)
        physical_trait_count = sum(len(character["physical_traits"]) for character in dataset.characters)
        character_subject_count = sum(len(character["subjects"]) for character in dataset.characters)
        character_work_count = sum(len(character["works"]) for character in dataset.characters)
        voice_credit_count = sum(len(character["voice_credits"]) for character in dataset.characters)
        external_ref_count = sum(len(character["external_refs"]) for character in dataset.characters)
        attribute_type_count = sum(len(attribute["attribute_types"]) for attribute in dataset.attributes)

        character_record_keys = [character["source_key"] for character in dataset.characters]
        _execute_many(
            conn,
            """insert into source_records
               (source_code, record_kind, external_key, source_url, payload, payload_hash)
               values (%s, %s, %s, %s, %s, %s)
               on conflict (source_code, record_kind, external_key) do update set
                 source_url = excluded.source_url,
                 payload = excluded.payload,
                 payload_hash = excluded.payload_hash,
                 last_seen_at = now()""",
            (
                (
                    SOURCE_CODE,
                    "character",
                    character["source_key"],
                    character["source_url"],
                    Jsonb(character["payload"]),
                    character["payload_hash"],
                )
                for character in dataset.characters
            ),
            label="写入角色源记录",
            total=character_count,
        )
        print("查询角色源记录 ID...", flush=True)
        source_record_rows = conn.execute(
            """select external_key, id from source_records
               where source_code = %s and record_kind = %s and external_key = any(%s)""",
            (SOURCE_CODE, "character", character_record_keys),
        ).fetchall()
        source_record_ids = {external_key: record_id for external_key, record_id in source_record_rows}

        _execute_many(
            conn,
            """insert into catalog_works (source_code, source_key, title)
               values (%s, %s, %s)
               on conflict (source_code, source_key) do update set title = excluded.title""",
            ((SOURCE_CODE, f"work:{title}", title) for title in dataset.works),
            label="写入作品目录",
            total=len(dataset.works),
        )
        _execute_many(
            conn,
            """insert into catalog_subjects (source_code, source_key, title)
               values (%s, %s, %s)
               on conflict (source_code, source_key) do update set title = excluded.title""",
            ((SOURCE_CODE, f"subject:{title}", title) for title in dataset.subjects),
            label="写入主题目录",
            total=len(dataset.subjects),
        )
        _execute_many(
            conn,
            """insert into catalog_attributes (source_code, source_key, name, source_url)
               values (%s, %s, %s, %s)
               on conflict (source_code, source_key) do update set
                 name = excluded.name,
                 source_url = excluded.source_url""",
            (
                (SOURCE_CODE, attribute["source_key"], attribute["name"], attribute["source_url"])
                for attribute in dataset.attributes
            ),
            label="写入属性目录",
            total=len(dataset.attributes),
        )
        _execute_many(
            conn,
            """insert into catalog_people (source_code, source_key, display_name)
               values (%s, %s, %s)
               on conflict (source_code, source_key) do update set
                 display_name = excluded.display_name""",
            ((SOURCE_CODE, f"person:{name}", name) for name in dataset.people),
            label="写入声优目录",
            total=len(dataset.people),
        )

        print("查询维表 ID...", flush=True)
        work_ids = _lookup_ids(conn, "catalog_works", [f"work:{title}" for title in dataset.works])
        subject_ids = _lookup_ids(conn, "catalog_subjects", [f"subject:{title}" for title in dataset.subjects])
        attribute_ids = _lookup_ids(
            conn,
            "catalog_attributes",
            [attribute["source_key"] for attribute in dataset.attributes],
        )
        person_ids = _lookup_ids(conn, "catalog_people", [f"person:{name}" for name in dataset.people])

        attribute_type_rows = (
            (attribute_ids[attribute["source_key"]], attribute_type)
            for attribute in dataset.attributes
            for attribute_type in attribute["attribute_types"]
            if attribute["source_key"] in attribute_ids
        )
        _execute_many(
            conn,
            """insert into catalog_attribute_types (attribute_id, attribute_type)
               values (%s, %s) on conflict do nothing""",
            attribute_type_rows,
            label="写入属性分类",
            total=attribute_type_count,
        )

        _execute_many(
            conn,
            """insert into catalog_characters
               (source_code, source_key, display_name, gender, is_active, source_record_id, source_url, metadata)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (source_code, source_key) do update set
                 display_name = excluded.display_name,
                 gender = excluded.gender,
                 is_active = true,
                 source_record_id = excluded.source_record_id,
                 source_url = excluded.source_url,
                 metadata = excluded.metadata""",
            (
                (
                    SOURCE_CODE,
                    character["source_key"],
                    character["display_name"],
                    character["gender"],
                    True,
                    source_record_ids[character["source_key"]],
                    character["source_url"],
                    Jsonb({"record_kind": "character"}),
                )
                for character in dataset.characters
            ),
            label="写入角色目录",
            total=character_count,
        )
        print("查询角色目录 ID...", flush=True)
        character_ids = _lookup_ids(conn, "catalog_characters", character_record_keys)
        selected_ids = list(character_ids.values())
        _delete_character_details(conn, selected_ids)

        _execute_many(
            conn,
            """insert into catalog_character_profiles
               (character_id, birth_year, birth_month, birth_day, zodiac, blood_type,
                age_text, height_text, weight_text)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (character_id) do update set
                 birth_year = excluded.birth_year,
                 birth_month = excluded.birth_month,
                 birth_day = excluded.birth_day,
                 zodiac = excluded.zodiac,
                 blood_type = excluded.blood_type,
                 age_text = excluded.age_text,
                 height_text = excluded.height_text,
                 weight_text = excluded.weight_text""",
            (
                (
                    character_ids[character["source_key"]],
                    character["profile"]["birth_year"],
                    character["profile"]["birth_month"],
                    character["profile"]["birth_day"],
                    character["profile"]["zodiac"],
                    character["profile"]["blood_type"],
                    character["profile"]["age_text"],
                    character["profile"]["height_text"],
                    character["profile"]["weight_text"],
                )
                for character in dataset.characters
            ),
            label="写入角色资料",
            total=character_count,
        )

        _execute_many(
            conn,
            """insert into catalog_character_names (character_id, name, name_kind)
               values (%s, %s, %s) on conflict do nothing""",
            (
                (character_ids[character["source_key"]], name["name"], name["name_kind"])
                for character in dataset.characters
                for name in character["names"]
            ),
            label="写入角色别名",
            total=name_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_images (character_id, position, image_ref, alt_text)
               values (%s, %s, %s, %s) on conflict do nothing""",
            (
                (
                    character_ids[character["source_key"]],
                    position,
                    image["url"],
                    image.get("alt"),
                )
                for character in dataset.characters
                for position, image in enumerate(character["images"])
                if isinstance(image, dict) and isinstance(image.get("url"), str)
            ),
            label="写入角色图片",
            total=image_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_attributes
               (character_id, attribute_id, evidence_source)
               values (%s, %s, %s) on conflict do nothing""",
            (
                (
                    character_ids[character["source_key"]],
                    attribute_ids[f"attribute:{attribute['name']}"] ,
                    attribute["evidence_source"],
                )
                for character in dataset.characters
                for attribute in character["attributes"]
                if f"attribute:{attribute['name']}" in attribute_ids
            ),
            label="写入角色属性关联",
            total=character_attribute_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_physical_traits (character_id, trait_type, value)
               values (%s, %s, %s) on conflict do nothing""",
            (
                (character_ids[character["source_key"]], trait["trait_type"], trait["value"])
                for character in dataset.characters
                for trait in character["physical_traits"]
            ),
            label="写入外观特征",
            total=physical_trait_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_subjects (character_id, subject_id)
               values (%s, %s) on conflict do nothing""",
            (
                (character_ids[character["source_key"]], subject_ids[f"subject:{title}"])
                for character in dataset.characters
                for title in character["subjects"]
                if f"subject:{title}" in subject_ids
            ),
            label="写入角色主题关联",
            total=character_subject_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_works (character_id, work_id, membership_source)
               values (%s, %s, %s) on conflict do nothing""",
            (
                (character_ids[character["source_key"]], work_ids[f"work:{title}"], "char2subject")
                for character in dataset.characters
                for title in character["works"]
                if f"work:{title}" in work_ids
            ),
            label="写入角色作品关联",
            total=character_work_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_voice_credits
               (character_id, person_id, credit_source)
               values (%s, %s, %s) on conflict do nothing""",
            (
                (
                    character_ids[character["source_key"]],
                    person_ids[f"person:{credit['name']}"] ,
                    credit["credit_source"],
                )
                for character in dataset.characters
                for credit in character["voice_credits"]
                if f"person:{credit['name']}" in person_ids
            ),
            label="写入角色声优关联",
            total=voice_credit_count,
        )
        _execute_many(
            conn,
            """insert into catalog_character_external_refs
               (character_id, external_source, external_key, metadata)
               values (%s, %s, %s, %s)
               on conflict (character_id, external_source, external_key) do update set
                 metadata = excluded.metadata""",
            (
                (
                    character_ids[character["source_key"]],
                    reference["external_source"],
                    reference["external_key"],
                    Jsonb(reference["metadata"]),
                )
                for character in dataset.characters
                for reference in character["external_refs"]
            ),
            label="写入 Bangumi 映射",
            total=external_ref_count,
        )
        _execute_many(
            conn,
            """insert into catalog_external_redirects (external_source, from_key, to_key)
               values (%s, %s, %s)
               on conflict (external_source, from_key) do update set to_key = excluded.to_key""",
            (("bangumi", from_key, to_key) for from_key, to_key in dataset.external_redirects),
            label="写入 Bangumi 重定向",
            total=len(dataset.external_redirects),
        )
        if changed_only and dataset.is_complete_snapshot:
            print("同步完整快照的角色有效状态...", flush=True)
            _sync_character_activity(conn, snapshot_character_keys)
        elapsed = time.monotonic() - started_at
        print(f"结构化数据入库完成，总耗时 {elapsed:.1f}s。", flush=True)
