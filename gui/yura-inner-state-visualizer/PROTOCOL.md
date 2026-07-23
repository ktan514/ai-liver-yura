# State telemetry protocol

- Transport: UDP
- Producer destination: `127.0.0.1:8766`
- Encoding: UTF-8 JSON, one snapshot per datagram
- Direction: Yura core → visualizer only
- Delivery: best effort

```json
{
  "schema_version": 1,
  "observed_at": "2026-07-23T00:00:00+00:00",
  "emotion": {
    "mood": "neutral",
    "arousal": 0.5,
    "valence": 0.0,
    "talkativeness": 0.5
  },
  "drive": {
    "curiosity": 0.5,
    "engagement": 0.5,
    "boredom": 0.0,
    "energy": 0.7
  },
  "activity": { "type": null, "active": false, "pending_count": 0 },
  "attention": { "engaged": false },
  "stream": { "status": "idle" }
}
```

入力本文や観測対象の名前は送信しません。PC操作観測を追加する場合も、この状態表示プロトコルへ生テキストを混在させません。
