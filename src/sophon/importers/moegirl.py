"""将萌娘 DB 的 JSON 文件转换为第一阶段目录模型，不执行数据库写入。"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MOEGIRL_DIR = ROOT / "data" / "moegirl"
DEFAULT_BANGUMI_DIR = ROOT / "data" / "bangumi"
SOURCE_CODE = "moegirl-dataset"


@dataclass(frozen=True)
class SourceArtifact:
    path: Path
    payload: Any


@dataclass(frozen=True)
class MoeGirlDataset:
    source_artifacts: tuple[SourceArtifact, ...]
    characters: tuple[dict[str, Any], ...]
    attributes: tuple[dict[str, Any], ...]
    subjects: tuple[str, ...]
    works: tuple[str, ...]
    people: tuple[str, ...]
    external_redirects: tuple[tuple[str, str], ...]
    is_complete_snapshot: bool


def _load(path: Path) -> tuple[Any, SourceArtifact]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, SourceArtifact(path=path, payload=payload)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _unique(value)
    if isinstance(value, str):
        return _unique([value])
    return []


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        values = _as_list(value)
        return " / ".join(values) or None
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _source_url(title: str) -> str:
    page = title.replace(" ", "_")
    return "https://zh.moegirl.org.cn/" + urllib.parse.quote(page, safe="()/:")


def _attribute_url(path: str | None) -> str | None:
    if not path:
        return None
    return _source_url(path.removeprefix("/"))


def _payload_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _name_rows(display_name: str, extra: dict[str, Any]) -> list[dict[str, str]]:
    rows = [{"name": display_name, "name_kind": "page_title"}]
    seen = {display_name}
    for name_kind, values in (
        ("legal_name", _as_list(extra.get("本名"))),
        ("alias", _as_list(extra.get("别名"))),
    ):
        for name in values:
            if name not in seen:
                rows.append({"name": name, "name_kind": name_kind})
                seen.add(name)
    return rows


def _profile(extra: dict[str, Any]) -> dict[str, Any]:
    birthday = extra.get("生日")
    if not isinstance(birthday, list):
        birthday = []
    year = _as_int(birthday[0]) if len(birthday) > 0 else None
    month = _as_int(birthday[1]) if len(birthday) > 1 else None
    day = _as_int(birthday[2]) if len(birthday) > 2 else None
    if month is not None and not 1 <= month <= 12:
        month = None
    if day is not None and not 1 <= day <= 31:
        day = None
    return {
        "birth_year": year,
        "birth_month": month,
        "birth_day": day,
        "zodiac": _as_text(extra.get("星座")),
        "blood_type": _as_text(extra.get("血型")),
        "age_text": _as_text(extra.get("年龄")),
        "height_text": _as_text(extra.get("身高")),
        "weight_text": _as_text(extra.get("体重")),
    }


def build_dataset(
    moegirl_dir: Path | None = None,
    bangumi_dir: Path | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> MoeGirlDataset:
    """读取复制到 Sophon 的数据集，并保留可落库的原始载荷。"""
    moegirl_dir = moegirl_dir or DEFAULT_MOEGIRL_DIR
    bangumi_dir = bangumi_dir or DEFAULT_BANGUMI_DIR
    artifacts: list[SourceArtifact] = []

    def load_moegirl(name: str) -> Any:
        payload, artifact = _load(moegirl_dir / name)
        artifacts.append(artifact)
        return payload

    def load_bangumi(name: str, optional: bool = False) -> Any:
        path = bangumi_dir / name
        if optional and not path.exists():
            return {}
        payload, artifact = _load(path)
        artifacts.append(artifact)
        return payload

    char_index = load_moegirl("char_index.json")
    load_moegirl("attrs.json")
    attr_index = load_moegirl("attr_index.json")
    attr2article = load_moegirl("attr2article.json")
    load_moegirl("attr2char.json")
    char2attr = load_moegirl("char2attr.json")
    char2cv = load_moegirl("char2cv.json")
    load_moegirl("cv2char.json")
    char2gender = load_moegirl("char2gender.json")
    char2subject = load_moegirl("char2subject.json")
    extra_processed = load_moegirl("extra_processed.json")
    load_moegirl("subjects.json")
    subject_index = load_moegirl("subject_index.json")
    hair_attrs = set(load_moegirl("hair_color_attr.json"))
    eye_attrs = set(load_moegirl("eye_color_attr.json"))
    fundamental_attrs = set(load_moegirl("fundamental_attr.json"))
    female_attrs = set(load_moegirl("female_attr.json"))
    male_attrs = set(load_moegirl("male_attr.json"))
    nogender_attrs = set(load_moegirl("nogender_attr.json"))
    cv_index = load_moegirl("cv_index.json")

    moegirl2bgm = load_bangumi("moegirl2bgm.json", optional=True)
    load_bangumi("bgm2moegirl.json", optional=True)
    bgm_info = load_bangumi("bgm_info.json", optional=True)
    bgm_images = load_bangumi("bgm_images_medium_mapped.json", optional=True)
    redirects = load_bangumi("bgm_redirects_full.json", optional=True)

    selected = char_index[offset:]
    if limit is not None:
        selected = selected[:limit]

    all_attributes = set(attr_index)
    all_subjects = set(subject_index)
    all_people = set(cv_index)
    characters: list[dict[str, Any]] = []
    works = set(subject_index)

    for name in selected:
        extra = extra_processed.get(name, {})
        if not isinstance(extra, dict):
            extra = {}
        mapped_attrs = _as_list(char2attr.get(name))
        info_attrs = _as_list(extra.get("萌点"))
        mapped_cvs = _as_list(char2cv.get(name))
        info_cvs = _as_list(extra.get("声优"))
        subjects = _as_list(char2subject.get(name))
        bangumi_ids = _as_list(moegirl2bgm.get(name))
        attrs = _unique(mapped_attrs + info_attrs)
        cvs = _unique(mapped_cvs + info_cvs)

        all_attributes.update(attrs)
        all_subjects.update(subjects)
        all_people.update(cvs)

        attribute_links = [
            {"name": value, "evidence_source": "char2attr"}
            for value in mapped_attrs
        ]
        mapped_attr_set = set(mapped_attrs)
        attribute_links.extend(
            {"name": value, "evidence_source": "extra_processed"}
            for value in info_attrs
            if value not in mapped_attr_set
        )

        voice_credits = [
            {"name": value, "credit_source": "char2cv"}
            for value in mapped_cvs
        ]
        mapped_cv_set = set(mapped_cvs)
        voice_credits.extend(
            {"name": value, "credit_source": "extra_processed"}
            for value in info_cvs
            if value not in mapped_cv_set
        )

        external_refs = []
        for bgm_id in bangumi_ids:
            external_refs.append(
                {
                    "external_source": "bangumi",
                    "external_key": bgm_id,
                    "metadata": {
                        "collects": bgm_info.get(bgm_id),
                        "medium_image": bgm_images.get(bgm_id),
                    },
                }
            )

        payload = {
            "title": name,
            "char2attr": mapped_attrs,
            "char2cv": mapped_cvs,
            "char2gender": char2gender.get(name),
            "char2subject": subjects,
            "extra_processed": extra,
            "moegirl2bgm": bangumi_ids,
        }
        characters.append(
            {
                "source_key": f"character:{name}",
                "display_name": name,
                "gender": char2gender.get(name),
                "source_url": _source_url(name),
                "payload": payload,
                "payload_hash": _payload_hash(payload),
                "names": _name_rows(name, extra),
                "profile": _profile(extra),
                "images": extra.get("image", []) if isinstance(extra.get("image"), list) else [],
                "attributes": attribute_links,
                "physical_traits": [
                    {"trait_type": "hair_color", "value": value}
                    for value in _as_list(extra.get("发色"))
                ] + [
                    {"trait_type": "eye_color", "value": value}
                    for value in _as_list(extra.get("瞳色"))
                ],
                "subjects": subjects,
                "works": [subject for subject in subjects if subject in works],
                "voice_credits": voice_credits,
                "external_refs": external_refs,
            }
        )

    attributes = []
    for name in sorted(all_attributes):
        attribute_types = []
        if name in hair_attrs:
            attribute_types.append("hair_color")
        if name in eye_attrs:
            attribute_types.append("eye_color")
        if name in fundamental_attrs:
            attribute_types.append("fundamental")
        if name in female_attrs:
            attribute_types.append("gender_hint_female")
        if name in male_attrs:
            attribute_types.append("gender_hint_male")
        if name in nogender_attrs:
            attribute_types.append("gender_hint_other")
        attributes.append(
            {
                "source_key": f"attribute:{name}",
                "name": name,
                "source_url": _attribute_url(attr2article.get(name)),
                "attribute_types": attribute_types,
            }
        )

    return MoeGirlDataset(
        source_artifacts=tuple(artifacts),
        characters=tuple(characters),
        attributes=tuple(attributes),
        subjects=tuple(sorted(all_subjects)),
        works=tuple(sorted(works)),
        people=tuple(sorted(all_people)),
        external_redirects=tuple(sorted((str(key), str(value)) for key, value in redirects.items())),
        is_complete_snapshot=offset == 0 and limit is None,
    )
