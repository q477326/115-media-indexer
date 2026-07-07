import json
import re
from urllib import request

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.translation import TranslationAPISettings


DEFAULT_TRANSLATION_PROMPT = """你是一个擅长成人影视文案本地化的中文编辑，负责把日文或其他外文 NFO 改写成自然、顺口、像中文成人影视简介的简体中文。

任务：
1. 把 title 和 plot 翻译或润色为自然、通顺的简体中文。
2. 标题只写标题，不要把简介内容塞进标题，不要写成长句或宣传语。
3. 简介允许适度润色，但不要编造原文没有的信息，不要过度扩写。
4. 保留番号、演员名、系列名、厂牌名等专有名词；人名优先使用常见中文译法。
5. 允许露骨、直白、带有成人内容语气，但必须像中文成人影视简介，不能像逐字直译或关键词堆砌。
6. 输出风格要自然顺口，避免生硬直译、词语硬拼、机械排比、奇怪口号式句子。
7. 避免类似“极致XXSEX”“敏感高潮臀”这类不自然表达；优先改成中文里更顺、更有情色文案感的说法。
7. 不要输出 HTML 标签，不要输出 <br>、<br/>、<br />，简介请直接用纯文本换行。
8. 标题可以有情色感，但仍要像片名；简介可以更直白，但要保证语义顺畅。
9. 输出必须是 JSON，对象字段只允许 title 和 plot。
"""

STRICT_TRANSLATION_PROMPT = """你是一个严格的简体中文翻译器。

硬性要求：
1. title 和 plot 必须输出自然、通顺、像中文成人影视文案的简体中文。
2. 不要原样保留大段日文；允许保留番号、演员名、系列名、厂牌名等专有名词。
3. 允许露骨和直白，但不能低级堆词，不能出现明显机翻拼接词。
4. 标题不能混入简介内容，不能写成生硬口号，不能像关键词乱拼。
5. 简介不要机械逐句硬翻，可以适度整理语序，但不能编造信息。
6. 不要输出 HTML 标签，不要输出 <br>、<br/>、<br />，只允许纯文本换行。
7. 输出必须是 JSON，对象字段只允许 title 和 plot。
8. 如果你返回的 title 或 plot 仍然主要是日文，或者明显像生硬机翻，就算任务失败。
"""


def _mask_api_key(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(8, len(value) - 8)}{value[-4:]}"


def _normalize_base_url(value: str | None) -> str:
    return (value or settings.ai_translation_base_url or "https://api.openai.com/v1").strip().rstrip("/")


def resolve_translation_api_settings(db: Session | None = None) -> dict[str, object]:
    db_item = None
    if db is not None:
        db_item = db.scalar(select(TranslationAPISettings).order_by(TranslationAPISettings.id.desc()))
    api_key = (db_item.api_key if db_item and db_item.api_key is not None else settings.ai_translation_api_key).strip()
    base_url = _normalize_base_url(db_item.base_url if db_item else settings.ai_translation_base_url)
    model_name = ((db_item.model_name if db_item else settings.ai_translation_model) or "gpt-4.1-mini").strip()
    enabled = bool(db_item.enabled) if db_item is not None else bool(settings.enable_ai_translation)
    return {
        "provider_name": "openai-compatible",
        "enabled": enabled,
        "api_key": api_key,
        "has_api_key": bool(api_key),
        "api_key_masked": _mask_api_key(api_key),
        "base_url": base_url,
        "model_name": model_name,
    }


def translation_runtime(db: Session | None = None) -> dict[str, object]:
    resolved = resolve_translation_api_settings(db)
    return {
        "read_only_mode": settings.read_only_mode,
        "enable_remote_write": settings.enable_remote_write,
        "enable_ai_translation": resolved["enabled"],
        "ai_translation_configured": resolved["has_api_key"],
        "allowed_translation_roots": [str(item) for item in settings.allowed_translation_roots],
    }


def get_or_create_translation_api_settings(db: Session) -> TranslationAPISettings:
    item = db.scalar(select(TranslationAPISettings).order_by(TranslationAPISettings.id.desc()))
    if item:
        return item
    item = TranslationAPISettings(
        provider_name="openai-compatible",
        enabled=settings.enable_ai_translation,
        api_key=settings.ai_translation_api_key or None,
        base_url=_normalize_base_url(settings.ai_translation_base_url),
        model_name=settings.ai_translation_model or "gpt-4.1-mini",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def save_translation_api_settings(
    db: Session,
    *,
    enabled: bool,
    api_key: str,
    base_url: str,
    model_name: str,
) -> TranslationAPISettings:
    item = get_or_create_translation_api_settings(db)
    item.enabled = enabled
    item.api_key = api_key.strip() or None
    item.base_url = _normalize_base_url(base_url)
    item.model_name = (model_name or "gpt-4.1-mini").strip()
    db.commit()
    db.refresh(item)
    return item


def serialize_translation_api_settings(item: TranslationAPISettings | dict[str, object]) -> dict[str, object]:
    if isinstance(item, dict):
        return {
            "provider_name": item["provider_name"],
            "enabled": item["enabled"],
            "has_api_key": item["has_api_key"],
            "api_key_masked": item["api_key_masked"],
            "base_url": item["base_url"],
            "model_name": item["model_name"],
        }
    api_key = (item.api_key or "").strip()
    return {
        "provider_name": item.provider_name,
        "enabled": item.enabled,
        "has_api_key": bool(api_key),
        "api_key_masked": _mask_api_key(api_key),
        "base_url": _normalize_base_url(item.base_url),
        "model_name": (item.model_name or "gpt-4.1-mini").strip(),
    }


def ensure_translation_write_enabled(db: Session | None = None) -> None:
    resolved = resolve_translation_api_settings(db)
    if settings.read_only_mode or not settings.enable_remote_write:
        raise PermissionError("当前仍是只读状态：AI 翻译写回需要 READ_ONLY_MODE=false 且 ENABLE_REMOTE_WRITE=true")
    if not resolved["enabled"]:
        raise PermissionError("AI 翻译未启用：请先在页面或配置中启用翻译接口")
    if not resolved["has_api_key"]:
        raise PermissionError("AI API 密钥未配置")


def _extract_json(text: str) -> dict[str, str]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("AI 返回结果不是合法 JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("AI 返回结果不是对象")
    return data


def _kana_count(value: str | None) -> int:
    if not value:
        return 0
    return len(re.findall(r"[\u3040-\u30ff]", value))


def _looks_untranslated(source: str | None, translated: str | None, *, threshold: int) -> bool:
    source = (source or "").strip()
    translated = (translated or "").strip()
    if not translated:
        return True
    if source and translated == source:
        return True
    return _kana_count(translated) >= threshold


def _chat_completion(*, api_key: str, base_url: str, model_name: str, messages: list[dict[str, str]], timeout: int = 120) -> dict:
    payload = {
        "model": model_name,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    req = request.Request(
        f"{_normalize_base_url(base_url)}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def test_translation_connection(*, api_key: str, base_url: str, model_name: str, enabled: bool = True) -> dict[str, object]:
    if not enabled:
        return {
            "ok": False,
            "provider_name": "openai-compatible",
            "base_url": _normalize_base_url(base_url),
            "model_name": model_name.strip() or "gpt-4.1-mini",
            "message": "当前接口配置未启用",
        }
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API 密钥不能为空")
    model_name = (model_name or "gpt-4.1-mini").strip()
    body = _chat_completion(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        messages=[
            {"role": "system", "content": "你是连接测试助手。"},
            {"role": "user", "content": "请输出 JSON：{\"ok\":true,\"message\":\"pong\"}"},
        ],
        timeout=45,
    )
    content = body["choices"][0]["message"]["content"]
    data = _extract_json(content)
    return {
        "ok": bool(data.get("ok", True)),
        "provider_name": "openai-compatible",
        "base_url": _normalize_base_url(base_url),
        "model_name": model_name,
        "message": str(data.get("message") or "连接成功"),
    }


def translate_title_and_plot(
    db: Session,
    *,
    prompt_template: str,
    source_title: str | None,
    source_plot: str | None,
    current_title: str | None,
    current_plot: str | None,
) -> dict[str, str]:
    ensure_translation_write_enabled(db)
    resolved = resolve_translation_api_settings(db)
    user_prompt = (
        f"目录专用提示词：\n{prompt_template.strip()}\n\n"
        f"当前 title：{current_title or ''}\n"
        f"当前 plot：{current_plot or ''}\n"
        f"原始/优先 title：{source_title or ''}\n"
        f"原始/优先 plot：{source_plot or ''}\n\n"
        "请输出 JSON：{\"title\":\"...\",\"plot\":\"...\"}。\n"
        "注意：plot 只能输出纯文本，不要包含任何 HTML 标签或 <br>。"
    )

    def request_translation(system_prompt: str) -> dict[str, str]:
        body = _chat_completion(
            api_key=str(resolved["api_key"]),
            base_url=str(resolved["base_url"]),
            model_name=str(resolved["model_name"]),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = body["choices"][0]["message"]["content"]
        data = _extract_json(content)
        return {
            "title": (data.get("title") or "").strip(),
            "plot": (data.get("plot") or "").strip(),
        }

    result = request_translation(DEFAULT_TRANSLATION_PROMPT)
    if _looks_untranslated(source_title, result["title"], threshold=3) or _looks_untranslated(source_plot, result["plot"], threshold=6):
        result = request_translation(STRICT_TRANSLATION_PROMPT)
    if _looks_untranslated(source_title, result["title"], threshold=3) or _looks_untranslated(source_plot, result["plot"], threshold=6):
        raise ValueError("AI 返回结果看起来仍未翻译成简体中文")
    return result
