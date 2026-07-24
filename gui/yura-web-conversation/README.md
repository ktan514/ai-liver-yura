# Yura Web Conversation

ゆらとの会話をブラウザで入出力し、VOICEVOXの音声をブラウザ上で再生する画面です。
`ai-liver-yura` モノレポの `gui/` 配下で、本体とは別プロセスとして動作します。

## 起動

最初にWeb会話画面を起動します。

```bash
cd ai-liver-yura/gui/yura-web-conversation
python3 server.py
```

ブラウザで `http://127.0.0.1:8770` を開き、「音声を有効にする」を押します。
次に別ターミナルでゆらを起動します。

```bash
cd ai-liver-yura
.venv/bin/python -m app
```

Web会話は既定で有効です。従来の管理者コンソール入力へ戻す場合は、次のように起動します。

```bash
YURA_WEB_CONVERSATION_ENABLED=0 .venv/bin/python -m app
```

## 通信

- Web画面: HTTP/SSE `127.0.0.1:8770`
- Webからゆらへの入力: UDP `127.0.0.1:8771`
- ゆらからWebへの文章・音声: HTTP `127.0.0.1:8770`

すべてlocalhostだけにバインドします。Web入力は通常ユーザー権限として扱われ、管理者コンソール入力とは分離されます。

ブラウザの自動再生制限があるため、音声は最初のボタン操作またはメッセージ送信で有効化されます。音声はFIFOで再生し、再生完了をゆら本体へ通知します。
