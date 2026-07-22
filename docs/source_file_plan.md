# ソースファイル作成方針

## 目的

AIライバーを「チャット応答プログラム」ではなく、常時稼働する配信主体として成立させるため、最初から全体骨格を定義し、その骨格の中で必要な部品を段階的に肉付けしていく。

本プロジェクトでは、最小構成を後から継ぎ足して巨大化させるのではなく、最初に Runtime 全体の境界、Loop、Queue、State、Executor、Adapter の責務を決める。そのうえで、各部品の初期実装は薄く保ち、テスト可能な順に実装を増やす。

AIライバーはチャットボットではなく、話題の主導権を自身に持つ常時稼働型の配信主体として扱う。外部入力は話題の起点ではなく、配信中に発生する刺激 Event の一種として扱う。

現時点では、コンソール入力、Ollama / OpenAI による LLM 応答生成、疑似読み上げ時間、短期発話記憶、Trace ログまで接続済みである。

## 全体方針

- Event は「起きたこと」
- Activity は「継続する目的」
- Action は「今この瞬間に実行する命令」
- 話題の起点は、ユーザー入力ではなく AIライバー自身の内的関心・気分・DriveState・TopicState とする
- 外部入力は、AIライバーの話題選択に影響する刺激 Event として扱い、必ずしも話題の主導権を渡さない
- 自律発話は、無入力・一定間隔・Queue 空状態ではなく、内的状態と話題状態に基づいて発生する
- キューに積む単位は Speech ではなく Activity とする
- 発話は Activity から派生する Action の一種であり、特別扱いしない
- LLM 生成待ちと Activity 実行待ちは分離する
- 思考ループは次に行いたい Activity を生成・計画し、実行ループは Activity を取り出して ActionPlan 化して実行する
- SPEAK の読み上げ時間や発話間隔は Action 実行側の制約として扱い、LLM 思考ループを待機させない
 - RuntimeSupervisor / RuntimeCoordinator は処理本体ではなく、各 Loop の起動・停止・接続を管理する Host として扱う
 - Event 処理、Activity 計画、Activity 実行、外部入力受信は独立した Loop / Service として分ける
### 関連設計書

- `docs/llm_role_architecture.md`: Situation Evaluator、Behavior Planner、Activity Result、Response Context、Character LLM、Response Validatorの詳細設計
- 本ファイルはソース配置・実装方針の正本とし、LLMロール間の詳細契約は上記設計書を正本とする

## 全体骨格の作成方針

本プロジェクトは、以後「最小構成から継ぎ足す」進め方を採用しない。
代わりに、最初から最終的な Runtime 骨格を明示し、その中身を段階的に実装する。

基本方針:

- 先に全体の境界を決める
- Loop と名付ける部品は、自分自身で継続実行する `run()` を持つ
- 一回分の処理だけを行う部品は、Loop ではなく Service / Processor / Usecase として扱う
- RuntimeCoordinator は、Event から Action 実行までを直列に抱え込まない
- Queue を境界にして、計画側と実行側を分離する
- LLM 呼び出しは、Planning 側に閉じ込める
- TTS / 字幕 / OBS / Live2D などの外部 I/O は Execution 側に閉じ込める
- 外部入力は Runtime 本体ではなく Input Loop / Receiver から Event として流入させる
- 初期実装で中身が薄くても、部品の配置と依存方向は最終形に合わせる

最終的な骨格:

```text
RuntimeSupervisor / RuntimeCoordinator
  ├─ ExternalInputLoop / InputReceiver
  │    └─ 外部入力を AgentEvent として EventQueue へ投入する
  ├─ ExternalEventLoop / EventProcessingLoop
  │    └─ EventQueue から Event を取り出し、AgentState / ActivityManager / Queue へ反映する
  ├─ ActivityPlanningLoop
  │    └─ AgentState / DriveState / EmotionState / TopicState から PlannedActivity を生成する
  ├─ ActivityExecutionLoop
  │    └─ PlannedActivityQueue から Activity を取り出して ActionPlanGroup を実行する
  ├─ PlannedActivityQueue
  │    └─ 実行予定 Activity を保持する
  ├─ EventQueue / EventBuffer
  │    └─ 外部 Event / 内部 Event を保持する
  └─ RuntimeState / AgentState
       └─ 現在の活動、感情、内的動機、実行中 Action を保持する
```

初期段階で薄く実装した部分（現在は後続実装済み）:

- TopicStateはTopicHistory / InterruptedTopic / 継続判定として段階実装済み
- ActivityPlanningLoop は最初は DriveState から単純に Activity を作るだけでよい
- ActivityExecutionLoop は最初は ActionPlanner / ActionScheduler を呼ぶだけでよい
- ExternalEventLoop は最初は USER_TEXT / SPEECH_STARTED / SPEECH_FINISHED のみ扱えばよい
- TTS / OBS / Live2D は最初は Console 出力 Adapter で代替してよい

ただし、薄い実装であっても、後から責務境界を大きく変えなくて済む構造にする。
- LLM 応答生成は ResponseGenerator Port 経由で差し替える
- 現時点では DummyResponseGenerator と OllamaResponseGenerator を利用できる
- キャラクター設定、モデル設定、入力アダプタ設定は `config/config.yaml` から読み込む
- 設定不備がある場合は、デフォルト値で補完せず異常終了する
- TTS / OBS / YouTube / Live2D などの外部接続は後続工程で Adapter / Channel Executor として追加する

## 現在の実装範囲

- Event
- Activity
- Action
- EventQueue / EventBuffer
- EventPublisher Port / EventBus
- EventFilter / EventPrioritizer
- ActivityManager
- ActionPlanner
- ActionScheduler
- RuntimeCoordinator
- AgentLifeService
- AgentState
- EmotionState
- DriveState
- InputReceiver Port
- ConsoleInputReceiver / TimerInputReceiver
- CharacterProfile / PromptBuilder
- DummyResponseGenerator / OllamaResponseGenerator / OpenAIResponseGenerator
- TraceLogger
- ShortTermMemory
- Config / 設定ファイル読み込み
- Runtime Composition Root
- ExecuteActionUsecase
- 起動確認用 `app/__main__.py`
- Runtime のスモークテスト

## Plugin所有ソースの配置

- YouTube配信固有のDomain modelは`app/plugins/youtube_streaming/domain`を正本とする
- 配信準備、開始、進行、コメント処理、終了のApplication logicは
  `app/plugins/youtube_streaming/application`を正本とする
- Coreの`app/domain`と共通`app/usecases`には、配信固有実装やPluginへの互換
  re-exportを置かない
- CoreとのActivity/Event接続はComposition RootでShared DTOへ相互変換する
- Streaming DemoのResponse GeneratorはCore pipeline用Adapterに置き、Plugin側の
  手動確認ログはSharedの固定fixtureだけを参照する

## 管理者の自然文指示と配信運用境界

- `python -m app`はゆらCoreとローカルConsoleだけを起動し、OBS、YouTube、配信進行APIを
  compositionしない
- Console入力は入力Adapterが`administrator`を付与し、YouTubeコメントは`viewer`を付与する
- 権限は本文から推測せず、本文中の自己申告では昇格させない
- administratorの「オープニングトークして」「本題に入って」等はコマンド文字列ではなく、
  Situation Evaluatorが自然文の進行指示として解釈する
- 汎用トーク指示は`DIRECTED_TALK`としてCharacter pipelineで実行し、ゲームなど登録済み
  Activityへの指示は既存のActivity Definition/Capability経路で実行する
- viewerコメントは会話上の刺激として扱い、危険な指示、外部操作、権限変更要求には従わない
- 将来ログインを導入する場合は、認証済みUser ID/Roleを`InputAuthority`へ写像する
- 起動発話は準備・眠気・自己紹介を固定せず、起動ごとの導入フォーカス、現在の感情、記憶、
  直近発話から自然な一言を作る

## トレースログ方針

- `runtime_trace.log` は設定したレベル以上の実行概要を記録し、標準設定のINFOでは起動・終了、Plugin/Capabilityの変化、Behavior Plannerの最終判断、Activityの開始・継続・完了・拒否、実行結果、重要なフォールバック、警告・エラーだけを扱う
- `runtime_debug.log` は `trace.debug_file_enabled` が有効な場合に詳細レコードを記録する。待機、ポーリング、`skipped`、途中状態、Capability照合、Action構築、LLM入出力、正規化後のユーザー入力はDEBUGへ出す
- ログ表示時刻は内部データのUTC方針と切り離し、実行環境のローカルタイムをUTCオフセット付きISO 8601で記録する
- LLMへ実際に渡す構造と生応答・解析結果・採用文は、`log_llm_prompts` / `log_llm_responses` で個別に有効化する。固定長で切断せず、一行のJSONエスケープ可能なフィールドとして保持する
- APIキー、Authorization、Password、Token、DSNなどはLogger共通の再帰マスク処理を通し、個別Adapterで独自のマスク処理を重複実装しない
- 正規化済みユーザー入力は `log_user_input` が有効な場合だけDEBUGへ記録し、INFOへ本文を出さない
- INFO概要とDEBUG詳細には同じローテーション設定を適用する
- 調査用の`logs/conversation.jsonl`には、LLMからTTSへ渡した原稿、Coreが受理したconsole入力、YouTube comment入力を、生テキストのまま時系列で記録する
- 会話ログは`timestamp`、`speaker`（`llm` / `console` / `comment`等）、`speaker_name`、`source`、`text`、追跡IDを持ち、Runtimeの詳細ログ設定とは独立して出力する

## 現在の主要フロー

現時点の旧フローは、Event 処理、Activity 生成、LLM 生成、Action 実行が RuntimeCoordinator 上で直列に近い形で接続されている。今後はこの旧フローを維持したまま拡張するのではなく、下記の全体骨格へ移行する。

```text
InputReceiver
  ↓
AgentEvent
  ↓
RuntimeCoordinator.publish_event() / publish_events()
  ↓
EventFilter
  ↓
EventPrioritizer
  ↓
EventBuffer
  ↓
EventQueue
  ↓
RuntimeCoordinator.run() / run_once()
  ↓
ActivityManager
  ↓
ActionPlanner
  ↓
ResponseGenerator
  ↓
PromptBuilder + CharacterProfile
  ↓
ActionPlanGroup
  ↓
ActionScheduler
  ↓
ExecuteActionUsecase
  ↓
EventPublisher Port
  ↓
EventBus
  ↓
EventQueue
  ↓
SPEECH_STARTED / SPEECH_FINISHED Event
```

今後は、LLM による Activity 計画と、Activity の実行待機を分離する。

移行後の基本フロー:

```text
ActivityPlanningLoop / AgentThinkingLoop
  ↓
内的状態・外部刺激・TopicState を評価
  ↓
次に行いたい Activity を生成
  ↓
PlannedActivityQueue に追加
  ↓
生成済み Activity を計画記憶へ反映
  ↓
次の Activity を考える

ActivityExecutionLoop / AgentActingLoop
  ↓
PlannedActivityQueue から Activity を取得
  ↓
ActionPlanner で ActionPlanGroup に変換
  ↓
ActionScheduler で Action を実行
  ↓
Activity 完了後の AgentState / TopicState / Memory を更新
  ↓
テンション・疲労・Activity 種別に応じて次の実行間隔を制御
```

この構成では、発話は `AUTONOMOUS_TALK` Activity から派生する `SPEAK` Action にすぎない。
`IDLE_OBSERVATION`、`THINKING`、`LOOK_AROUND`、`CHECK_COMMENTS`、`STREAM_MAINTENANCE` なども同じ Activity として扱う。
## PlannedActivityQueue / ActivityPlanningLoop / ActivityExecutionLoop 方針

AIライバーの常時稼働では、LLM による思考・計画と、Activity の実行・待機を分離する。
ただし、キューに積む単位は Speech ではなく Activity とする。

目的:

- LLM 生成待ち時間を発話待機や Activity 実行間隔に含めない
- 発話だけでなく、観察・思考・表情変化・コメント確認・配信操作なども同列の Activity として扱う
- AIライバーが「セリフを生成する存在」ではなく「次に行う Activity を考え、実行し続ける存在」になるようにする
- MOUTH が発話中でも、HEAVY_BRAIN / LIGHT_BRAIN / EYES / FACE など別リソースの準備を進められるようにする
- 外部入力が来た場合に、生成済み Activity、実行待ち Activity、実行中 Activity を調停できるようにする

基本方針:

- `SpeechQueue` は作らず、`PlannedActivityQueue` を作る
- `PlannedActivityQueue` は、次に実行予定の Activity を保持する
- `ActivityPlanningLoop` は、AgentState / DriveState / EmotionState / TopicState / 外部刺激から次に行いたい Activity を生成する
- `ActivityExecutionLoop` は、PlannedActivityQueue から Activity を取り出し、ActionPlanner で ActionPlanGroup に変換して実行する
- Action 実行後、Activity 完了イベント・成功失敗・実行結果を AgentState / TopicState / Memory に反映する
- SPEAK の読み上げ時間、発話後の間、テンションによる待機時間は ActivityExecutionLoop 側の制御とする
- ActivityPlanningLoop は SPEAK の読み上げ時間や発話後の待機を直接待たない
- ActivityPlanningLoop はキューが不足している場合、先に Activity を生成して積める
- ただし、外部刺激や状態変化で不適切になった Activity は実行前にキャンセル・再計画できるようにする

追加予定ファイル:

- `app/runtime/planned_activity_queue.py`
- `app/runtime/activity_planning_loop.py`
- `app/runtime/activity_execution_loop.py`

予定モデル:

- `PlannedActivity`
- `PlannedActivityQueue`
- `ActivityPlanningLoop`
- `ActivityExecutionLoop`

`PlannedActivity` の候補属性:

- `activity`
- `created_at`
- `source`
- `planning_reason`
- `priority`
- `expires_at`
- `planned_drive`
- `planned_emotion`
- `planned_topic`

ActivityPlanningLoop の予定責務:

- AgentState を読む
- TopicState / DriveState / EmotionState を読む
- 外部刺激 Event を参考にする
- 次に行う Activity を選ぶ
- 必要に応じて LLM で Activity の内容や発話本文を生成する
- PlannedActivityQueue に Activity を積む
- 生成済み Activity を計画記憶に反映する

ActivityExecutionLoop の予定責務:

- PlannedActivityQueue から Activity を取り出す
- 実行直前に Activity がまだ有効か確認する
- ActionPlanner で ActionPlanGroup を生成する
- ActionScheduler で ActionPlanGroup を実行する
- Activity 完了後に AgentState / TopicState / Memory を更新する
- Activity 種別、テンション、疲労、使用リソースに応じて次の実行間隔を調整する

Activity と Action の関係:

- Activity は継続する目的である
- Action は Activity を実現するための瞬間的な命令である
- `AUTONOMOUS_TALK` Activity は `SPEAK` / `UPDATE_SUBTITLE` / `CHANGE_EXPRESSION` などの Action に変換される
- `IDLE_OBSERVATION` Activity は `OBSERVE` / `LOOK_AROUND` / `CHANGE_EXPRESSION` などの Action に変換される
- `THINKING` Activity は `LIGHT_BRAIN` / `HEAVY_BRAIN` を使う内部 Action として扱える
- `STREAM_MAINTENANCE` Activity は OBS 操作や状態確認 Action に変換される

`PlannedActivityQueue`、`ActivityPlannerThread`、`ActivityExecutorThread`として実装済み。
計画と実行を別Queueへ分離し、実行直前のActivity有効性を再検証する。
## EventPublisher / EventBus

EventPublisher は、Action 実行中に発生した内部 Event を Runtime へ戻すための Port である。
EventBus は EventPublisher を実装し、受け取った AgentEvent を EventQueue へ投入する。

目的:

- ExecuteActionUsecase が RuntimeCoordinator に直接依存しないようにする
- SPEAK Action から発生する `SPEECH_STARTED` / `SPEECH_FINISHED` を Runtime の EventQueue に戻す
- 外部入力 Event と内部 Action Event の流入先を EventQueue に統一する
- RuntimeCoordinator への戻り依存を避け、依存方向を一方向に保つ

実装済みファイル:

- `app/ports/event_publisher.py`
- `app/runtime/event_bus.py`
- `tests/test_event_bus.py`

現時点の実装仕様:

- `EventPublisher` は `publish(event: AgentEvent)` を持つ Protocol である
- `EventBus` は `EventPublisher` を実装する
- `EventBus` は `EventQueue` を受け取る
- `EventBus.publish(event)` は `EventQueue.put(event)` を呼ぶ
- `ExecuteActionUsecase` は Callable ではなく `EventPublisher` Port に依存する
- `RuntimeCoordinator.publish_internal_event()` は不要になったため削除済みである

テストで確認済みの内容:

- `EventBus.publish(event)` で EventQueue に Event を投入できる
- EventQueue から同じ Event を取り出せる

## Event / EventFilter / EventPrioritizer

RuntimeCoordinator は EventQueue へ直接 Event を投入せず、次の順で処理する。

1. EventFilter でイベントを正規化・破棄判定する
2. EventPrioritizer で優先度を補正する
3. EventBuffer で replace_key 単位の最新化を行う
4. EventQueue へ投入する

実装済みファイル:

- `app/runtime/event_filter.py`
- `app/runtime/event_prioritizer.py`
- `app/runtime/event_buffer.py`
- `tests/test_event_filter.py`
- `tests/test_event_prioritizer.py`
- `tests/test_event_buffer.py`
- `tests/test_runtime_coordinator.py`

現時点のルール:

- user_text は高優先度で保持する
- youtube_comment は中〜高優先度で保持する
- camera_frame は discardable とし、replace_key に `camera_frame` を設定する
- silence_timeout は discardable とし、replace_key に `silence_timeout` を設定する
- speech_started / speech_finished は内部連鎖イベントとして優先度を補正する
- replace_key がないイベントは投入順に全件保持する
- replace_key があるイベントは同じ replace_key の最新イベントだけ保持する
- user_text / youtube_comment は全件保持する
- camera_frame / silence_timeout は複数投入時に最新だけ保持する

テストで確認済みの内容:

- user_text は複数件すべて処理される
- camera_frame は複数件投入しても最新だけ処理される
- user_text と camera_frame が混在しても、user_text と最新 camera_frame が処理される

## ActivityManager

ActivityManager は、Event から Activity を生成し、現在の foreground Activity と新しい Activity を比較して、活動の前面化・保留・一時停止を判断する。

基本方針:

- Activity は foreground / pending / suspended / completed / canceled として管理する
- 新しい Activity が来たら、現在の foreground Activity と優先度を比較する
- 新しい Activity の優先度が高く、現在の foreground Activity が `interruptible=True` の場合、新しい Activity を foreground にする
- その場合、元の foreground Activity は suspended にする
- 現在の foreground Activity が `interruptible=False` の場合、新しい Activity は pending にする
- 新しい Activity の優先度が foreground Activity 以下の場合も pending にする
- Action 実行が完了した Activity は completed にできる
- foreground Activity 完了後、pending Activity が存在する場合は優先度が最も高いものを active に戻す
- foreground Activity完了後はpendingとsuspendedを同じ候補集合として評価し、優先度最大のActivityを再開する
- 同一優先度では、未開始pendingより中断済みsuspendedを優先して活動目的の連続性を保つ
- 古いAUTONOMOUS_TALK本文はそのまま再開せず、既存のTopic継続評価へ委ねて再計画する
- 明示再開はforegroundがなく対象がpendingまたはsuspendedの場合だけ許可する
- 再開ログにはactivity_id、previous_status、reason、候補数を含める

実装済みファイル:

- `app/runtime/activity_manager.py`
- `tests/test_activity_manager.py`
- `tests/test_runtime_coordinator.py`

初期実装で扱う代表ケース:

- idle_observation 中に user_text が来た場合、conversation_with_user を active にする
- autonomous_talk 中に user_text が来た場合、autonomous_talk を suspended にし、conversation_with_user を active にする
- conversation_with_user 中に silence_timeout が来た場合、conversation_with_user を維持し、autonomous_talk を pending にする
- conversation_with_user が完了したら completed になる
- foreground Activity 完了後、pending の autonomous_talk が active になる
- pending がない場合、foreground Activity は `None` になる

現時点では ActivityTransitionService は作成せず、ActivityManager 内に最小実装する。
ロジックが複雑化した段階で、ActivityTransitionService へ分離する。

## Action / ActionResource / ActionScheduler

AIライバーは常時稼働するため、入力受信・判断・出力実行を分けて扱う。

基本方針:

- Input Receiver は並行して動作する
- Event は発生タイミングで受け入れ、EventQueue / EventBuffer へ投入する
- RuntimeCoordinator は Event を Activity / Action へ変換する判断部分を担当する
- 実際の出力・操作は ActionScheduler が物理I/Oリソースごとに制御する
- 同時実行できるかどうかは、Activity そのものではなく Action が使用するリソースで判定する

実装済みの概念:

- ActionResource
- ActionPlanGroup
- ActionScheduler

ActionResource は、Action が使用する物理I/Oまたは処理能力を表す。

初期候補:

- `MOUTH`: 発話・TTS
- `FACE`: 表情
- `BODY`: Live2Dモーション
- `HANDS`: ゲーム操作・入力操作
- `EYES`: 画面認識・視覚入力
- `HEAVY_BRAIN`: 重いLLM推論
- `LIGHT_BRAIN`: 軽い相槌・短い反応
- `SUBTITLE`: 字幕表示
- `OBS`: 配信操作

実装済みファイル:

- `app/domain/actions/action_resource.py`
- `app/domain/actions/action_plan_group.py`
- `app/runtime/action_scheduler.py`
- `tests/test_action_scheduler.py`

修正済みファイル:

- `app/domain/actions/action_plan.py`
- `app/domain/actions/__init__.py`
- `app/runtime/action_planner.py`
- `app/runtime/runtime_coordinator.py`
- `app/runtime/__init__.py`
- `tests/test_runtime_coordinator.py`
- `tests/test_runtime_smoke.py`
- `app/usecases/execute_action_usecase.py`
- `tests/test_execute_action_usecase.py`
- `app/ports/event_publisher.py`
- `app/runtime/event_bus.py`
- `tests/test_event_bus.py`

現時点の実装仕様:

- `ActionPlan` は `required_resources` を持つ
- `ActionPlanner.plan()` は `ActionPlanGroup` を返す
- `conversation_with_user` は `SPEAK` / `UPDATE_SUBTITLE` / `CHANGE_EXPRESSION` を返す
- `autonomous_talk` は `SPEAK` / `UPDATE_SUBTITLE` を返す
- `idle_observation` 系は `OBSERVE` を返す
- `RuntimeCoordinator.run_once()` は `ActionPlanGroup | None` を返す
- `RuntimeCoordinator` は `ActionScheduler` 経由で ActionPlanGroup を実行する
- `ExecuteActionUsecase` は単一 `ActionPlan` の実行責務として残す
- `ExecuteActionUsecase` は任意の `EventPublisher` Port を受け取れる
- `SPEAK` Action 実行時は、実行前に `SPEECH_STARTED` Event を発行する
- `SPEAK` Action 実行後は、`SPEECH_FINISHED` Event を発行する
- `SPEECH_STARTED` / `SPEECH_FINISHED` Event の payload には action_id / source_activity_id / text を含める
- `SPEAK` 以外の Action では speech Event を発行しない
- `SPEAK` Action から発行された speech Event は EventBus 経由で EventQueue に投入される

### VOICEVOX発話読み補正

目的:

- LLMが生成した表示用テキストを保持したまま、VOICEVOXへ渡す読みだけを補正する
- 漢字や固有名詞の誤読を、文脈を含むフレーズ単位の辞書で抑制する
- 将来のアクセント句・モーラ補正を、テキスト補正とVOICEVOX通信から分離する

発話処理フロー:

```text
Character LLM (speech + engine非依存VoiceIntent)
  -> SPEAK Action metadata
  -> SpeechSynthesizer Port
  -> VoiceVox AdapterのVoiceIntent profile解決
  -> PronunciationCorrector
  -> VoiceVoxSpeechSynthesizer.audio_query
  -> AudioQueryCorrector
  -> VoiceVoxSpeechSynthesizer.synthesis
  -> AudioPlayer
```

責務:

- `PronunciationDictionary` は外部YAMLからルールを読み込み、安全なルールを検索可能な順序で保持する
- `PronunciationCorrector` はフレーズ単位の補正を適用し、元文・補正文・適用履歴を返す
- `AudioQueryCorrector` はAudioQuery取得後の補正拡張点とし、初期実装は無変更で返す
- Character LLMはEmotionStateと文脈を統合解釈し、エンジン非依存の`VoiceIntent.style`を返す
- 表現意図が途中で変わる場合だけCharacter LLMは2〜8件の`ReactionSegment`を返し、Coreはsegment_index順に字幕・表情・身振り・音声を実行する
- ReactionSegmentはspeech / expression / gesture / VoiceIntent / 0〜3秒のpauseだけを持ち、エンジン固有値や単語単位の過剰分割を含めない
- `ExecuteActionUsecase` はEmotionStateを音声パラメータへ変換せず、SPEAK ActionのVoiceIntentをPortへ渡す
- `VoiceVoxSpeechSynthesizer` はVoiceIntentを設定済みprofileへ解決し、VOICEVOX API通信と補正コンポーネントを調停する
- 未知または欠落したVoiceIntentはAdapterでdefault profileへフォールバックする
- `app/plugins/voice_output/`はSpeechSynthesizerとAudioPlayerを`output.speech` Capabilityとして公開する
- Voice Output Pluginは具体VOICEVOX型へ依存せずPortを委譲し、Composition RootだけがAdapterを組み立てる
- 合成・再生障害時はCapability Reporterを通じて`output.speech`を解除する
- Capability喪失後もExecuteActionUsecaseはテキスト表示、時間推定、失敗Result返却を継続しRuntime全体を停止しない

辞書仕様:

```yaml
rules:
  - surface: "どんな風に"
    reading: "どんなふうに"
    priority: 100
    enabled: true
    match_type: literal
    description: "風を様態の意味で使用する表現"
```

- 適用順は `enabled=true`、priority降順、surface文字数降順、定義順とする
- 初期実装の `match_type` は `literal` のみとし、正規表現は扱わない
- 同一surface・同一readingの重複と、同一surface・異なるreadingの競合を警告して除外する
- 辞書欠落、空ファイル、一部不正ルールでは安全なルールだけを使用し、発話処理を継続する
- 補正処理が失敗した場合は元の発話テキストでVOICEVOX処理を継続する
- AudioQuery補正が失敗した場合は取得直後のAudioQueryで音声合成を継続する

表示・記憶用テキストとTTS入力用テキスト:

- 字幕、標準出力、短期記憶、話題履歴、長期記憶にはLLM生成の元表記を保存する
- 読み補正済みテキストはVOICEVOXの `/audio_query` 入力にだけ使用する
- 通常ログには全文ではなく省略した元文・補正文と適用ルール数を記録する

ActionScheduler の確定仕様:

- 空の ActionPlanGroup は何も実行しない
- required_resources が空の ActionPlan はそのまま実行する
- 異なる required_resources を持つ ActionPlan は並列実行できる
- 同じ required_resources を持つ ActionPlan は同時実行しない
- 複数リソースを持つ ActionPlan は、リソース名順で Lock を取得してデッドロックを防ぐ
- `SPEAK` を含む ActionPlanGroup は、字幕・表情・音声を同一の出力単位として直列実行する
- 同一出力単位では字幕・表情を音声より先に反映し、音声完了までグループの全リソースを保持する
- 次の出力単位は、現在の音声が完了するまで字幕・表情を含めて開始しない
- 同一出力単位の ActionPlan と ActionPlanGroup は共通の `output_unit_id` を持つ
- 出力単位の完了はINFO、待機・選択・開始と各Actionの途中状態はDEBUGで、`output_unit_id` / `action_id` 付きで追跡できる

音声出力の優先順位:

- 発話を含む出力単位は、スレッドセーフな優先待ちゲートを通して1件ずつ開始する
- 優先順位はユーザー応答（100）、通常の反応・挨拶（50）、自律発話（10）の順とする
- 同じ優先順位ではゲートへ到着した順序を維持し、複数のユーザー応答を逆転させない
- 待機中の自律発話より、後から到着したユーザー応答を先に開始する
- すでに再生を開始した音声は強制停止せず、その1件の完了後に最優先の待機出力を開始する
- DEBUGの待機開始・選択・実行開始ログには `output_unit_id`、`output_priority`、`queue_sequence` を含める

### USER_TEXT受理時の自律Activity割り込み

- USER_TEXTはEventQueueから取り出す時点ではなく、RuntimeCoordinatorが受理した時点で割り込み判定する
- foregroundが割り込み可能なAUTONOMOUS_TALKの場合、直ちにSUSPENDEDへ変更する
- 同じUSER_TEXTに対応するCONVERSATION_WITH_USER Activityを予約し、foregroundへ前面化する
- EventQueueには元のUSER_TEXT Eventを残し、入力自体は破棄しない
- Event処理時は予約済みActivityを再利用し、重複した会話Activityを作らない
- ActivityExecutorThreadはAction実行直前に対象ActivityがACTIVEか再確認する
- USER_TEXT受理によってSUSPENDEDになった自律ActivityのActionは、新規実行を開始しない
- 退避時は対象activity_id、source_event_id、理由をINFOログへ記録する
- すでに音声再生中のActionと、実行キューに生成済みのActionのキャンセルはTASK-002で扱う

### USER_TEXT受理時の古い自律発話キャンセル

- USER_TEXT受理時に、PlannedActivityQueue内の未実行AUTONOMOUS_TALKを取り除く
- 取り除いたActivityはCANCELEDへ変更し、planned_activity_id、activity_id、source_event_id、理由をログへ記録する
- ActionPlannerが処理中の場合は、生成完了後かつActionScheduler実行前にActivity状態を再確認する
- 生成中にActivityがSUSPENDEDまたはCANCELEDになった場合、ActionGroupを実行しない
- 生成済みActionを破棄するログにはaction_id、action_type、source_activity_idを含める
- USER_TEXT Eventは通常どおりEventQueueへ保持し、キャンセル処理の対象にしない
- すでに音声再生を開始したSPEAK Actionは初回実装では強制停止せず、現在の再生完了を待つ
- 再生中Actionの強制停止はAudioPlayerの中断契約と音声リソース解放を別途設計してから導入する
- 現在再生中の音声が完了した後は、キャンセル済み自律発話を再生せずユーザー応答を次に処理する
- SPEAK ActionのTTS合成はFIFO出力前の準備段階で行い、前Turnの再生中に次Turnの音声を準備する
- 字幕、表情、音声再生、発話イベント、記憶保存はFIFO先頭が実行可能になってから行う
- 同一Activityでは未完了Turnを「現在分と次の1件」までとし、古い会話状態による過剰な先読みを行わない
- 同一Activity内の次Turnへ絶対予定時刻を付けず、前Turnの音声再生完了と内容・感情から決めた`pause_after_seconds`の後にFIFOで開始する
- Activity間の自律発話間隔と、Activity内の短いTurn間隔は別の状態として扱う

### 複数ターン活動の状態保持

- `Activity`は継続する目的を表し、同じ目的が続く間は同じ`activity_id`を維持する
- 1回の入力または発話は`ActivityTurn`として区切り、Turnごとに`ActionPlanGroup`を生成・完了する
- `AUTONOMOUS_TALK`は同一話題・同一目的なら`CONTINUE`でTurnを追加し、話題転換時に旧Activityを完了して新しいActivityを`START`する
- TurnのLLM生成、TTS合成、FIFO出力、キャンセル、記憶保存は`activity_turn_id`または`output_unit_id`を実行単位にする
- `OngoingActivity`は活動種別、状態、開始時の目的、直前のActivityResult、次に期待する入力、終了条件、活動固有contextを持つ
- 複数ターン活動中のUSER_TEXTから作る会話Activityには、同じ`ongoing_activity_id`と状態スナップショットを引き継ぐ
- 継続中入力のgoalとcontextには通常会話との識別情報を持たせ、Promptへ活動状態を明示する
- Action実行完了時に、発話・観察・外部操作を区別できる汎用ActivityResultで継続中活動を更新する
- ActivityResultは結果種別、概要、成功状態、Actionごとの詳細データを持ち、SPEAKへ依存しない
- 活動終了時は状態をCOMPLETEDにして現在状態から外し、次のUSER_TEXTを通常会話として扱う
- 開始、更新、終了は`ongoing_activity_id`、活動種別、終了理由を含むINFOログへ記録する
- しりとり固有の開始判定、単語更新、勝敗・終了判定はGames Plugin内に閉じ、Coreは共通Plugin契約だけを扱う

### 中断後の話題継続・再開・転換判断

- USER_TEXT受理から30秒間は通常会話が継続中とみなし、新しい自律発話を計画しない
- 追加のUSER_TEXTを受理した場合は、最後の入力時刻を基準に無入力時間を再計算する
- OngoingActivityがACTIVEの間は無入力時間にかかわらず自律発話を抑制する
- OngoingActivityの終了、明示的な会話終了、または無入力タイムアウト後に自律計画を許可する
- 会話前にPENDINGまたはSUSPENDEDだった自律Activityと未実行Actionは物理的な実行対象から外す
- Activityをキャンセルしても意味的な話題はInterruptedTopicとして保持し、機械的に破棄・再開しない
- すでに再生中の音声はTASK-002の方針どおり強制停止しない
- 自律計画の抑制ログはDEBUGとし、理由とタイムアウト値またはongoing_activity_idを含める
- InterruptedTopicはactive、interrupted、suspended、completed、abandoned、expiredを表現できる
- 判断には重要度、関心度、未完了度、消耗度、中断時間、会話ターン、会話中の話題候補、EmotionState、DriveStateを使用する
- 判断結果はresume_original、resume_with_reframing、branch_from_original、branch_from_interruption、start_new_topic、suspend_original、abandon_original、waitを表現する
- wait、suspend_original、abandon_originalではその評価時点に自律Eventを生成しない
- 再開・派生・新規開始ではCURIOSITY_PEAK Eventへ判断、理由、元話題、選択話題、再導入要否を格納する
- 元話題へ戻る場合は原則として短い再導入を付け、同じ内容を繰り返さないようPromptへ指示する
- 同一ActivityのTurnごとに、関心度と未完了度を減衰させ、表層類似度・EmotionState・DriveStateから消耗度を累積する
- 関心度、未完了度、talkativeness、arousal、curiosityに対して消耗度が上回った場合はActivity終了を予約し、準備済みTurnの完了後に次のActivityへ移る
- 本格的な意味類似度、候補生成、重要度・関心度推定は将来のTopic Engineへ移管する

テストで確認済みの内容:

- 空の ActionPlanGroup は何もしない
- 異なるリソースの Action は実行される
- required_resources なしの Action も実行される
- `MOUTH` を共有する複数 Action は同時実行されない
- 同一出力単位の字幕・表情・音声が対応し、次の字幕は現在の音声完了前に表示されない
- 同一出力単位の各Actionは共通の`output_unit_id`を持つ
- 待機中の自律発話よりユーザー応答が先に再生される
- 複数のユーザー応答は到着順のまま再生される
- 複数ターン活動の状態が次のUSER_TEXTへ引き継がれる
- 活動中入力と通常会話をcontextおよびPromptで区別できる
- 活動終了後の入力は通常会話へ戻る
- ユーザー応答直後は自律発話を計画せず、追加入力で抑制時間を延長する
- 複数ターン活動の継続中は自律発話を計画しない
- 会話終了条件成立後の自律Eventに再開理由が含まれる
- 中断話題の価値と状態に応じて、再開・派生・転換・保留・放棄・待機を選択できる
- 怒りや落胆時に明るい元話題へ機械的に戻らず、感情回復後に保留話題を再評価できる

### Emotion制御と将来のTopic Engine

- `EmotionAppraiser`はEventの確定事実を原因付きdeltaへ変換し、ユーザー文面だけから感情を決めつけない
- `EmotionStateUpdater`はdelta適用時の値域保証と、時間経過によるbaselineへの減衰・回復を担当する
- `AgentLifeService`はEventごとの評価適用と時間減衰を行い、理由と更新前後の値を構造化ログへ記録する
- Character LLMは現在値と変化原因を表現へ統合するが、EmotionState自体は変更しない
- Topic Engineを追加し、現在話題、候補、意味的距離、新規性、重要度、関心度、未完了論点、消耗度を一元管理する
- EmbeddingやLLM評価はPort越しに任意利用とし、利用不能時は決定論的なフォールバックを使う
- TopicHistoryは発話履歴、InterruptedTopicは中断判断用状態、Topic Engineは候補選定責務として区別する

## Games Plugin / 複数ターンゲーム方針

- GameEngine、GameSession、ゲーム入力解釈、しりとり状態・ルール・進行Serviceは`app/plugins/games/`が所有する
- Core Runtimeはゲーム固有型や「しりとり」分岐を持たず、PluginCommand、PluginActivityRequest、PluginActivityStateだけを扱う
- GameEngineは対応ゲームの登録・一覧・対応判定と、単一GameSessionのライフサイクルだけを管理する
- GameEngineは音声、字幕、表情、Action、CoreのOngoingActivityを直接扱わない
- GameDefinitionはgame_type、display_name、description、supported、create_initial_stateを提供する最小抽象とする
- 未登録またはsupported=falseのゲームは開始を拒否し、同じgame_typeの二重登録も拒否する
- activeなGameSessionはRuntime内で最大1つとし、PLAYINGまたはPAUSEDをactiveとして扱う
- GameSessionはsession_id、game_type、status、started_at、updated_at、ended_at、current_turn、metadata、result、end_reasonを保持する
- GameSessionStatusはSTARTING、PLAYING、PAUSED、COMPLETED、CANCELEDとする
- 状態遷移はSTARTING→PLAYING、PLAYING→PAUSED、PAUSED→PLAYING、PLAYING→COMPLETED、PLAYING/PAUSED→CANCELEDだけを許可する
- COMPLETEDまたはCANCELEDからPLAYINGへ戻すことを禁止する
- ActivityはRuntime上の実行状態、GameSessionはゲーム終了まで継続するゲーム状態として分離する
- Coreへ渡すActivityは共通`PLUGIN_ACTIVITY`とし、`plugin_session_id`でPlugin Sessionを参照して既存のAction・字幕・音声・表情経路を利用する
- Activityの完了・中断・再生成だけではGameSessionを終了しない
- GameEngineはGames Plugin初期化時に一度だけ生成し、Plugin内部の各ゲームコンポーネントが同一インスタンスを参照する
- Sessionの開始・一時停止・再開・完了・キャンセルはprevious_status、new_status、reasonを含む構造化ログへ記録する
- しりとりはShiritoriGameDefinitionとしてFactoryで登録し、GameEngineの共通Session基盤を利用する
- 自然言語からのゲーム開始判定と、ゲーム入力・通常会話の分類はGames PluginのIntent Interpreterが扱う

### しりとり詳細設計

- ShiritoriStateはcurrent_turn、last_word、expected_head、used_words、turn_count、winner、loser、end_reasonを保持する
- 手番はUSERとAIを区別し、開始時に指定可能、既定はAI先攻とする
- ユーザー単語はGames PluginのCommand HandlerからServiceへ渡す
- AI単語はPlugin内部の一時ActivityとPlugin専用Promptを使い、注入されたLLM Gatewayで生成する
- GameEngineやShiritoriGameDefinitionからLLM、Action、音声、字幕、表情を直接呼ばない
- AI生成時は既存の人格・品質Promptに、ルール、期待文字、使用済み単語、感情スナップショットを追加する
- LLM出力はgame_action、word、utteranceを持つJSONとし、状態更新にはwordだけ、SPEAKにはutteranceだけを使う
- JSON解析失敗、空単語、手番違反、開始文字違反、重複、`ん`終端は採用せず、最大3回まで再生成する
- 上限後は期待文字に合う安全な内蔵候補を使用し、候補がなければAI降参としてSessionを完了する
- ユーザーの`ん`終端はAI勝利、AI降参はユーザー勝利とし、winner、loser、end_reasonをSession結果へ保存する
- ユーザーまたはAIの正常手ごとにlast_word、expected_head、used_words、current_turn、turn_count、updated_atを更新する

単語正規化:

- Unicode NFKC正規化後、前後・全角を含む空白、句読点、括弧、引用符を除去する
- カタカナはひらがなへ変換し、ユーザーとAIで同じ正規化・検証関数を使う
- headは先頭の基本かなを使い、`キャベツ`は`き`として扱う
- tailの小書き文字は大書きへ寄せ、`きゅ`は`ゆ`として扱う
- 末尾の長音符は読み飛ばして直前かなを使用し、`ミネラルウォーター`は`た`として扱う
- 今回は辞書APIによる実在語判定、形態素解析、複合語・固有名詞の網羅的例外処理を行わない

検証結果:

- valid、invalid_head、already_used、ends_with_n、not_user_turn、not_ai_turn、game_finished、invalid_wordを区別する
- 終了済みSessionへの追加入力はgame_finishedとして拒否する
- 自然言語の終了判定は行わず、cancelまたはsurrenderの明示メソッドを使う

ログと記憶:

- session初期化、ユーザー検証、AI生成要求・拒否・採用、ターン更新、完了、フォールバックを構造化ログへ記録する
- Prompt全文やユーザー長文は通常のINFOログへ出さず、設定で許可したDEBUGログだけへ記録する
- PluginActivityRequestのMemoryPolicyでtopic memory等を抑止し、各単語と発話を通常会話の記憶へ混入させない

### コンソール入力のデコード障害

- コンソールの1入力でUnicodeDecodeErrorが発生してもRuntime全体を異常終了させない
- デコード不能な入力行だけを破棄し、警告ログと再入力メッセージを出して入力ループを継続する
- 復旧後の`exit`または`quit`は通常どおり終了要求として扱う
- RuntimeCoordinator は ActionPlanGroup を返す
- RuntimeCoordinator 経由でも `SPEAK` / `OBSERVE` を取り出して確認できる
- `SPEAK` Action 実行時に `SPEECH_STARTED` / `SPEECH_FINISHED` Event が発行される
- speech Event の payload に action_id / source_activity_id / text が含まれる
- event_publisher 未指定でも `SPEAK` Action はエラーにならない
- `SPEAK` 以外の Action では speech Event が発行されない

現時点での到達点:

- 発話しながら字幕を出す土台ができた
- 発話しながら表情を変える土台ができた
- ただし、複数の発話は同時実行しない
- foreground Activityは設計上1件に限定し、割込み時はpending / suspendedへ移して優先度付きで再開する

## RuntimeCoordinator

RuntimeCoordinator は、最終的には RuntimeSupervisor に近い Host として扱う。Event から Activity 生成、ActionPlan 生成、Action 実行までを直接抱えるのではなく、各 Loop の起動・停止・接続・例外監視を担当する。

メソッド方針:

- `run_once()` は EventQueue から1件だけ取り出して処理する
- `run()` は `stop()` が呼ばれるまで EventQueue を処理し続ける
- `stop()` は `run()` の継続を停止する

役割分担:

- `run_once()` はユニットテスト・スモークテスト・手動確認に使う
- `run()` はAIライバーの常時稼働Runtimeとして使う
- `stop()` はPyQt6管理画面、終了シグナル、テストから停止するために使う

現時点の RuntimeCoordinator は旧構成の名残として Event から Activity 生成、ActionPlan 生成、Action 実行までを直列に近い形で担当している。
今後はこの責務を段階的に分解し、RuntimeCoordinator は Event 投入、状態同期、各 Loop の起動停止、終了制御、例外監視を行う Host 寄りの責務へ移す。
将来の RuntimeCoordinator / Supervisor の責務:

- ActivityPlanningLoop を task として起動する
- ActivityExecutionLoop を task として起動する
- ExternalEventLoop / EventProcessingLoop を task として起動する
- InputReceiver 群を task として起動する
- stop 時に各 Loop / Receiver へ停止要求を送る
- Loop 内例外を検知し、必要に応じて Runtime 全体を停止する
- 各 Loop の生存状態を Trace / 管理画面へ渡す

RuntimeCoordinator が直接やらないこと:

- LLM へ直接問い合わせる
- 個別 Action を直接実行する
- ActivityPlanningLoop.run_once() を通常運用の中で逐次呼び出す
- ActivityExecutionLoop.run_once() を通常運用の中で逐次呼び出す
- InputReceiver の具体実装を知る

RuntimeCoordinator.run の基本動作:

1. running フラグを有効にする
2. EventQueue からイベントを待ち受ける
3. `SPEECH_STARTED` / `SPEECH_FINISHED` の場合は AgentLifeService のみ更新する
4. 通常 Event の場合は ActivityManager に渡す
5. ActionPlanner で ActionPlanGroup を生成する
6. ActionScheduler で ActionPlanGroup を実行する
7. `stop()` が呼ばれるまで繰り返す

注意点:

- Input Receiver は `run()` の中に直接実装しない
- Input Receiver は別タスクとして並行動作し、`publish_event()` / `publish_events()` を呼ぶ
- `run()` は Runtime の判断・実行ループに集中する
- Action の並列制御は ActionScheduler が担当する
- 将来的には、PyQt6管理画面から `run()` 開始・`stop()` 停止を操作する

現時点の実装仕様:

- `RuntimeCoordinator` は `_running` フラグを持つ
- `run_once()` は Queue が空かどうかに関係なく、AgentLifeService に次の自律 Event 候補を問い合わせる
- AgentLifeService が自律 Event 候補を返した場合、その Event を EventBuffer / EventQueue に投入できる
- 自律 Event は Queue が空であることを発生条件にしない
- `run_once()` は処理可能な Event が存在しない場合のみ `None` を返す
- `run_once()` は EventQueue から1件取り出し、`_handle_event()` に処理を委譲する
- `run()` は `_running=True` にして継続ループを開始する
- `run()` は `run_once()` を繰り返し呼び出す
- EventQueue が空の場合、`run()` は短時間待機してから再確認する
- `stop()` は `_running=False` にして `run()` を停止させる
- `_handle_event()` は Eventから状態更新、Plugin routing、Activity計画要求投入までを担当し、計画と実行は専用Threadへ分離する
- `_handle_event()` は `SPEECH_STARTED` / `SPEECH_FINISHED` を AgentState 更新専用Eventとして扱う
- AgentState 更新専用Eventは ActivityManager に渡さない
- AgentState 更新専用Eventでは ActionPlanner / ActionScheduler を呼ばず、空の ActionPlanGroup を返す
- RuntimeCoordinator は AgentLifeService を注入される
- AgentLifeServiceの生成はComposition Rootだけが担当する
- Event受理直後にAgentLifeServiceが冪等に状態を更新し、ActivityManagerの状態をAgentStateへ同期する
- Input Receiver Port と ConsoleInputReceiver / TimerInputReceiver は実装済み
- RuntimeCoordinator.run() 起動中に外部入力タスクから Event を投入できる
- 内部 Action 由来の Event は RuntimeCoordinator に戻さず、EventBus から EventQueue に投入する
- 自律 Event は、単なる無入力・一定間隔・Queue 空状態ではなく、AgentState の内的動機状態に基づいて発生する
- Action 実行完了後、foreground Activity を completed にし、AgentLifeService に ActivityManager の状態を再同期する
- SPEAK Action は疑似読み上げ時間を持ち、読み上げ予定時間中は MOUTH リソースを占有する
- 自律発話の連続実行は、EmotionState / DriveState から算出した最低間隔で抑制する
- 現時点では LLM 生成と Action 実行が `_handle_event()` 内で直列に行われる
- 今後は LLM による Activity 計画を ActivityPlanningLoop に移し、Action 実行待機を ActivityExecutionLoop に分離する
- RuntimeCoordinator は最終的に、Event 入出力、Loop 起動停止、状態同期の調停役へ寄せる

テストで確認済みの内容:

- `run()` 起動中に `publish_event()` された Event が処理される
- Event がない状態でも `stop()` で `run()` を終了できる
- RuntimeCoordinator 経由で USER_TEXT Event を処理したとき、AgentLifeService の last_user_input_at が更新される
- RuntimeCoordinator 経由で USER_TEXT Event を処理したとき、AgentLifeService の active_activity が同期される
- RuntimeCoordinator 経由で `SPEECH_STARTED` Event を処理したとき、AgentLifeService の last_speech_started_at が更新される
- RuntimeCoordinator 経由で `SPEECH_STARTED` Event を処理したとき、Activity は作成されない
- RuntimeCoordinator 経由で `SPEECH_STARTED` Event を処理したとき、空の ActionPlanGroup が返る
- 内的動機が強い場合、RuntimeCoordinator は AgentLifeService から自律 Event 候補を受け取れる
- EventQueue に外部 Event が存在する状態でも、RuntimeCoordinator は自律 Event 候補を生成できる
- 外部 Event と自律 Event 候補は優先度に従って処理される
- foreground Activity が存在する場合、自律 Event 候補は処理されない

## AgentLifeService / AgentState

AgentLifeService は、AIライバーが外部入力の有無に関係なく、配信活動を継続するための同期状態更新Serviceである。

中心に置くのは「発話」ではなく、Agent の生活・活動状態である。
発話は Activity から派生する Action の一種として扱う。

話題の中心に置くのは「ユーザー入力」ではなく、AIライバー自身の内的関心・気分・興味・飽き・配信中の流れである。
ユーザー入力は、現在の内的状態や話題状態へ影響を与える外部刺激として扱う。

目的:

- 外部入力がない状態でも、AIライバーの活動を継続させる
- 配信全体の状態を AgentState として保持する
- 発話・沈黙・観察・思考・反応を Activity / Action として扱う
- 読み上げ中でも、別リソースで次の思考・観察・話題準備を進められるようにする
- 外部入力が来た場合に、現在の Activity / 実行中 Action / 準備中 Action を調停できるようにする

基本方針:

- AgentLifeService は Timer による定期発話を目的にしない
- AgentLifeService はユーザー入力を自律発話の起点にしない
- AgentLifeService は DriveState / EmotionState / TopicState をもとに、自分から話題を開始・継続・転換する
- ユーザー入力直後の pause は「被せて話さない」ための制御であり、「入力がないから話す」ための制御ではない
- MOUTH が発話中でも、HEAVY_BRAIN / LIGHT_BRAIN / EYES / FACE / SUBTITLE などは別リソースとして並行できる
- ActivityPlanningLoop は HEAVY_BRAIN / LIGHT_BRAIN を使って次の Activity を準備できる
- ActivityExecutionLoop は MOUTH / FACE / BODY / SUBTITLE / OBS などの実行リソースを使って Activity を実行する
- 発話待機や読み上げ時間は ActivityExecutionLoop 側の制約であり、ActivityPlanningLoop の思考処理を止めない
- 外部入力が来た場合は、InterruptionPolicy で中断・継続・破棄・再思考を判断する

AgentState の初期候補:

- active_activity
- pending_activities
- suspended_activities
- running_actions
- prepared_actions
- last_user_input_at
- last_speech_started_at
- last_speech_finished_at
- current_emotion
- current_drive
- current_mood
- attention_target
- stream_status

AgentLifeService が扱う代表的な Activity:

- `STREAMING_SESSION`: 配信全体を継続する親 Activity
- `AUTONOMOUS_TALK`: 自分から話題を進める
- `LISTENING_MODE`: コメントや音声入力を待つ
- `IDLE_OBSERVATION`: 画面・コメント欄・状況を見る
- `THINKING`: 次の話題や返答を考える
- `CONVERSATION_WITH_USER`: 視聴者入力へ応答する
- `STIMULUS_REACTION`: 一瞬の反応をする
- `SILENCE`: あえて黙る
- `LOOK_AROUND`: 画面や配信状況を見る
- `CHECK_COMMENTS`: コメント欄を確認する
- `STREAM_MAINTENANCE`: 配信状態や表示を整える
- `TOPIC_SHIFT`: 話題を転換する
- `TOPIC_CONTINUE`: 現在の話題をもう少し続ける

発話に関する方針:

- AIライバーは「発話を続ける存在」ではなく「配信活動を継続する存在」として扱う
- 発話は SPEAK Action として扱う
- 発話は ActivityQueue の中心概念ではない
- キューに積むのは発話本文ではなく Activity である
- 発話本文は `AUTONOMOUS_TALK` や `CONVERSATION_WITH_USER` Activity を ActionPlan 化する過程で使用する
- SPEAK Action の実行中も、次の思考や観察は別リソースで進められる
- 発話開始は `SPEECH_STARTED` Event として Runtime に戻す
- 発話終了は `SPEECH_FINISHED` Event として Runtime に戻す
- 発話中に外部入力が来た場合、現在の SPEAK Action を中断するか、次に準備していた Action を破棄するかを判断する

感情・気分による制御方針:

- 感情や気分は AgentState の一部として扱う
- talkativeness が高い場合は、発話間隔を短くし、発話や反応を増やす
- talkativeness が低い場合は、短く返す、黙る、観察に寄せる
- 怒っている場合は、発話を減らす、沈黙する、応答を短くする
- 興奮している場合は、表情・声色・発話頻度を強める

内的動機による制御方針:

- 内的動機は DriveState として AgentState の一部に保持する
- curiosity / engagement / boredom / energy を 0.0〜1.0 の範囲で扱う
- 自律発話は、単に入力がないから、一定時間が経過したから、または Queue が空だから発生するのではなく、内的動機が十分強い場合に発生する
- energy が低い場合は、curiosity / engagement / boredom が高くても自律発話しない
- AgentLifeService は DriveState を参照し、次の自律 Event を発生させるか判断する

実装済みファイル:

- `app/runtime/agent_state.py`
- `app/runtime/agent_life_loop.py`
- `app/domain/emotions/emotion_state.py`
- `app/domain/emotions/__init__.py`
- `app/domain/relationships/relationship_state.py`
- `app/domain/relationships/__init__.py`
- `app/domain/drives/drive_state.py`
- `app/domain/drives/__init__.py`
- `tests/test_agent_state.py`
- `tests/test_agent_life_service.py`
- `tests/test_emotion_state.py`
- `tests/test_drive_state.py`

今後追加する予定の概念:

- `app/runtime/interruption_policy.py`

AgentState / EmotionState / AgentLifeServiceの実装とRuntimeCoordinatorへの接続は完了している。
AgentLifeServiceは同期状態更新と自律Event候補の判断を担当し、継続実行はRuntimeCoordinatorと専用Threadが担う。

現時点の実装仕様:

- `AgentLifeService` は AIライバーの生活・活動状態を更新する中核Serviceである
- `AgentLifeService` は ActivityManager を受け取り、AgentState と同期する
- `AgentLifeService` は USER_TEXT / YOUTUBE_COMMENT / USER_SPEECH を受けて last_user_input_at を更新する
- `AgentLifeService` は SPEECH_STARTED / SPEECH_FINISHEDの時刻を更新する
- `AgentLifeService` は EmotionState / DriveState / RelationshipMemoryを更新できる
- `AgentLifeService.plan_next_event()` は現在状態から次に発生させる自律 Event を判断する
- `AgentLifeService.plan_next_event()` は active / pending Activityがある場合、発話抑制状態、内的動機が弱い場合、発話・入力直後には自律Eventを返さない
- `AgentLifeService.plan_next_event()` は、前回の自律発話計画時刻からの経過時間を見て、テンションに応じた自律発話間隔を制御する
- 自律発話間隔は EmotionState の arousal / talkativeness と DriveState の energy をもとに算出する
- 自律発話では、ユーザー入力ではなく内的状態を話題選択の起点にする
- `AgentLifeService.plan_next_event()` は条件を満たした場合、`CURIOSITY_PEAK` Event を返す
- `CURIOSITY_PEAK` Event の payload には `reason: internal_drive` と最も強い drive 名を含める
- `AgentState` は AIライバーの現在状態を保持する Runtime 用モデルである
- `AgentState` は active_activity / pending_activities / suspended_activities を保持する
- `AgentState` は running_actions / prepared_actions を保持する
- `AgentState` は current_emotion / current_drive / relationship_memory / attention_target / stream_status を保持する
- `AgentState` は last_user_input_at / last_speech_started_at / last_speech_finished_at を保持する
- `AgentState` は immutable な dataclass として扱い、状態更新時は新しいインスタンスを返す
- `EmotionState` は mood / arousal / valence / talkativeness を保持する
- `EmotionState` は arousal / talkativeness を 0.0〜1.0、valence を -1.0〜1.0 に制限する
- `EmotionState` は気分に応じた発話抑制・反応増加・発話間隔の判断を提供する
- `RelationshipMemory`は安定したcounterpart_idごとにRelationshipStateをimmutableに保持する
- `RelationshipMemory`は`max_entries`を超える古い相手を破棄し、長時間稼働でも無制限に増加しない
- `RelationshipState`はdisplay_name / role / familiarity / trust / affinity / interaction_count / 最終交流情報を保持する
- USER_TEXTとUSER_SPEECHは`local:user`、YouTube入力はchannel_idを名前空間付きIDとして識別する。明示counterpart_idがある場合はそれを優先する
- Event受理時は交流回数とfamiliarityだけを事実として更新し、発言本文からtrustやaffinityを決めつけない
- Runtimeは当該Turn適用後の関係性を副作用なしでpreviewし、BehaviorPlanningContextとCharacter ResponseContextへ渡す
- Characterへ渡す関係性には発言履歴やPlugin内部状態を含めず、安全な集約値だけを使う
- RelationshipMemoryの永続化は`RelationshipMemoryStore` Portと`RelationshipMemoryPlugin`を介し、JSON Adapterの読み書き失敗時もCore Event処理を継続する
- `memory.relationship_memory`で永続化の有効化、保存先、保持上限を設定する。既定は無効で、会話本文や外部秘密は保存しない（相手IDと表示名を含むため保存先は保護する）
- `DriveState` は curiosity / engagement / boredom / energy を保持する
- `DriveState` は各値を 0.0〜1.0 に制限する
- `DriveState` は内的動機として自律発話を始める強さがあるかを判定する
- `DriveState` は現在もっとも強い内的動機名を返す
- `ExecuteActionUsecase` の `SPEAK` Action から `SPEECH_STARTED` / `SPEECH_FINISHED` Event を発行できる
- `RuntimeCoordinator` は `SPEECH_STARTED` / `SPEECH_FINISHED` を AgentState 更新専用Eventとして扱える

テストで確認済みの内容:

- `AgentLifeService` の初期 AgentState が正しく設定される
- USER_TEXT / YOUTUBE_COMMENT で last_user_input_at が更新される
- SPEECH_STARTED で last_speech_started_at が更新される
- SPEECH_FINISHED で last_speech_finished_at が更新される
- ActivityManager から active / pending / suspended Activity を AgentState に同期できる
- `AgentLifeService` 経由で EmotionStateを更新できる
- `AgentLifeService` 経由で DriveStateを更新できる
- 相手ごとの関係状態を複数Turn・複数相手にわたって独立に保持できる
- Runtimeが現在Turnの関係性をAction生成前のActivity contextへ伝播できる
- 内的動機が強い場合、AgentLifeService は `CURIOSITY_PEAK` Event を返す
- 内的動機が弱い場合、AgentLifeService は自律 Event を返さない
- active Activity がある場合、内的動機が強くても AgentLifeService は自律 Event を返さない
- 発話直後またはユーザー入力直後は、内的動機が強くても AgentLifeService は自律 Event を返さない
- `AgentState` の初期値が正しく設定される
- active_activity / prepared_actions / current_emotion / current_drive を更新できる
- user_input / speech_started / speech_finished の時刻を記録できる
- `EmotionState` の初期値が neutral になる
- angry / tired / sad / low talkativeness で発話抑制判定ができる
- happy / excited / high arousal で反応増加判定ができる
- arousal / valence / talkativeness の範囲外指定でエラーになる
- `DriveState` の初期値が正しく設定される
- `DriveState` の各値が 0.0〜1.0 に制限される
- curiosity / engagement / boredom が高い場合に自律発話判定が True になる
- energy が低い場合は自律発話判定が False になる
- `DriveState` から最も強い内的動機名を取得できる

## Input Receiver

Input Receiver は、外部入力を受け取り、`AgentEvent` として RuntimeCoordinator に投入する入口である。

Input Receiver は AIライバーの活動を開始する主体ではなく、配信中に発生した外部刺激を Runtime に渡す Adapter である。
自律発話や話題選択の主導権は Input Receiver ではなく AgentLifeService / TopicState / DriveState 側に置く。

基本方針:

- Input Receiver は RuntimeCoordinator.run() の中に直接実装しない
- Input Receiver は Runtime とは別タスクとして並行動作する
- Input Receiver は入力を受け取ったら `AgentEvent` を生成する
- 生成した AgentEvent は `publish_event()` / `publish_events()` 経由で Runtime に渡す
- 入力受信口ごとに上限・間引き・最新値保持の方針を持たせる
- RuntimeCoordinator は入力元を意識しない

実装済みファイル:

- `app/runtime/input_receiver.py`
- `app/adapters/input/console_input_receiver.py`
- `app/adapters/input/timer_input_receiver.py`
- `tests/test_console_input_receiver.py`
- `tests/test_timer_input_receiver.py`

実装済み入力アダプタ:

- ConsoleInputReceiver
- TimerInputReceiver

後続工程で追加する入力アダプタ候補:

- YouTubeCommentReceiver
- SpeechRecognitionReceiver
- GameStateReceiver
- CameraFrameReceiver

### ConsoleInputReceiver

ConsoleInputReceiver は、コンソールから入力された文字列を `USER_TEXT` Event として Runtime に投入する入力アダプタである。

現時点の実装仕様:

- `InputReceiver` を実装する
- `start(publish_event)` は内部 task を起動する
- `stop()` は内部 task を停止する
- `wait_until_stopped()` は内部 task の自然終了を待つ
- デフォルト入力は `asyncio.to_thread(input, "> ")` で取得する
- `input_provider` を差し替え可能にし、テストでは FakeInputProvider を使う
- 入力文字列の前後空白は strip で除去する
- 空文字は Event 化しない
- `exit` / `quit` が入力された場合は停止する
- 入力文字列は `USER_TEXT` Event の `payload["text"]` に入れる
- Event の `payload["source"]` には `"console"` を入れる
- publish 後に短く Runtime 側へ制御を渡し、次の入力プロンプトと Action 出力が同じ行に重なりにくいようにする

テストで確認済みの内容:

- 入力文字列が `USER_TEXT` Event として publish される
- publish された Event の payload は `{"text": 入力文字列, "source": "console"}` になる
- 前後の空白は除去される
- 空文字は publish されない
- `exit` / `quit` で停止する

### TimerInputReceiver

TimerInputReceiver は、一定間隔で Runtime に `SILENCE_TIMEOUT` Event を投入するダミー入力アダプタである。現時点では検証用に残すが、AIライバー本体の自律発話起点としては扱わない。

現時点の実装仕様:

- `InputReceiver` を実装する
- `start(publish_event)` は内部 task を起動する
- `stop()` は内部 task を停止する
- `interval_seconds` ごとに `SILENCE_TIMEOUT` Event を publish する
- `max_events` を指定した場合、その件数に達したら自動停止する
- `max_events=None` の場合は `stop()` されるまで動作する
- publish する Event は `discardable=True` / `replace_key="silence_timeout"` を持つ
- 現在の `app/__main__.py` の起動確認は ConsoleInputReceiver を使うコンソール対話デモである

テストで確認済みの内容:

- `SILENCE_TIMEOUT` Event を publish できる
- publish された Event の payload は `{"source": "timer"}` になる
- `max_events` で投入件数を制限できる
- `stop()` すると追加 Event が発生しない

## ResponseGenerator / PromptBuilder / CharacterProfile

ResponseGenerator は、移行後はCharacter LLM相当の発話・表現生成Portとして扱う。
PromptBuilder は、検証済みResponse Context、Activity Result、CharacterProfileからCharacter LLMへ渡す入力を構築する。
CharacterProfile は、AIライバーの人格・口調・配信スタイルを保持するドメインモデルである。
入力の意味解析、Activity選択、Capability可否、実行成功の判断はResponseGeneratorへ持たせない。

目的:

- ActionPlanner から固定応答文を分離する
- 応答生成処理を Dummy / Ollama / OpenAI などへ差し替え可能にする
- LLM 接続前でも Runtime 全体の流れをテストできるようにする
- LLM に投げる前のキャラクター設定を構造化する
- プロンプト生成をテスト可能な部品として独立させる

基本方針:

- ResponseGenerator は runtime 側の Port として定義する
- `generate_response(activity)` は async メソッドにする
- ActionPlanner は ResponseGenerator をコンストラクタで受け取る
- ActionPlanner は `await response_generator.generate_response(activity)` の結果を使って ActionPlanGroup を作る
- `SPEAK` と `UPDATE_SUBTITLE` には同じ応答テキストを使う
- CharacterProfile は domain 層に置く
- PromptBuilder は runtime 側の Port として定義する
- SimplePromptBuilder は adapters 側の初期実装として作る
- PromptBuilder は LLM API を呼ばず、文字列の組み立てだけを担当する
- PromptBuilder は、会話応答用 Prompt と自律発話用 Prompt の責務を分離する方向で整理する
- 自律発話用 Prompt は、ユーザー入力への返答ではなく、AIライバー自身の内的関心から話すための Prompt として扱う
- 直近発話記憶は、会話履歴として返答するためではなく、話題の重複や不自然な断絶を避ける参考情報として使う

実装済みファイル:

- `app/runtime/response_generator.py`
- `app/runtime/prompt_builder.py`
- `app/domain/character/character_profile.py`
- `app/domain/character/__init__.py`
- `app/adapters/llm/dummy_response_generator.py`
- `app/adapters/llm/__init__.py`
- `app/adapters/prompt/simple_prompt_builder.py`
- `app/adapters/prompt/__init__.py`
- `tests/test_action_planner.py`
- `tests/test_dummy_response_generator.py`
- `tests/test_simple_prompt_builder.py`

現時点の実装仕様:

- ResponseGenerator Port を追加済み
- DummyResponseGenerator を追加済み
- ActionPlanner は ResponseGenerator を受け取る
- ActionPlanner.plan() は async メソッドになった
- RuntimeCoordinator は `await action_planner.plan(activity)` を呼ぶ
- DummyResponseGenerator は CharacterProfile と PromptBuilder を受け取る
- DummyResponseGenerator.generate_response() は最初に `prompt_builder.build_prompt(activity, character_profile)` を呼ぶ
- 生成された prompt は latest_prompt に保持される
- DummyResponseGenerator は conversation / autonomous_talk / observation 用のダミー応答を返す
- app/__main__.py は `config.response_generator.type` に従って DummyResponseGenerator または OllamaResponseGenerator を生成し、ActionPlanner に注入する
- CharacterProfile は `name` / `personality` / `speaking_style` / `streaming_style` を持つ
- CharacterProfile は `likes` / `dislikes` / `behavior_policy` を list として持つ
- SimplePromptBuilder は CharacterProfile の人格・口調・配信スタイルを prompt に含める
- SimplePromptBuilder は likes / dislikes / behavior_policy を箇条書きで prompt に含める
- SimplePromptBuilder は Activity の種類と目的を prompt に含める
- conversation Activity では `text` または `comment` をユーザー入力として prompt に含める
- autonomous_talk Activity では自律発話用の指示を prompt に含める
- autonomous_talk Activity では、話題の主導権が AIライバー自身にあることを prompt に含める
- SimplePromptBuilder は ShortTermMemory から直近発話を取得し、参考情報として prompt に含められる
- 直近発話は、必ず続けるべき会話履歴ではなく、話題の重複や不自然な断絶を避けるための情報として扱う
## ShortTermMemory / TopicState 方針

ShortTermMemory は、直近の発話をメモリ上に保持する Runtime 部品である。

`AgentMemoryState`は短期会話ログとは別に、Event事実のエピソード記憶、明示的に学習した
意味記憶、未完了Activityの現在スナップショット、未回収話題、Emotion Appraisal履歴を
型ごとに保持する。各履歴は上限を持ち、Event IDで重複記録しない。RelationshipMemoryは
相手ID単位の関係記憶として独立させる。判断とCharacter Contextには種類を保ったまま渡し、
単一の文字列ログへ平坦化しない。
現時点では、発話内容を最大数件だけ保持し、PromptBuilder に参考情報として渡す。

目的:

- 直近発話の重複を避ける
- 話題が唐突に飛びすぎることを避ける
- 同じ豆知識や同じ感想の反復を抑制する
- ただし、直近発話をユーザー入力のように扱って返答対象にしない

現時点の実装済みファイル:

- `app/domain/short_term_memory.py`

現時点の実装仕様:

- `ShortTermMemory` は直近発話に加え、ユーザーとゆらの会話Turnを順序付きでメモリ上に保持する
- `SpeechMemoryItem` は text / activity_type / created_at を持つ
- `ConversationMemoryItem` は role / text / counterpart_id / display_name / created_at を持つ
- `ShortTermMemory.add_speech()` は SPEAK 完了後の発話を保存する
- `AgentLifeService`はUSER_TEXT / USER_SPEECH / YOUTUBE_COMMENTをEvent ID冪等で会話記憶へ保存する
- `ShortTermMemory.build_recent_speech_summary()` は Prompt に渡すための箇条書き文字列を返す
- `build_recent_conversation_summary()`は相手表示名とゆらを区別した直近Turnを古い順で返す
- RuntimeFactory は `ShortTermMemory` を生成し、AgentLifeService、ResponseContextBuilder、SimplePromptBuilder、ExecuteActionUsecase に同じインスタンスを渡す
- ResponseContextBuilderは通常会話でも直近会話・直近発話・TopicHistoryをCharacter LLMへ渡す
- RuntimeCoordinatorはEvent Filter通過後、Plugin/Behavior routingより先にAgentStateへEventを一度反映する
- 後段Queueで同じEventが処理されてもAgentLifeServiceはevent_idで重複更新を防ぐ
- `RuntimeCoordinator.diagnostic_snapshot()`はEmotion、Drive、関係性集約、Activity/Ongoing状態、Plugin statusと利用可能Capabilityを返す
- 診断スナップショットには会話本文、相手ID・表示名、外部認証情報を含めない
- Streaming compositionは`agent_runtime`としてこのスナップショットをAdmin diagnosticsへ接続する

今後追加する予定の概念:

- `TopicState`
- `TopicStateUpdater`
- `TopicInterestEvaluator`
- `TopicMemory`

TopicState の予定方針:

- 現在の主題を保持する
- 話し足りなさ、飽き、関心の強さ、直近の使用頻度を保持する
- 話題候補ごとに interest / fatigue / freshness を管理する
- 話題の開始・継続・転換を AIライバー自身の状態から決定する
- ユーザー入力やコメントは TopicState へ影響を与える刺激として扱う
- ユーザー入力が来ても、必ずしもその話題へ主導権を渡さない
- その他 Activity では必要な場合のみ短く反応する指示を prompt に含める
- likes / dislikes / behavior_policy が空の場合は `- なし` を出力する

テストで確認済みの内容:

- ActionPlanner が ResponseGenerator の返答を使って `SPEAK` / `UPDATE_SUBTITLE` を作る
- conversation Activity で `SPEAK` / `UPDATE_SUBTITLE` / `CHANGE_EXPRESSION` が作られる
- autonomous_talk Activity で `SPEAK` / `UPDATE_SUBTITLE` が作られる
- idle_observation Activity で `OBSERVE` が作られる
- DummyResponseGenerator が text / comment / autonomous_talk / observation の応答を生成できる
- DummyResponseGenerator が CharacterProfile と SimplePromptBuilder から prompt を生成する
- DummyResponseGenerator の latest_prompt に conversation / autonomous_talk / observation 用 prompt が保持される
- CharacterProfile の値が prompt に含まれる
- likes / dislikes / behavior_policy が箇条書きとして prompt に含まれる
- conversation Activity の `text` / `comment` が prompt に含まれる
- autonomous_talk Activity の目的と自律発話指示が prompt に含まれる
- likes / dislikes / behavior_policy が空の場合、各セクションに `- なし` が出力される

## OllamaResponseGenerator

OllamaResponseGenerator は、ローカルで動作する Ollama の HTTP API に prompt を送信し、生成された応答テキストを返す ResponseGenerator 実装である。

目的:

- DummyResponseGenerator を実際のローカルLLM応答生成に差し替える
- CharacterProfile / PromptBuilder で生成した prompt を Ollama に渡す
- Runtime / Activity / ActionPlanner 側を変更せず、ResponseGenerator の差し替えだけで LLM 応答を利用できるようにする

基本方針:

- ResponseGenerator Port を実装する
- CharacterProfile と PromptBuilder を受け取る
- `generate_response(activity)` の中で `prompt_builder.build_prompt(activity, character_profile)` を呼ぶ
- 生成した prompt を Ollama の `/api/generate` に送る
- 初期実装では `stream=false` を使用し、単一レスポンスとして応答を受け取る
- HTTP 通信には標準ライブラリの `urllib.request` を使い、依存ライブラリを増やさない
- 接続先 URL は config から受け取る
- model 名は config から受け取る
- 生成された prompt は latest_prompt に保持する
- Ollama から返った応答テキストは前後空白を除去して返す
- 応答が空の場合は安全なフォールバック文を返す
- HTTP エラーや JSON 解析エラーは RuntimeError として扱う

実装済みファイル:

- `app/adapters/llm/ollama_response_generator.py`
- `tests/test_ollama_response_generator.py`

修正済みファイル:

- `app/adapters/llm/__init__.py`
- `app/__main__.py`
- `docs/source_file_plan.md`

テストで確認済みの内容:

- OllamaResponseGenerator が PromptBuilder で prompt を生成する
- 生成した prompt が latest_prompt に保持される
- Ollama API に `model` / `prompt` / `stream=false` を含む JSON を送信する
- Ollama API の `response` を応答テキストとして返す
- 応答文字列の前後空白が除去される
- 空応答の場合はフォールバック文を返す
- 通信エラー時は RuntimeError を送出する

現時点の到達点:

- DummyResponseGenerator と同じ Port で OllamaResponseGenerator を使える
- `config.response_generator.type` を切り替えることで Dummy / Ollama を選択できる
- モデル名や接続先URLは `config/config.yaml` から読み込む構成に移行済み

## Config / 設定ファイル

AIライバーのキャラクター設定、応答生成器、入力アダプタ設定は、コードに直書きせず `config/config.yaml` から読み込む。

目的:

- モデル名や接続先URLをコード修正なしで切り替えられるようにする
- キャラクター設定をコードから分離する
- Dummy / Ollama などの ResponseGenerator を設定で切り替えられるようにする
- 今後追加する TTS / OBS / YouTube / Live2D などの設定を同じ形式で管理できるようにする

実装済みファイル:

- `config/config.yaml`
- `app/config/app_config.py`

修正済みファイル:

- `app/__main__.py`

設定ファイル形式:

- YAML を使用する
- 人間が編集することを前提にする
- キャラクター設定やリスト項目を読みやすく管理する

現時点の `config/config.yaml` の主な項目:

- `app.name`
- `app.mode`
- `response_generator.type`
- `response_generator.ollama.model`
- `response_generator.ollama.api_url`
- `response_generator.ollama.timeout_seconds`
- `response_generator.ollama.fallback_response`
- `response_generator.dummy.enabled`
- `character.name`
- `character.name_reading`
- `character.personality`
- `character.speaking_style`
- `character.streaming_style`
- `character.likes`
- `character.dislikes`
- `character.behavior_policy`
- `input_receivers.console.enabled`
- `input_receivers.timer.enabled`
- `input_receivers.timer.interval_seconds`
- `input_receivers.timer.max_events`

設定読み込み方針:

- `app/config/app_config.py` で YAML を読み込む
- YAML の内容は dataclass に変換して扱う
- `app/__main__.py` は `load_app_config()` を呼び、取得した設定を使って Runtime を組み立てる
- `CharacterProfile` は `config.character` から生成する
- ResponseGenerator は `config.response_generator.type` によって dummy / ollama を切り替える
- Ollama の model / api_url / timeout / fallback_response は `config.response_generator.ollama` から取得する

安全方針:

- デフォルト値による補完は行わない
- 設定ファイルが存在しない場合は異常終了する
- 設定ファイルが空の場合は異常終了する
- 必須設定が不足している場合は異常終了する
- 型が不正な場合は異常終了する
- 必須文字列が空文字の場合は異常終了する
- `input_receivers.timer.max_events` のみ `null` を許可する

この方針により、設定ミスがある状態で想定外のモデル・キャラクター・入力設定のまま起動することを防ぐ。

現時点の確認結果:

- `config/config.yaml` から `character.name: 星波ゆら` を読み込める
- `python -m app` で `星波ゆら` として応答できる
- `pytest` は `101 passed` を確認済み

## Runtime Composition Root

Runtime Composition Rootは、RuntimeCoordinatorとその周辺部品、具体Adapter、
Pluginを組み立てるFactoryである。Core Runtimeの責務ではないため、
`app.bootstrap`に配置する。

目的:

- `app/__main__.py` から Runtime 構築責務を分離する
- EventQueue / EventBus / ActivityManager / ActionPlanner / ActionScheduler / ActivityPlanningLoop / ActivityExecutionLoop / ExecuteActionUsecase / RuntimeCoordinator の生成を一箇所に集約する
- ResponseGenerator や CharacterProfile の生成を Runtime 起動処理から分離する
- 今後 TTS / OBS / Live2D / YouTube コメント入力などの Adapter が増えても、起動処理を肥大化させない

実装済みファイル:

- `app/bootstrap/runtime.py`
- `app/runtime/runtime_factory.py`（旧import向けの互換re-exportのみ）
- `tests/test_runtime_factory.py`

現時点の実装仕様:

- `create_character_profile(config)` で CharacterProfile を生成する
- `create_response_generator(config, character_profile, prompt_builder)` で Dummy / Ollama / OpenAI の ResponseGenerator を切り替える
- `create_runtime_coordinator(config)` で RuntimeCoordinator を生成する
- `create_runtime_coordinator(config)` は EventQueue と EventBus を同じ Queue で接続する
- `create_runtime_coordinator(config)` は `ExecuteActionUsecase(event_publisher=event_bus)` を生成する
- `create_runtime_coordinator(config)` は `ShortTermMemory` を生成し、`SimplePromptBuilder` と `ExecuteActionUsecase` に共有インスタンスとして渡す
- `app/bootstrap/__init__.py` から `create_runtime_coordinator` をexportする
- `app/runtime`は具体AdapterまたはPluginをimport・構成しない
- `app/__main__.py` は Runtime 構築を直接行わず、`create_runtime_coordinator(config)` を呼ぶ

テストで確認済みの内容:

- `create_runtime_coordinator(config)` が RuntimeCoordinator を返す

## 起動確認

`app/__main__.py` は、`config/config.yaml` を読み込み、RuntimeFactory で RuntimeCoordinator を生成し、RuntimeCoordinator.run() と ConsoleInputReceiver を組み合わせたコンソール対話デモとして動作する。

確認できる流れ:

1. `load_app_config()` で `config/config.yaml` を読み込む
2. `create_runtime_coordinator(config)` で RuntimeCoordinator を生成する
3. RuntimeFactory 内で CharacterProfile と DummyResponseGenerator / OllamaResponseGenerator を生成する
4. RuntimeCoordinator.run() を別 task で開始する
5. ConsoleInputReceiver を開始する
6. コンソールから文字列を入力する
7. ConsoleInputReceiver が `USER_TEXT` Event を publish する
8. Runtime が Event を処理し、ActionPlanGroup を実行する
9. `exit` / `quit` 入力で ConsoleInputReceiver が停止する
10. `runtime.stop()` で Runtime を停止する

```bash
python -m app
```

期待される出力例:

```text
コンソール入力デモを開始します。終了するには exit または quit を入力してください。
> こんにちは

[speak] こんにちは！星波ゆらです。今日も一緒に楽しもうね♪何か話したいことありますか？
[subtitle] こんにちは！星波ゆらです。今日も一緒に楽しもうね♪何か話したいことありますか？
[expression] smile
> quit
終了しました。
```

## テスト

必要な依存関係:

```bash
pipenv install --dev pytest-asyncio
pipenv install PyYAML
```

テスト実行:

```bash
pytest
```

現時点の確認結果:

```text
112 passed
```

## 今後の課題

- Runtime 全体骨格を先に確定し、既存の直列 RuntimeCoordinator 構成を段階的に置き換える
- Loop と Service / Processor / Usecase の命名基準を整理する
- RuntimeCoordinator を RuntimeSupervisor / RuntimeHost として再定義するか検討する
- ActivityPlanningLoop / ActivityExecutionLoop を `run_once()` 呼び出し型ではなく、独立した `run()` loop として接続する
- ExternalEventLoop / EventProcessingLoop を追加し、外部 Event 処理を RuntimeCoordinator から分離する
- PromptBuilder を ConversationPromptBuilder / AutonomousTalkPromptBuilder に分離する
- TopicState / TopicMemory を追加し、話題の主導権を AIライバー自身に持たせる
- TopicInterestEvaluator を追加し、興味・関心の高い話題ではテンションを上げ、興味・関心の低い話題ではテンションを下げる
- SILENCE_TIMEOUT を自律発話の主導 Event として扱わないよう整理する
- PlannedActivityQueue を追加し、Speech ではなく Activity をキューに積む
- ActivityPlanningLoop を追加し、LLM による Activity 計画を RuntimeCoordinator から分離する
- ActivityExecutionLoop を追加し、Activity 実行・発話待機・実行間隔制御を RuntimeCoordinator から分離する
- RuntimeCoordinator を Event 入出力、状態同期、Loop 起動停止の Host へ寄せる
- LLM 生成待ちと Activity 実行待ちを分離し、発話中でも次の Activity を準備できるようにする
- `app/__main__.py` を ConsoleInputReceiver 中心のデモ起動から RuntimeHost 中心の起動構成へ整理する
- ActivityManager の複数 ACTIVE 対応
- Activity に required_resources を持たせるかどうかの検討
- suspended Activity の再開方針
- ActionExecutor からの成功・失敗イベント連携
- DriveState を時間経過・配信状況・コメント状況から変化させる仕組み
- DriveState から autonomous_talk 以外の Activity を選ぶ方針
- 自律 Event 候補の増殖を防ぐための replace_key / cooldown / Activity 状態の整理
- 外部 Event と自律 Event の優先度設計の精密化
- TTS Adapter の追加
- 字幕表示 Adapter の追加
- Live2D / 表情制御 Adapter の追加
- OBS Adapter の追加
- YouTube コメント入力 Adapter の追加
- 音声認識入力 Adapter の追加
- PyQt6 管理画面から Runtime の start / stop を操作する機能

## Games Pluginの入力分類と実行

- `app/plugins/games/intent/`: 開始・継続・制御・通常会話を区別する決定論的判定、LLMフォールバック、Parser、Validator
- `app/plugins/games/engine.py`と`session.py`: ゲームSessionのライフサイクルと状態の正本
- `app/plugins/games/shiritori/`: しりとりの状態、ルール、進行Service、専用Prompt
- `app/plugins/games/plugin.py`: 共通Command/Result/ActivityStateへの変換、失敗時rollback、Capability縮退
- `app/runtime/runtime_coordinator.py`: Plugin共通契約に基づく実行とOngoingActivity同期だけを担当する
- GameSessionをゲーム状態の唯一の正本とし、開始要求・AI初手・ゲーム内単語はtopic memoryから除外する
- `app/__main__.py`: ConsoleInputReceiverを`RuntimeCoordinator.submit_user_text`へ接続する本番入口
- 本番RuntimeFactoryはGames Pluginを登録し、ゲーム内部コンポーネントの生成はPlugin初期化へ委ねる
- 本番Factory経由テストでは公開入力APIから3手以上進行し、Plugin Session IDとOngoingActivity IDの継続を確認する

## Plugin構成

- `app/shared/contracts/plugins/runtime/`: 常駐Runtime PluginのContext、Capability、汎用Command/Result契約
- `app/shared/contracts/plugins/registration/`: 管理・Streaming orchestration向け非同期Registration契約と`PluginActivitySpec`
- `app/shared/contracts/activity.py`: PluginとCoreが共有するActivity Definition / Matcher / ActivityPlan view契約
- `app/shared/contracts/memory.py`: 区分別Memory DTO、versioned Snapshot、Store Protocol
- `app/shared/contracts/expression.py`と`output.py`: エンジン非依存VoiceIntent、SpeechSynthesizer、AudioPlayer契約
- `app/shared/plugin_host/`: 汎用PluginRegistryとCommand / Query / Activity Dispatcher
- `app/shared/observability/`: bounded replayを持つ実装非依存ApplicationEventBroker
- `app/core/plugins/`: Runtime PluginManager、CapabilityRegistryと旧import互換入口。契約の正本は置かない
- `app/plugins/games/plugin.py`: Games Pluginの初期化、Intent公開境界、Command実行、ActivityRequest変換
- Games Plugin内のLLM要求と生成作業は`PluginLlmRequest` / `PluginActivityWorkItem`を使い、composition rootだけがCore Activityへ変換する
- Games Pluginの観測ログはShared `PluginLogger`を使い、Core TraceContextへ依存しない
- `app/plugins/games/intent/`: GameIntentCommand、意味解析Prompt、JSON Parser、Validator
- `app/plugins/llm_provider/`: 役割別ResponseGenerator Adapterを`llm.provider.<role>` Capabilityとして公開し、障害時は当該ProviderのCapabilityだけを解除する
- LLM Provider PluginはSharedの`ResponseGenerationGateway`だけを受け取り、Core Activity型や旧ResponseGenerator Portをimportしない
- default / situation_evaluator / character / response_validatorは独立Providerとして登録し、役割ごとの障害を隔離する
- `app/plugins/relationship_memory/`: Sharedの型付き`SnapshotStore`を`memory.relationship` Capabilityとして公開し、保存対象のCore型を知らずに障害を隔離する
- `app/plugins/agent_memory/`: Shared Snapshot Storeを`memory.agent_state` Capabilityとして公開し、JSON永続化障害をCoreから隔離する
- `app/plugins/voice_output/`: Sharedの表現・出力契約だけに依存し、合成・再生障害時に`output.speech`を解除する
- Pluginの`capabilities`はManifest相当の提供可能性宣言、`available_capabilities`は初期化・設定・依存・Provider健全性を反映した現在値として区別する
- CapabilityRegistryは許可リスト方式でCapability単位に登録・解除・Provider解決を行い、未対応機能一覧や拒否リストは持たない
- disabled、初期化失敗、停止、依存・Health喪失時は該当Capabilityを解除する。Games PluginはLLM Provider不在時に実行Capabilityを登録しない
- RuntimeCoordinatorは現在使用可能なCapabilityからInterpreter/Handlerを取得し、Command実行直前にも同じPluginのCapabilityを再検証する
- 実行要求に一致するCapabilityがなければ通常会話へ戻し、実行したふりと内部用語を禁止する制約をPromptへ渡す。知識質問・過去・否定・雑談は機能不在を理由に拒否しない
- 未知の要求でも仮Capabilityを生成せず、安全な通常会話へ戻す。代替案は現在可能なものを最大一つに限定する
- ActionPlannerは`prepared_response_text`とPlugin MemoryPolicyを汎用的に適用する
- `plugins.games.enabled`でゲーム機能をCore変更なしに無効化できる
- 将来別Pythonパッケージへ分離する場合も、`app/shared`の契約とGatewayだけを依存境界とする
- mixed入力は構造化までとし、ゲーム進行と雑談応答の統合は次工程で実装する

## Behavior Planner・Situation Evaluator・Character LLM

本プロジェクトでは、未知のユーザー入力を特定ワードや特定Plugin向けの固定分岐で処理しない。
登録済みのActivityDefinitionを意味的に照合し、実行可否と発話表現を分離する汎用構造を採用する。

詳細設計は `docs/llm_role_architecture.md` を正本とする。

基本フロー:

```text
External Event
  ↓
Situation Evaluator
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
Response Context
  ↓
Character LLM
  ↓
Response Validator
  ↓
ActionPlanGroup / Output Unit
```

責務分離:

- Situation Evaluatorは人格を持たず、入力の意味、発話意図、Activity候補、operation、constraints、否定、仮定、過去、知識質問、confidenceを構造化する
- `SituationState`は直近Event、注意対象、Foreground/Pending/Suspended/Ongoing Activityの要約を継続保持し、会話本文は短期記憶へ分離する
- Behavior PlannerはSituation Evaluatorの解析結果、AgentState、OngoingActivity、ActivityDefinitionを基に次の行動を決定する
- Activity Registryは「どのようなActivityが存在するか」の正本とする
- Capability Registryは「現在そのActivityを実行できるか」の正本とする
- Pluginが無効でもActivityの意味認識は可能とし、実行可否だけをCapability Registryで拒否する
- Activity Resultは、実際に起きた事実の正本とする
- Response ContextはActivity Resultと現在状態を、Character LLMが安全に表現できる形式へ整理する
- Character LLMはキャラクター口調、感情表現、発話、表情、ジェスチャー候補だけを生成する
- Response ValidatorはCharacter LLM出力とActivity Resultの整合性を検証し、未実行・拒否・失敗した処理を成功したように発話させない
- Character LLMへユーザー入力だけを直接渡し、行動判断と最終発話を同時に行わせない
- LLMが返したActivity名、Capability、Providerは信用せず、登録済み定義から導出する
- 架空Activity、不正JSON、低確信度、LLM障害は安全なConversationまたは確認へフォールバックする
- 再生成は最大1回とし、無制限ループを禁止する

汎用化方針:

- Coreへ「しりとり」「検索」「OBS」等の特定ワード判定を埋め込まない
- 個別Activityの意味情報、supported operations、constraints schema、required capability、provider pluginはActivityDefinitionまたはPlugin側が提供する
- 決定論的Matcherを使う場合もPlugin側から共通インターフェースで提供し、Coreは候補比較だけを行う
- 未知の言い回しはSituation EvaluatorがActivityDefinition一覧と意味照合する
- 発話の整合性検証はキーワードブラックリストではなく、対応する成功Activity Resultの有無で判断する
- ゲーム、外部検索、OBS操作、音楽再生、アバター操作、ファイル操作、外部サービス操作に同じ仕組みを適用する

Activity Resultの最低項目:

- `activity_type`
- `operation`
- `status`
- `capability`
- `provider_plugin_id`
- `result_payload`
- `failure_reason`
- `constraints`

status候補:

- `succeeded`
- `rejected`
- `failed`
- `canceled`
- `waiting_input`

LLMロール:

- `situation_evaluator`
- `character`
- `response_validator`

初期実装では同じProvider・Modelを共有してよいが、設定、Prompt、依存関係、temperatureは論理ロールごとに分離する。
将来はSituation Evaluatorを低温度・構造化出力重視、Character LLMを表現力重視、Response Validatorを低温度・整合性重視のモデルへ個別に差し替えられるようにする。

ログ方針:

- INFOには最終Behavior判断、Activity結果、Character応答生成完了、Validator拒否・置換、重要なフォールバックだけを残す
- DEBUGにはSituation Evaluator入力、ActivityDefinition候補、LLM生出力、構造化解析、Activity Plan、Capability検証、Activity Result、Response Context、Character LLM入出力、Validator結果を記録する
- Promptや生成結果を記録する場合は共通マスク処理を通す

既存クラスとの関係:

- 現行`BehaviorPlanner`は段階的にSituation Evaluatorと行動選択責務へ分離する
- 現行`ResponseGenerator`はCharacter LLM相当の発話生成Portへ整理する
- `ActionPlanner`はCharacter LLM出力を直接信用せず、検証済みResponseをActionPlanGroupへ変換する
- `RuntimeCoordinator`は個別機能判定を持たず、各Service・Registry・Loopの接続と実行調停へ寄せる
- `OngoingActivity`は複数Turnの目的と状態を保持し、各Turnの実行結果はActivity Resultとして記録する
