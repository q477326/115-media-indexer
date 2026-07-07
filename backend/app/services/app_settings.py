from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULT_TRANSLATION_PROMPT = """你负责把当前目录中的 NFO 标题和简介整理成自然、顺口、像中文成人影视简介的简体中文。
要求：
1. 标题只写标题，不要把简介内容塞进标题，也不要写成长句或宣传语。
2. 保留番号、演员名、系列名、厂牌名等专有名词；人名优先使用常见中文译法。
3. 简介可以适度润色，但不要编造不存在的信息，不要过度扩写。
4. 允许露骨、直白、带有成人内容语气，但必须读起来像正常中文，而不是逐字硬译。
5. 避免生硬直译、关键词堆砌、机械重复和奇怪的口号式句子。
6. 可以更香艳一点，但核心仍然是通顺、自然、有画面感。
7. 不要输出 HTML 标签，不要输出 <br>、<br/>、<br />，简介请直接用纯文本换行。
8. 如果原文已经是合格中文，只做轻微修正。"""

DEFAULT_APP_SETTINGS: dict[str, dict[str, Any]] = {
    "organizer_task": {
        "source_root": "/mnt/clouddrive/115open/原始库/小姐姐/骑兵",
        "output_root": "/mnt/clouddrive/115open/小姐姐/骑兵",
        "reference_scope_prefix": "骑兵/",
    },
    "one_click_ingest": {
        "source_root": "/mnt/clouddrive/115open/云下载",
        "output_root": "/mnt/clouddrive/115open/原始库/不正常视频/qb/骑兵/洗版",
    },
    "translation_defaults": {
        "name": "骑兵自动翻译监控",
        "folder_path": "/mnt/local-media/小姐姐/骑兵",
        "prompt_template": DEFAULT_TRANSLATION_PROMPT,
        "enabled": True,
        "recursive": True,
        "auto_translate": True,
    },
    "nfo_tag_defaults": {
        "folder_path": "/mnt/local-media/小姐姐/骑兵",
        "search_type": "title",
    },
    "western_poster_defaults": {
        "root": "/mnt/local-media/data/strm/原始库/不正常视频/link/欧美",
        "state_file": "/data/western-poster-state.json",
        "process_all": False,
        "dry_run": True,
    },
}


def _flat_key(category: str, key: str) -> str:
    return f"{category}.{key}"


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _decode(value: str) -> Any:
    return json.loads(value)


def get_app_settings(db: Session) -> dict[str, dict[str, Any]]:
    output = json.loads(json.dumps(DEFAULT_APP_SETTINGS, ensure_ascii=False))
    rows = db.scalars(select(AppSetting)).all()
    for row in rows:
        if "." not in row.key:
            continue
        category, key = row.key.split(".", 1)
        output.setdefault(category, {})
        output[category][key] = _decode(row.value)
    return output


def save_app_settings(db: Session, payload: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    existing = {
        row.key: row
        for row in db.scalars(select(AppSetting).where(AppSetting.category.in_(payload.keys()))).all()
    }
    for category, values in payload.items():
        for key, value in values.items():
            flat = _flat_key(category, key)
            row = existing.get(flat)
            if row is None:
                row = AppSetting(category=category, key=flat, value=_encode(value))
                db.add(row)
            else:
                row.value = _encode(value)
    db.commit()
    return get_app_settings(db)
