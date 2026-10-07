"""Read-only keyword preview and Zernio delivery diagnostics."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from sqlalchemy.orm import Session

from app.models.bot_setting import BotSetting
from app.models.keyword import Keyword
from app.service.reply_engine import normalize_text
from app.service.product_response import keyword_response
from app.service.zernio_service import comment_keyword_variants, zernio_service
from app.service.automation_service import automation_service


def preview_comment(db: Session, text: str, keyword: str, response: str,
                    comment_reply: str | None, editing_id: int | None = None,
                    draft_active: bool = True) -> dict:
    """Simulate active account-wide comment rules, including the unsaved form."""
    rules = [
        (item.id, item.keyword, keyword_response(item), item.comment_reply, False)
        for item in db.query(Keyword).filter(Keyword.active.is_(True)).all()
        if item.id != editing_id
    ]
    if draft_active:
        rules.append((editing_id, keyword.strip(), response.strip(), (comment_reply or "").strip() or None, True))
    clean_text = normalize_text(text)
    matches = []
    for rule_id, word, dm_text, public_reply, is_draft in rules:
        variants = comment_keyword_variants(word) if public_reply else [word]
        mode = "contains" if public_reply else "exact"
        if any(
            (normalize_text(variant) in clean_text if public_reply else normalize_text(variant) == clean_text)
            for variant in variants if normalize_text(variant)
        ):
            matches.append({
                "id": rule_id, "keyword": word, "match_mode": mode,
                "dm_message": dm_text, "comment_reply": public_reply,
                "is_draft": is_draft,
            })

    setting = db.query(BotSetting).first()
    return {
        "matches": matches,
        "draft_disabled": not draft_active,
        "follow_gate_enabled": bool(setting and setting.follow_gate_enabled),
        "follow_gate_message": setting.follow_gate_message if setting and setting.follow_gate_enabled else None,
    }


def _latest_comment_result(automation_id: str) -> dict:
    svc = automation_service.active_service
    base_url = getattr(svc, "base_url", None) or ("https://api.postzen.dev/v1" if automation_service.provider == "postzen" else "https://zernio.com/api/v1")
    url = f"{base_url}/comment-automations/{quote(str(automation_id), safe='')}/logs"
    try:
        result = requests.get(url, headers=svc.headers, params={"limit": 10}, timeout=8)

        result.raise_for_status()
        logs = result.json().get("logs", [])
        comments = [
            log for log in logs
            if (log.get("source") == "comment") or (log.get("trigger") == "comment") or ("source" not in log and "trigger" not in log)
        ]

        latest = max(comments, key=lambda log: log.get("createdAt") or "", default=None)
        if not latest:
            return {"last_comment": None, "logs_error": False}
        return {
            "last_comment": {
                "dm_status": latest.get("status"),
                "dm_error": (latest.get("error") or "")[:300],
                "reply_status": latest.get("commentReplyStatus"),
                "reply_error": (latest.get("commentReplyError") or "")[:300],
                "created_at": latest.get("createdAt"),
            },
            "logs_error": False,
        }
    except (requests.RequestException, ValueError, TypeError):
        return {"last_comment": None, "logs_error": True}


def _configuration_differs(kw: Keyword, auto: dict) -> bool:
    expected_mode = "contains" if kw.comment_reply else "exact"
    expected_keywords = comment_keyword_variants(kw.keyword) if kw.comment_reply else [kw.keyword]
    return (
        ("matchMode" in auto and auto["matchMode"] != expected_mode)
        or ("keywords" in auto and set(auto["keywords"] or []) != set(expected_keywords))
        or ("dmMessage" in auto and auto["dmMessage"] != keyword_response(kw))
        or auto.get("alsoMatchInDms", False)
        or ("commentReply" in auto and (auto["commentReply"] or "") != (kw.comment_reply or ""))
    )


def keyword_delivery_statuses(db: Session) -> dict:
    """Get synced state, counters and the latest real comment outcome for each rule."""
    keywords = db.query(Keyword).all()
    if not automation_service.is_configured():
        provider_name = "پست‌زن" if automation_service.provider == "postzen" else "زرنیو"
        return {"available": False, "message": f"اتصال {provider_name} تنظیم نشده است", "keywords": []}

    automations = automation_service.list_comment_automations()
    svc = automation_service.active_service
    acc_id = getattr(svc, "account_id", None)
    by_name = {
        auto.get("name"): auto for auto in automations
        if auto.get("accountId") in (None, acc_id)
    }

    rows = []
    pending = {}
    for kw in keywords:
        auto = by_name.get(f"KW_{kw.id}_{kw.keyword}") or next(
            (item for name, item in by_name.items()
             if isinstance(name, str) and name.startswith(f"KW_{kw.id}_")), None
        )
        if not auto:
            state = "disabled" if not kw.active else "not_synced"
        elif not kw.active:
            state = "disabled_remote" if auto.get("isActive", True) else "disabled"
        else:
            state = "synced" if auto.get("isActive", True) else "remote_inactive"
            if state == "synced" and (auto.get("name") != f"KW_{kw.id}_{kw.keyword}"
                                       or _configuration_differs(kw, auto)):
                state = "config_mismatch"
        stats = (auto.get("stats") or {}) if auto else {}
        row = {
            "keyword_id": kw.id, "state": state,
            "stats": {
                "triggered": stats.get("triggered", 0),
                "dms_sent": stats.get("dmsSent", 0),
                "dms_failed": stats.get("dmsFailed", 0),
            },
            "last_comment": None, "logs_error": False,
        }
        rows.append(row)
        if auto and (auto.get("id") or auto.get("_id")):
            pending[kw.id] = (row, auto.get("id") or auto.get("_id"))

    if pending:
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as executor:
            futures = {executor.submit(_latest_comment_result, auto_id): row
                       for row, auto_id in pending.values()}
            for future in as_completed(futures):
                futures[future].update(future.result())
    local_ids = {kw.id for kw in keywords}
    orphan_names = sorted(
        name for name in by_name if isinstance(name, str) and name.startswith("KW_")
        and (len(name.split("_", 2)) != 3 or not name.split("_", 2)[1].isdigit()
             or int(name.split("_", 2)[1]) not in local_ids)
        and by_name[name].get("isActive", True)
    )
    return {"available": True, "keywords": rows, "orphan_automations": orphan_names}
