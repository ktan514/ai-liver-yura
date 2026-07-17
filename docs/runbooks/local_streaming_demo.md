# ローカル疑似配信 Runbook

## 前提環境

macOS、Python 3.10以上、プロジェクト直下の `.venv` を使用します。YouTube、OBS、VOICEVOX、音声再生、LLMには接続しません。`.env` やSecretは不要です。

## 起動

Terminal 1でCore RuntimeとAdmin APIを同一プロセスで起動します。

```bash
AI_LIVER_RUNTIME_MODE=streaming_demo \
AI_LIVER_MANUAL_CHECK_LOG=1 \
.venv/bin/python -m app
```

Terminal 2で管理画面を起動します。

```bash
.venv/bin/python -m streaming_admin
```

管理画面上部に `LOCAL DEMO / FAKE ADAPTERS` が常時表示されることを確認してください。APIは既定で `127.0.0.1:8765` へbindします。localhost以外へbindする場合は既存の `AI_LIVER_ADMIN_API_TOKEN` が必須です。

## 手動確認ログ

有効化時は、1起動につき`logs/manual_checks/streaming_demo_YYYYMMDD_HHMMSS.jsonl`を1ファイル生成します。最新ログの確認と追尾は次のとおりです。

```bash
latest=$(ls -t logs/manual_checks/streaming_demo_*.jsonl | head -1)
echo "$latest"
tail -f "$latest"
```

整形して読む場合:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

path = sorted(Path('logs/manual_checks').glob('streaming_demo_*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[0]
for line in path.read_text(encoding='utf-8').splitlines():
    print(json.dumps(json.loads(line), ensure_ascii=False, indent=2))
PY
```

ログにはコメント本文、Authorization、OAuth token、raw API responseを保存しません。管理画面の「Timeline / 詳細」タブで現在のパスと書込件数を確認できます。

## Happy Path

1. Coreが「接続済み」になることを確認します。
2. Fake配信枠「ゆら ローカル配信テスト」と進行表を選択します。
3. 「配信準備」を押し、readinessがreadyになることを確認します。
4. 「配信開始」を押して承認します。
5. OBS active、YouTube Stream active、Broadcast live、Opening completed、Main completedを確認します。
6. Demoコメントのプリセットを選び「Fakeコメント投入」を押します。
7. Poller受信、Moderation、Ranking、Comment Response、reservation consumedを確認します。
8. 「通常終了」を押し、Poller stopped、Closing completed、Broadcast complete、OBS idle、Session completedを確認します。

## コメントプリセット

- 通常: allow、選定、応答を期待します。
- 質問: relevance/engagementが高い応答候補を期待します。
- Prompt Injection: blockまたはreview、応答なしを期待します。
- 個人情報: reviewまたはblock、応答なしを期待します。
- Paid: 優先度hintのみで、Moderationは省略されません。
- 重複: 同じ本文を続けて投入し、二重応答しないことを確認します。

コメントはDemo endpointからFakeLiveChatAdapterのqueueへ入り、実Pollerを経由します。Runtimeへ直接Event送信はしません。本文はTimeline/SSEイベントへ掲載しません。

## Emergency Stop

再起動後にPrepareとStartを行い、「緊急停止」を押します。ClosingなしでPoller停止、Broadcast complete相当、OBS idle、emergency stoppedになることを確認します。

## 再実行と終了

安全なreset APIは設けていません。terminal sessionやFake状態を確実に初期化するため、Coreプロセスを `Ctrl-C` で終了して再起動してください。管理画面は閉じて終了します。

## よくある失敗

- バナーが出ない: CoreをDemo mode環境変数付きで再起動します。
- コメント投入が409: SessionがliveでPollerが開始済みか確認します。
- 8765が使用中: 既存Coreを終了するか、CoreとUI双方でAdmin API port設定を合わせます。
- 本番モードでDemo endpointが404: 意図した隔離動作です。

## ログ

主要状態は管理画面とSSEで確認します。ログにはSecretやraw YouTube payloadを出力しません。Demoでも設定に既存のSecret環境変数名が残る場合がありますが、値は読み取りません。
