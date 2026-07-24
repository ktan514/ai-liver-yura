# LLMロール分離・発話整合性設計

## 1. 目的

AIライバーの入力解釈、行動判断、実行、キャラクター表現を分離し、未知の入力や将来追加されるPluginにも適用できる汎用構造を定義する。

特定ワードや特定ゲーム向けの条件分岐をCoreへ追加し続ける方式は採用しない。
LLMは意味を推定するが、Activityの存在、実行権限、実行成功を決定しない。

## 2. 設計原則

- Situation Evaluatorは世界と入力を客観的に解釈する
- Behavior Plannerは次に行うActivityを選択する
- Activity Registryは存在するActivityの正本とする
- Capability Registryは現在実行可能なCapabilityの正本とする
- Plugin / Activity Executorは実処理を行う
- Activity Resultは実際に起きた事実の正本とする
- Response Contextは事実と表現可能範囲をCharacter LLMへ渡す
- Character LLMはキャラクターとしての表現だけを生成する
- Response Validatorは発話と事実の整合性を保証する

## 3. 全体フロー

```text
External Event
  ↓
Situation Evaluator
  ↓
Structured Situation Analysis
  ↓
Behavior Planner
  ↓
Behavior Plan
  ↓
Activity Registry照合
  ↓
Capability Registry検証
  ↓
Activity実行
  ↓
Activity Result
  ↓
Response Context Builder
  ↓
Character LLM
  ↓
Character Response
  ↓
Response Validator
  ↓
Validated Response
  ↓
ActionPlanner
  ↓
ActionPlanGroup / Output Unit
```

Character LLMへ外部入力だけを直接渡し、意味解析、行動判断、実行宣言、最終発話を一度に行わせてはならない。

## 4. Situation Evaluator

### 責務

- 入力の意味解析
- speech actの特定
- Activity候補の選択
- operationの判定
- goalとconstraintsの抽出
- 否定、仮定、過去、知識質問の判定
- OngoingActivityとの関係整理
- confidenceの算出
- 必要時の確認提案

### 非責務

- 最終発話文の生成
- Activityの存在確定
- Capabilityの利用可否判断
- Providerの決定
- 実行成功の決定

### 出力例

```json
{
  "decision": "start_activity",
  "activity_type": "shiritori",
  "operation": "start",
  "speech_act": "proposal",
  "goal": "深海生物に限定したしりとりを行う",
  "constraints": {"theme": "深海生物"},
  "negated": false,
  "hypothetical": false,
  "past_reference": false,
  "knowledge_question": false,
  "confidence": 0.95
}
```

出力はSchema検証し、架空Activity、不正operation、不正constraintsを採用しない。

## 5. ActivityDefinitionとRegistry

ActivityDefinitionは最低限、次を持つ。

- `activity_type`
- `description`
- `semantic_descriptions`
- `supported_operations`
- `constraints_schema`
- `required_capability`
- `provider_plugin_id`
- 任意の決定論的Matcher

Coreは個別Activity名や個別表現を知らない。
全ActivityDefinitionを共通形式で評価し、高信頼の単一Matcher候補がある場合だけ決定論的に採用する。
未確定・競合時はSituation Evaluatorへ渡す。

Pluginが無効でもActivityDefinitionは意味認識候補として参照できる。
実行可否はCapability Registryが別に判断する。

## 6. Behavior Planner

Behavior Plannerは、Situation Evaluatorの解析結果、AgentState、DriveState、EmotionState、TopicState、OngoingActivity、ActivityDefinitionを基にBehavior Planを作る。

主なdecision:

- `start_activity`
- `continue_activity`
- `stop_activity`
- `conversation`
- `ask_confirmation`
- `wait`
- `no_action`

Behavior PlannerはCapabilityを実行せず、発話本文も生成しない。

## 7. Capability検証と実行

Behavior PlanのActivityDefinitionから`required_capability`と`provider_plugin_id`を導出する。
LLMが返したCapabilityやProviderは信用しない。

```text
Behavior Plan
→ ActivityDefinition照合
→ Capability Registry検証
→ 実行またはrejected
```

Capability不足、Plugin無効、初期化失敗は例外ではなく正常なActivity Resultとして扱う。
Command実行直前にも再検証する。

## 8. Activity Result

Activity Resultは発話に依存しない共通モデルとし、実際に起きた事実の正本とする。

最低項目:

```text
activity_type
operation
status
capability
provider_plugin_id
result_payload
failure_reason
constraints
started_at
finished_at
```

status:

- `succeeded`
- `rejected`
- `failed`
- `canceled`
- `waiting_input`

Character LLMはActivity Resultを書き換えない。

## 9. Response Context

Response Context Builderは、Activity Result、Behavior Plan、AgentState、OngoingActivity、会話文脈から、Character LLMが表現可能な事実を整理する。

最低項目:

```text
user_input
activity_type
operation
execution_status
failure_reason
result_summary
allowed_claims
forbidden_claims
conversation_goal
emotion_snapshot
ongoing_activity_context
```

allowed / forbidden claimsは特定機能の固定文一覧ではなく、Activity Resultとoperationから共通ルールで生成する。

## 10. Character LLM

### 責務

- キャラクター口調
- 感情表現
- 自然な発話
- 表情候補
- ジェスチャー候補
- 会話のつなぎ方

### 非責務

- Activity選択
- Capability判定
- 実行
- 成功・失敗の確定
- RegistryにないActivityの追加

Character LLMにはCharacterProfile、EmotionState、現在の相手とのRelationshipState集約値、
直近のユーザー/ゆら会話Turn、直近発話、TopicHistory、Response Context、Activity Resultを渡す。
RelationshipStateはBehavior Planningにも渡すが、Capabilityや実行事実の判定根拠にはしない。
Character LLMは発話・表情・ジェスチャーに加え、音声エンジン固有値ではない
`VoiceIntent.style`を返す。CoreはEmotionStateをVOICEVOX等のパラメータへ直接変換せず、
EmotionState自身も表現・反応・固定待機秒を決定しない。自律Activityの開始間隔など
行動選択に必要な解釈は専用Policy、発話・表情・身振りの解釈はCharacter LLMが担当する。
SPEAK ActionからSpeechSynthesizer PortへVoiceIntentを伝達する。

表現意図が発話途中で変化する場合、Character LLMは`ReactionPlan`内に2〜8件の
`ReactionSegment`を返す。各Segmentはspeech、expression、gesture、VoiceIntent、
0〜3秒のpause_after_secondsだけを持つ。単語単位には分割せず、変化がない場合は
従来の単一Segmentとして扱う。Action PlannerはSegment順をmetadataへ固定し、
Schedulerは各Segmentの字幕・表情・身振りを音声より先に実行してから次Segmentへ進む。
特定エンジンの話者ID、style ID、pitch、speed等はこの契約へ含めない。

各LLM RoleのResponseGenerator AdapterはLLM Provider Pluginで包み、
`llm.provider.default`、`llm.provider.situation_evaluator`、
`llm.provider.character`、`llm.provider.response_validator`として独立管理する。
Provider例外時は該当Capabilityだけを解除し、Role間で障害を連鎖させない。

## 11. Response Validator

Character ResponseをAction化する前に、Activity Resultとの整合性を検証する。

検証項目:

- 未実行処理を実行済みと主張していないか
- rejected / failed / canceledを成功したように表現していないか
- succeeded Resultがない外部操作の成功を主張していないか
- OngoingActivity状態と矛盾していないか
- 内部用語をユーザーへ露出していないか
- allowed / forbidden claimsに違反していないか

検証は特定キーワードのブラックリストだけで実装しない。

```text
発話がActivityの開始・実行・成功を主張する
かつ
対応するsucceeded Activity Resultが存在しない
→ invalid
```

invalid時はCharacter LLMへ修正理由を渡して最大1回だけ再生成する。
再生成後もinvalid、またはValidator障害時は安全な応答へ置換する。

## 12. LLMロール設定

```yaml
llm_roles:
  situation_evaluator:
    provider: openai
    model: ...
    temperature: 0.1

  character:
    provider: openai
    model: ...
    temperature: 0.8

  response_validator:
    provider: openai
    model: ...
    temperature: 0.0
```

初期状態では同一Provider・Modelを共有してよい。
ただしFactory、設定、PromptBuilder、Portはロール別に分離する。

各ロールのPrompt構築は、`SituationPromptBuilder`、
`CharacterRolePromptBuilder`、`ResponseValidationPromptBuilder`の契約を通じて
Runtimeへ注入する。Runtimeサービスは具体Prompt Builderを生成・importせず、
Composition Rootだけが使用する実装を選択する。

## 13. 既存クラスからの移行

- `BehaviorPlanner`: Situation Evaluator結果を使う行動選択へ整理する
- `ResponseGenerator`: Character LLM用Portへ整理する
- `PromptBuilder`: Situation Evaluator用、Character用、Validator用に責務分離する
- `ActionPlanner`: 検証済みCharacter ResponseだけをActionPlanGroupへ変換する
- `RuntimeCoordinator`: 個別Activity判定を持たず、ServiceとLoopの調停へ寄せる
- `ActivityManager`: OngoingActivityとTurn状態を管理する
- `ActivityResult`: Action完了、Plugin拒否、失敗、待機状態を共通表現する

移行中も既存Portを急に削除せず、AdapterまたはFacadeで段階的に置き換える。

## 14. 汎用性要件

次の種類を同じ基盤で扱えること。

- ゲーム
- 外部検索
- OBS操作
- 配信開始・停止
- 音楽再生
- アバター表情・動作
- ファイル操作
- 外部サービス操作
- 将来追加される未知のPlugin Activity

Core変更なしにActivityDefinitionとPluginを追加できることを目標とする。

## 15. ログ

INFO:

- 最終Behavior判断
- Activity開始・継続・完了・拒否・失敗
- Character Response生成完了
- Validator拒否・置換
- 重要なフォールバック

DEBUG:

- Situation Evaluator入力
- `SituationState`は直近Event種別・入力元・注意対象・Activityスナップショットを継続し、入力本文は保持しない
- Situation Evaluator、Behavior Planner、Character LLMは同じ状況スナップショットを役割別に参照する
- ActivityDefinition候補
- LLM生出力
- Schema解析結果
- Behavior Plan
- Capability検証結果
- Activity Result
- Response Context
- Character LLM入力・出力
- Validator入力・結果
- 再生成・置換理由

Prompt、入力、生成結果のログは設定で有効化し、APIキーやToken等を共通マスクする。

## 16. テスト方針

- 未知の言い回しを登録済みActivityへ対応付けられる
- Plugin無効でもActivityを認識できる
- Capability不足でrejected Resultになる
- rejected / failed時に成功発話を許可しない
- succeeded時だけ実行済み発話を許可する
- 架空Activity、架空Capability、不正JSONを実行しない
- 低確信度時に確認またはConversationへ遷移する
- Character LLMがActivity実行可否を決定しない
- Validatorが事実と矛盾する発話を拒否する
- ゲーム以外のダミーActivityでも同じ経路が動作する
- 全既存テストに回帰がない

## 17. ドキュメント責任

- 本設計書と`docs/source_file_plan.md`の更新責任はChatGPT側とする
- Codexは設計書を参照して実装するが、設計書ファイルを変更しない
- 実装結果に設計との差異がある場合、Codexは差異を報告し、ChatGPT側で設計書へ反映する
