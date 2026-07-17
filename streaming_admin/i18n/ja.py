STATUS = {
    "authentication_required": "認証が必要",
    "authentication_in_progress": "認証中",
    "authenticated": "認証済み",
    "authentication_failed": "認証失敗",
    "created": "未準備",
    "preparing": "準備中",
    "ready": "準備完了",
    "failed": "準備失敗",
    "healthy": "正常",
    "degraded": "一部制限",
    "unavailable": "利用不可",
    "unknown": "不明",
}


def status_label(value: str) -> str:
    return STATUS.get(value, value)
