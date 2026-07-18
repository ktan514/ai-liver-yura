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
    "automatic": "自動",
    "manual": "手動",
    "event_driven": "イベント駆動",
    "fresh": "最新",
    "stale": "情報が古い",
    "in_progress": "処理中",
    "completed": "完了",
    "not_started": "未実行",
    "waiting": "人間の操作待ち",
    "live": "配信中",
    "ending": "終了処理中",
    "ended": "終了済み",
}


def status_label(value: str) -> str:
    return STATUS.get(value, value)
