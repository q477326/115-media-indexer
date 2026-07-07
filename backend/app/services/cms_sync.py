from datetime import datetime, timezone
from urllib import error, request

from app.core.config import settings


def cms_sync_configured() -> bool:
    return bool(settings.cms_sync_url)


def trigger_cms_sync() -> dict:
    if not settings.cms_sync_url:
        raise ValueError("CMS_SYNC_URL 未配置")

    started_at = datetime.now(timezone.utc)
    req = request.Request(settings.cms_sync_url, method="GET")
    try:
        with request.urlopen(req, timeout=settings.cms_sync_timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status_code": response.getcode(),
                "message": "CMS 增量同步已触发",
                "response_text": payload[:2000],
                "triggered_at": started_at,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": False,
            "status_code": exc.code,
            "message": f"CMS 同步返回 HTTP {exc.code}",
            "response_text": body[:2000],
            "triggered_at": started_at,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "message": f"CMS 同步失败: {exc}",
            "response_text": None,
            "triggered_at": started_at,
        }
