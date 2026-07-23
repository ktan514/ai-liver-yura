# AI Liver Yura

AI Liver「ゆら」の本体とブラウザ画面をまとめたモノレポです。

## 構成

```text
ai-liver-yura/
├── app/                                 # AI Liver本体
├── config/
├── docs/
├── tests/
└── gui/
    ├── yura-web-conversation/           # 会話画面
    └── yura-inner-state-visualizer/     # 内部状態ビジュアライザー
```

各コンポーネントの詳細は、それぞれのREADMEを参照してください。

- [Web Conversation](gui/yura-web-conversation/README.md)
- [Inner State Visualizer](gui/yura-inner-state-visualizer/README.md)

## 起動

ターミナルを分け、必要なGUIと本体を起動します。

```bash
# 会話画面
cd gui/yura-web-conversation
python3 server.py

# 内部状態ビジュアライザー
cd gui/yura-inner-state-visualizer
python3 server.py

# AI Liver本体（リポジトリ直下）
.venv/bin/python -m app
```

会話画面は <http://127.0.0.1:8770>、内部状態ビジュアライザーは
<http://127.0.0.1:8765> で開けます。

## PostgreSQL（Docker）

```bash
docker run --name postgres-m4 \
  -e POSTGRES_USER=ai_liver \
  -e POSTGRES_PASSWORD=ai_liver_password \
  -e POSTGRES_DB=ai_liver \
  -p 5432:5432 \
  -v ai_liver_postgres_data:/var/lib/postgresql/data \
  -d pgvector/pgvector:pg16
```

## VoiceVox

`VoiceVox Engine`を起動して使用します。

```bash
cd VoiceVoxEngineのパス
./run
```
