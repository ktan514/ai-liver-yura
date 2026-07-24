# 会話品質改善 1〜9 実装記録

## 目的

会話の暴走を単純な待機時間だけで抑えるのではなく、発話権、ユーザー反応、発話目的、反復、話題種別、未回答問い、存在設定、プロンプト偏り、観測指標を同じモデルで扱う。

## 1. 会話状態

`ConversationFloorState` を追加した。

- `IDLE`
- `RESPONDING`
- `YIELDING_TO_USER`
- `AUTONOMOUS_TALK`

通常応答の完了後は `YIELDING_TO_USER` へ遷移し、所定の余白が終わるまで自律発話を許可しない。

## 2. ユーザー反応

`UserResponseKind` と次の観測値を追加した。

- `user_response_observed`
- `user_response_kind`
- `last_user_input_at`

沈黙は `NONE` のままとし、関心・同意・継続要求へ変換しない。話題変更時は同一話題ターン数をリセットする。

## 3. 発話目的

`SpeechPurpose` を追加した。

- 回答
- 共感
- 感想
- 軽い問い
- 話題導入
- 話題終了
- 説明
- タスク進行

直近発話は `SpeechRecord` として目的、話題、主語、感情、情景語とともに保持する。

## 4. 意味構造による反復検出

`ConversationRepetitionDetector` を追加した。文字列類似度だけでなく、次の一致を加点する。

- 発話目的
- 話題
- 主語
- 感情
- 情景語

閾値を超えた候補は、再生成または話題終了判断に利用できる。

## 5. 話題種別別の継続上限

`ConversationTurnPolicy` を追加した。

- ユーザー由来話題: 自律継続は原則1回
- 自律開始話題: 原則2回
- タスク: 固定上限なし
- ゲーム: 固定上限なし

説明、作業、ゲームを通常雑談と同じ上限で切らない。

## 6. 未回答問い

`OpenPrompt` と登録・期限切れ・解決処理を追加した。軽い問いを発した後も会話全体を停止せず、後から関連回答が来た場合に結び付けられる。

## 7. 存在設定

`CharacterExistenceProfile` を追加した。

- 存在種別
- 存在環境
- 身体能力
- 感覚能力
- 経験境界
- 世界との関係

既存の `behavior_policy` へ自動展開するため、現行Prompt Builderとの互換性を維持する。

## 8. プロンプト例の偏り抑制

キャラクター共通方針に、海だけでなくゲーム、技術、日常、音楽、現在の気分へ例を分散して解釈する規則を追加した。例文の固有語句ではなく、短い導入、一つの展開、自然な終了という構造だけを参照する。

## 9. 観測ログ

`ConversationQualitySnapshot` を追加した。

- `consecutive_agent_turns`
- `seconds_since_user_input`
- `same_topic_turns`
- `semantic_similarity`
- `speech_purpose`
- `handoff_state`
- `autonomous_resume_reason`

`as_trace_fields()` により既存 `TraceLogger` へそのまま渡せる形式にする。

## 実装ファイル

- `app/domain/conversation_flow.py`
- `app/runtime/conversation_flow_controller.py`
- `app/runtime/conversation_quality.py`
- `app/domain/character/character_profile.py`

## テスト

- `tests/test_conversation_flow_controller.py`
- `tests/test_conversation_quality.py`
- `tests/test_character_existence_profile.py`

## 適用上の境界

今回追加した会話フローは、既存の待機時間と `TopicContinuationEvaluator` を置き換えるのではなく、その上位で判断根拠を統一するための基盤である。ランタイムから利用する際は、ユーザー入力受信、応答開始、出力成功、自律計画開始の各境界で `ConversationFlowController` を呼び出す。
