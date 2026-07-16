# Plugin–Core 接続契約

- **Version:** 1.0.0
- **目的:** AIライバーCoreと任意Pluginの共通接続仕様を定義する
- **位置づけ:** `ai_liver_architecture_policy.md`を補足する共通契約
- **対象:** Games、Streaming、YouTube、OBS、TTS、STT、Avatar、Search、Moderation、Storage、LLM Providerなど

## 1. 基本方針

Pluginは、Coreへ任意追加される機能単位である。

CoreはPlugin固有の実装や外部サービスを知らず、共通契約だけを通じてPluginを利用する。

```text
Core Runtime
    ↓
Plugin Contract
    ↓
Plugin
    ↓
Port / Adapter
    ↓
External Service
```

Pluginが無効、初期化失敗、依存先停止、Capability喪失となった場合でも、Coreの通常動作は継続できなければならない。

## 2. 責務境界

### 2.1 Coreの責務

Coreは次を担当する。

- Pluginの登録とライフサイクル管理
- Plugin設定の受け渡し
- Capability Registryの管理
- Activity Definitionの収集
- Situation EvaluatorおよびBehavior Plannerへの候補提供
- Activity Planの検証
- Plugin Commandの実行要求
- Plugin実行結果の受理
- Ongoing Activityの共通状態管理
- Action Planの生成
- Action Schedulerによる実行制御
- Character LLMおよびResponse Validatorへの事実提供
- Plugin停止時のCapability解除

CoreはPlugin固有のルール、入力分類、Session状態、外部API仕様を持たない。

### 2.2 Pluginの責務

Pluginは次を担当する。

- 自身が提供可能な機能の宣言
- 自身の初期化と停止
- 設定および依存先の検証
- 現在利用可能なCapabilityの報告
- Plugin固有の入力解釈
- Plugin固有Commandの検証
- Plugin固有状態の管理
- 外部サービスまたは内部機能の実行
- 実行結果の構造化
- 必要なActivity Request、Prompt Context、Memory Policyの返却
- 依存喪失やHealth悪化の通知

PluginはCoreの内部状態やSchedulerを直接操作しない。

## 3. Pluginライフサイクル

Pluginの標準ライフサイクルを次のように定義する。

```text
discovered
→ registered
→ initializing
→ available
→ degraded
→ unavailable
→ shutting_down
→ stopped
```

### 3.1 discover

Plugin候補を検出する。この時点では実行可能とはみなさない。

### 3.2 register

Plugin ID、メタデータ、宣言Capability、Activity Definitionを登録する。重複Plugin IDは拒否する。

### 3.3 initialize

設定、依存Provider、外部サービス接続、内部状態を初期化する。初期化失敗はPlugin単位で隔離し、Core全体を停止させない。

### 3.4 health check

Pluginおよび依存先の健全性を確認する。一部機能だけ利用可能な場合は、Capability単位で利用可能状態を報告できる。

### 3.5 available

初期化とHealth確認が完了し、実行可能なCapabilityをRegistryへ登録した状態。

### 3.6 degraded / unavailable

一部または全部のCapabilityを利用できない状態。利用不能となったCapabilityは速やかにRegistryから解除する。

### 3.7 shutdown

新規Command受付を停止し、実行中処理の終了またはキャンセルを行い、Capabilityを解除する。

## 4. Plugin識別情報

各Pluginは少なくとも次を持つ。

```text
plugin_id
display_name
version
enabled
declared_capabilities
activity_definitions
configuration_schema
```

### 4.1 plugin_id

システム内で一意の固定識別子。

例:

```text
games
streaming_orchestration
youtube_platform
obs
voice_synthesis
avatar_control
```

表示名や外部サービス名を識別子として流用しない。

## 5. Capability契約

Capabilityは、Coreから見た「現在実行可能な機能」を表す。

### 5.1 宣言と利用可能状態の分離

Pluginが宣言したCapabilityは、提供可能性を示すだけであり、現在利用可能であることを保証しない。

```text
declared_capabilities
    Pluginが実装上提供可能な機能

available_capabilities
    現在実行できる機能
```

Coreは実行許可を判断するとき、`available_capabilities`だけを正本とする。

### 5.2 Capability Registry

Capability Registryは次を保持する。

```text
capability_id
provider_plugin_id
availability
health_status
registered_at
state_version
```

同一Capabilityを複数Pluginが提供できる場合、Core側のProvider選択方針に従う。

### 5.3 Capability解除

次の場合、該当Capabilityを解除する。

- Plugin停止
- 初期化失敗
- 外部サービス切断
- Provider喪失
- Health check失敗
- 実行中に利用不能が判明
- 設定変更による無効化

過去に利用可能だった事実やLLM出力を根拠に実行してはならない。

## 6. Activity Definition契約

Pluginは、自身が提供するActivity候補を`ActivityDefinition`として宣言する。

Activity Definitionは、意味認識用の候補定義であり、実行可能性そのものではない。

最低限、次を持つ。

```text
activity_type
description
semantic_descriptions
supported_operations
required_capability
provider_plugin_id
constraints_schema
ongoing_supported
```

### 6.1 意味認識と実行許可の分離

Activity Definitionは、Pluginが無効またはCapability未登録でも、意味認識候補として利用できる。

その後、Activity Plan確定時とCommand実行直前にCapability Registryで実行可否を検証する。

```text
User Input
→ Situation Evaluator
→ Activity Definition照合
→ Activity Plan
→ Capability検証
→ Plugin実行または拒否
```

### 6.2 required_capabilityの決定

`required_capability`と`provider_plugin_id`は、LLM出力ではなくActivity Definitionから導出する。

LLMにCapability名やProviderを自由生成させない。

## 7. Plugin Context

CoreはPluginへ、必要最小限の`PluginContext`だけを渡す。

含めてよいもの:

```text
plugin_id
plugin_config
clock
logger
llm_gateway
activity_gateway
capability_snapshot
correlation_id
```

必要に応じて、狭い目的のGatewayを追加できる。

渡してはいけないもの:

- Event Queue本体
- Activity Manager本体
- Action Scheduler本体
- AgentStateの可変参照
- 他Pluginの実装インスタンス
- UIオブジェクト
- DB接続オブジェクトの直接参照

Plugin Context経由の状態は原則として読み取り専用または限定操作とする。

## 8. Command契約

CoreからPluginへの実行要求は`PluginCommand`として渡す。

最低限、次を持つ。

```text
command_id
correlation_id
plugin_id
activity_type
operation
constraints
state_version
requested_at
```

必要に応じて次を持てる。

```text
ongoing_activity_id
source_event_id
deadline
confirmation_state
```

### 8.1 Command検証

Pluginは副作用を起こす前に次を検証する。

- Pluginが現在有効か
- 対象operationをサポートしているか
- 必須Capabilityが利用可能か
- constraintsがschemaに適合するか
- state_versionが古くないか
- Plugin固有状態が実行可能か
- 重複実行でないか
- 確認が必要なCommandではないか

不正または古いCommandは実行せず、拒否Resultを返す。

### 8.2 constraints schema

constraintsはPlugin固有だが、検証方式は共通化する。

推奨仕様:

- required / optional
- type
- enum
- minimum / maximum
- minLength / maxLength
- nested object
- additionalProperties
- default

同じValidatorを次の3段階で使用する。

```text
Situation解析後
→ Activity Plan検証時
→ Plugin Handler実行直前
```

## 9. Plugin実行結果

Pluginは実行結果を`PluginExecutionResult`として返す。

最低限、次を持つ。

```text
execution_result_id
command_id
correlation_id
plugin_id
activity_type
operation
status
summary
result_payload
failure_reason
started_at
completed_at
```

status例:

```text
accepted
running
waiting_input
succeeded
rejected
failed
canceled
```

### 9.1 実行事実と出力結果の分離

Plugin処理の結果と、発話・字幕・音声・表情などのAction実行結果は分離する。

```text
PluginExecutionResult
    Plugin機能の実行事実

ActivityResult
    Action Plan Groupの実行結果
```

両Resultは`correlation_id`および必要な関連IDで追跡できなければならない。

Pluginが成功しても、Character LLM、TTS、字幕、Action Schedulerが成功したとは限らない。

### 9.2 成功確定のタイミング

副作用が完了する前に`succeeded`を返してはならない。

処理が継続する場合は`accepted`、`running`、`waiting_input`などを使用する。

### 9.3 Resultの正本性

外部操作やPlugin処理の実行事実は、PluginExecutionResultを正本とする。

Character LLMやBehavior PlannerはResultを書き換えない。

## 10. Activity Request契約

PluginがCore側のAction実行を必要とする場合、`PluginActivityRequest`を返す。

例:

- 発話
- 字幕
- 表情
- モーション
- 次Event生成
- Ongoing Activity開始または更新

最低限、次を持つ。

```text
correlation_id
activity_type
goal
response_facts
action_hints
memory_policy
followup_events
ongoing_transition
```

Pluginは音声再生、字幕表示、表情変更などを直接実行しない。

Coreが既存のAction PlannerとAction Schedulerを通じて実行する。

## 11. Ongoing Activityとの接続

複数入力や複数Turnにまたがる活動は、Coreの`OngoingActivity`へ接続する。

### 11.1 役割分担

```text
OngoingActivity
    Runtime上の継続目的、状態、期待入力、終了条件

Plugin Session
    Plugin固有のルール状態、外部ID、内部進行状態
```

Plugin Sessionの詳細状態をOngoingActivityへ複製しない。

OngoingActivityはPlugin Session IDまたはPlugin State IDを参照する。

### 11.2 開始

Pluginのstart成功時に、必要ならOngoingActivityを作成する。

### 11.3 継続

同じ継続活動への入力では、同一`ongoing_activity_id`とPlugin Session IDを引き継ぐ。

### 11.4 終了

次の場合、OngoingActivityとPlugin Sessionの状態を同期する。

- completed
- canceled
- failed
- timeout
- user stop
- Plugin unavailable

どちらか一方だけが実行中として残らないようにする。

## 12. Prompt Context

Pluginは、Character LLMやSituation Evaluatorに必要な補足情報を`PromptFragment`または構造化Contextとして返せる。

含めてよいもの:

- 現在のPlugin固有状態の要約
- 利用者へ伝えるべき事実
- 禁止すべき表現
- 次に期待する入力
- Plugin固有の語彙説明

含めてはいけないもの:

- 最終発話文の強制
- 実行していない処理の成功宣言
- Core内部構造の説明
- 秘密情報
- 外部APIの認証情報
- 生の内部例外

## 13. Memory Policy

Pluginは、Plugin Activityに関する保存方針を`MemoryPolicy`として返せる。

例:

```text
save_conversation_history
save_short_memory
save_long_memory
save_topic_memory
save_embedding
save_activity_summary
```

CoreはPlugin種別を判定せず、Memory Policyに従う。

Plugin固有の保存禁止ルールをCoreへ直接埋め込まない。

## 14. Follow-up Event

Pluginは、必要な後続処理を`FollowupEvent`としてCoreへ返せる。

例:

- plugin_operation_completed
- plugin_operation_failed
- waiting_for_user_input
- external_state_changed
- capability_lost
- session_completed

PluginはEvent Queueへ直接投入せず、Coreへ返却する。

Coreが検証したうえでEvent化する。

## 15. Healthと障害処理

### 15.1 Health Status

PluginまたはCapabilityの状態を次で表現する。

```text
healthy
degraded
unhealthy
unknown
```

### 15.2 障害時の原則

- Plugin障害でCore全体を停止させない
- 実行できない機能を実行したふりをしない
- Capabilityを解除してから会話フォールバックへ進む
- 失敗ResultをCharacter LLMへ事実として渡す
- 内部例外を利用者向け発話へ直接露出しない
- 再試行には上限を設ける
- 同じ失敗Activityの無制限再提案を禁止する

### 15.3 フォールバック

Capability不足またはPlugin障害時は、通常Conversation Activityへ遷移できる。

その際、Coreは次を保証する。

- 未実行であること
- 成功したと表現しないこと
- 現在可能な代替案だけを必要に応じて提示すること
- PluginやCapabilityなどの内部用語をそのまま発話しないこと

## 16. Response生成との境界

PluginExecutionResultまたはActivityResultから、Character LLM用のResponse Contextを構築する。

Response Contextには少なくとも次を含める。

```text
activity_type
operation
status
summary
failure_reason
capability
provider_plugin_id
constraints
ongoing_state
allowed_claims
forbidden_claims
correlation_id
```

Character LLMは表現を生成するだけであり、実行事実を決定しない。

Response Validatorは、Character LLMの自己申告claimsだけを信頼せず、発話本文とResultの整合性も検証する。

## 17. ログと追跡

共通ログには次を含める。

```text
correlation_id
command_id
execution_result_id
activity_id
ongoing_activity_id
plugin_id
capability_id
operation
status
state_version
```

次の処理を一つのcorrelation chainとして追跡できるようにする。

```text
Event
→ Situation Analysis
→ Behavior Plan
→ Capability検証
→ Plugin Command
→ PluginExecutionResult
→ Character Response
→ Action Plan Group
→ ActivityResult
```

認証情報、秘密情報、不要なPrompt全文はINFOログへ出力しない。

## 18. Pluginがしてはいけないこと

- CoreのEvent Queueへ直接書き込む
- Activity Managerを直接操作する
- Action Schedulerを直接操作する
- AgentStateを直接変更する
- 他Pluginの実装クラスを直接呼ぶ
- Capability Registryを書き換える
- Character LLMを最終実行者として扱う
- 実行前に成功Resultを返す
- schema未検証のCommandを実行する
- Plugin固有状態をCoreへ重複保存する
- CoreへPlugin固有の条件分岐を追加させる
- UI、TTS、字幕、Avatarなどの出力を直接制御する
- 失敗を通常成功へ変換する

## 19. 設定方針

Plugin設定はPlugin単位で分離する。

例:

```yaml
plugins:
  games:
    enabled: true

  youtube_platform:
    enabled: false

  voice_synthesis:
    enabled: true
```

設定には次を含められる。

- enabled
- Provider選択
- 接続情報参照
- timeout
- retry
- Plugin固有設定

認証情報は安全な設定管理手段を使用し、設計書やログへ直接記載しない。

## 20. 互換機能と移行

旧実装との互換処理は、Coreへ恒久的に残さない。

互換処理は専用Adapterへ隔離する。

```text
Legacy Input / Marker
→ Legacy Adapter
→ Common Plugin Contract
```

互換機能には次を明記する。

- Deprecatedであること
- 対象範囲
- 削除条件
- 移行先
- 削除予定

## 21. Plugin追加時の完了条件

新しいPluginは、少なくとも次を満たす。

- 一意なPlugin IDを持つ
- 初期化と停止ができる
- 宣言Capabilityと利用可能Capabilityを分離している
- Activity Definitionを提供する
- Command schemaを持つ
- 実行直前検証を行う
- 構造化Resultを返す
- Ongoing Activityとの境界が定義されている
- Memory Policyが定義されている
- Capability喪失時に解除できる
- Plugin無効時もCoreが動作する
- CoreへPlugin固有分岐を追加しない
- 正常、拒否、失敗、停止、依存喪失のテストがある

## 22. 本書で扱わない内容

本書では次を扱わない。

- 個別Pluginの内部設計
- YouTube APIの具体仕様
- OBS操作仕様
- ゲームルール
- VOICEVOX読み補正
- Plugin固有Sessionの詳細
- 特定ソースファイル配置
- 実装進捗
- 配信台本や進行表

これらは各Plugin設計書または`source_file_plan.md`で管理する。
