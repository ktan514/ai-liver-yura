# Yura Streaming Admin

配信準備、開始・終了、コメント状況、進行、診断、実行時設定をブラウザから操作する
管理画面です。`ai-liver-yura` モノレポの `gui/` 配下で、Coreとは別プロセスとして動作します。

## 起動

先にリポジトリ直下でCoreを起動します。

```bash
.venv/bin/python -m app
```

別のターミナルで管理画面のローカルサーバーを起動します。

```bash
.venv/bin/python gui/yura-streaming-admin/server.py
```

ブラウザで <http://127.0.0.1:8780> を開きます。待受ポートは `--port` で変更できます。

## 通信

- Web画面: HTTP/SSE `127.0.0.1:8780`
- Core Admin API: HTTP/SSE `127.0.0.1:8765`

ブラウザはStreaming Adminのローカルサーバーとのみ通信します。Core APIのトークンはブラウザへ
渡しません。Core APIの接続設定には `AI_LIVER_ADMIN_API_URL`、
`AI_LIVER_ADMIN_API_TOKEN`、`AI_LIVER_ADMIN_API_TIMEOUT`、
`AI_LIVER_ADMIN_OPERATOR` を使用します。

依存関係だけを個別に導入する場合は次を実行します。

```bash
.venv/bin/python -m pip install -r gui/yura-streaming-admin/requirements.txt
```
