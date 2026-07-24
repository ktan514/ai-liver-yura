# Local protocol

## Browser/UI → Yura

WebサーバーがUDP `127.0.0.1:8771` へ送ります。

```json
{"schema_version":1,"type":"user_text","text":"こんにちは"}
```

送信元は本体側で `web`、権限は `USER` に固定されます。

## Yura → Browser/UI

本体は `POST /api/output` へ表示文を、`POST /api/audio` へWAVを送ります。WebサーバーはSSE `/events` でブラウザへ通知します。

音声POSTは、ブラウザが再生を完了して `POST /api/audio/{audio_id}/complete` を返すまで応答を保留します。これにより本体の発話完了時刻と実際のWeb音声再生を同期します。
