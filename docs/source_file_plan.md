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

初期実装で薄くしてよい部分:

- TopicState は最初は未実装または簡易版でよい
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
- AgentLifeLoop
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
- RuntimeFactory
- ExecuteActionUsecase
- 起動確認用 `app/__main__.py`
- Runtime のスモークテスト

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

現時点では未実装。
まずは資料方針を確定し、その後 `PlannedActivityQueue` の最小実装から追加する。
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
- suspended Activity の自動再開はまだ行わない

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
LLM応答テキスト
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
- `VoiceVoxSpeechSynthesizer` はVOICEVOX API通信と補正コンポーネントの呼び出しを調停する
- `ExecuteActionUsecase` は表示・記憶用の元文を変更せず、音声合成結果の再生だけを扱う

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

テストで確認済みの内容:

- 空の ActionPlanGroup は何もしない
- 異なるリソースの Action は実行される
- required_resources なしの Action も実行される
- `MOUTH` を共有する複数 Action は同時実行されない
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
- ActivityManager の複数 ACTIVE 対応はまだ未実装

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
3. `SPEECH_STARTED` / `SPEECH_FINISHED` の場合は AgentLifeLoop のみ更新する
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
- `run_once()` は Queue が空かどうかに関係なく、AgentLifeLoop に次の自律 Event 候補を問い合わせる
- AgentLifeLoop が自律 Event 候補を返した場合、その Event を EventBuffer / EventQueue に投入できる
- 自律 Event は Queue が空であることを発生条件にしない
- `run_once()` は処理可能な Event が存在しない場合のみ `None` を返す
- `run_once()` は EventQueue から1件取り出し、`_handle_event()` に処理を委譲する
- `run()` は `_running=True` にして継続ループを開始する
- `run()` は `run_once()` を繰り返し呼び出す
- EventQueue が空の場合、`run()` は短時間待機してから再確認する
- `stop()` は `_running=False` にして `run()` を停止させる
- `_handle_event()` は Event から Activity / AgentLifeLoop / ActionPlanGroup / ActionScheduler 実行までを担当する
- `_handle_event()` は `SPEECH_STARTED` / `SPEECH_FINISHED` を AgentState 更新専用Eventとして扱う
- AgentState 更新専用Eventは ActivityManager に渡さない
- AgentState 更新専用Eventでは ActionPlanner / ActionScheduler を呼ばず、空の ActionPlanGroup を返す
- RuntimeCoordinator は AgentLifeLoop を任意注入できる
- AgentLifeLoop が未指定の場合は、RuntimeCoordinator 内で `AgentLifeLoop(activity_manager)` を生成する
- ActivityManager が Event を処理した後、AgentLifeLoop が Event と ActivityManager の状態を AgentState に同期する
- Input Receiver Port と ConsoleInputReceiver / TimerInputReceiver は実装済み
- RuntimeCoordinator.run() 起動中に外部入力タスクから Event を投入できる
- 内部 Action 由来の Event は RuntimeCoordinator に戻さず、EventBus から EventQueue に投入する
- 自律 Event は、単なる無入力・一定間隔・Queue 空状態ではなく、AgentState の内的動機状態に基づいて発生する
- Action 実行完了後、foreground Activity を completed にし、AgentLifeLoop に ActivityManager の状態を再同期する
- SPEAK Action は疑似読み上げ時間を持ち、読み上げ予定時間中は MOUTH リソースを占有する
- 自律発話の連続実行は、EmotionState / DriveState から算出した最低間隔で抑制する
- 現時点では LLM 生成と Action 実行が `_handle_event()` 内で直列に行われる
- 今後は LLM による Activity 計画を ActivityPlanningLoop に移し、Action 実行待機を ActivityExecutionLoop に分離する
- RuntimeCoordinator は最終的に、Event 入出力、Loop 起動停止、状態同期の調停役へ寄せる

テストで確認済みの内容:

- `run()` 起動中に `publish_event()` された Event が処理される
- Event がない状態でも `stop()` で `run()` を終了できる
- RuntimeCoordinator 経由で USER_TEXT Event を処理したとき、AgentLifeLoop の last_user_input_at が更新される
- RuntimeCoordinator 経由で USER_TEXT Event を処理したとき、AgentLifeLoop の active_activity が同期される
- RuntimeCoordinator 経由で `SPEECH_STARTED` Event を処理したとき、AgentLifeLoop の last_speech_started_at が更新される
- RuntimeCoordinator 経由で `SPEECH_STARTED` Event を処理したとき、Activity は作成されない
- RuntimeCoordinator 経由で `SPEECH_STARTED` Event を処理したとき、空の ActionPlanGroup が返る
- 内的動機が強い場合、RuntimeCoordinator は AgentLifeLoop から自律 Event 候補を受け取れる
- EventQueue に外部 Event が存在する状態でも、RuntimeCoordinator は自律 Event 候補を生成できる
- 外部 Event と自律 Event 候補は優先度に従って処理される
- foreground Activity が存在する場合、自律 Event 候補は処理されない

## AgentLifeLoop / AgentState

AgentLifeLoop は、AIライバーが外部入力の有無に関係なく、配信活動を継続するための中核ループである。

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

- AgentLifeLoop は Timer による定期発話を目的にしない
- AgentLifeLoop はユーザー入力を自律発話の起点にしない
- AgentLifeLoop は DriveState / EmotionState / TopicState をもとに、自分から話題を開始・継続・転換する
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

AgentLifeLoop が扱う代表的な Activity:

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
- AgentLifeLoop は DriveState を参照し、次の自律 Event を発生させるか判断する

実装済みファイル:

- `app/runtime/agent_state.py`
- `app/runtime/agent_life_loop.py`
- `app/domain/emotions/emotion_state.py`
- `app/domain/emotions/__init__.py`
- `app/domain/drives/drive_state.py`
- `app/domain/drives/__init__.py`
- `tests/test_agent_state.py`
- `tests/test_agent_life_loop.py`
- `tests/test_emotion_state.py`
- `tests/test_drive_state.py`

今後追加する予定の概念:

- `app/runtime/interruption_policy.py`

現時点では、AgentState / EmotionState / AgentLifeLoop の最小実装は完了している。
AgentLifeLoop はまだ自律進行の run() は持たず、AgentState の更新と ActivityManager からの状態同期を担当する。
RuntimeCoordinator への軽い接続は完了しており、Event 処理時に AgentLifeLoop の AgentState も更新される。

現時点の実装仕様:

- `AgentLifeLoop` は AIライバーの生活・活動状態を更新する中核ループの土台である
- `AgentLifeLoop` は ActivityManager を受け取り、AgentState と同期する
- `AgentLifeLoop` は USER_TEXT / YOUTUBE_COMMENT / USER_SPEECH を受けて last_user_input_at を更新する
- `AgentLifeLoop` は SPEECH_STARTED を受けて last_speech_started_at を更新する
- `AgentLifeLoop` は SPEECH_FINISHED を受けて last_speech_finished_at を更新する
- `AgentLifeLoop` は EmotionState を更新できる
- `AgentLifeLoop` は DriveState を更新できる
- `AgentLifeLoop.plan_next_event()` は現在状態から次に発生させる自律 Event を判断する
- `AgentLifeLoop.plan_next_event()` は active Activity または pending Activity がある場合は自律 Event を返さない
- `AgentLifeLoop.plan_next_event()` は EmotionState が発話抑制状態の場合は自律 Event を返さない
- `AgentLifeLoop.plan_next_event()` は DriveState の内的動機が弱い場合は自律 Event を返さない
- `AgentLifeLoop.plan_next_event()` は直前の発話終了直後またはユーザー入力直後は自律 Event を返さない
- `AgentLifeLoop.plan_next_event()` は、前回の自律発話計画時刻からの経過時間を見て、テンションに応じた自律発話間隔を制御する
- 自律発話間隔は EmotionState の arousal / talkativeness と DriveState の energy をもとに算出する
- 自律発話では、ユーザー入力ではなく内的状態を話題選択の起点にする
- `AgentLifeLoop.plan_next_event()` は条件を満たした場合、`CURIOSITY_PEAK` Event を返す
- `CURIOSITY_PEAK` Event の payload には `reason: internal_drive` と最も強い drive 名を含める
- `AgentState` は AIライバーの現在状態を保持する Runtime 用モデルである
- `AgentState` は active_activity / pending_activities / suspended_activities を保持する
- `AgentState` は running_actions / prepared_actions を保持する
- `AgentState` は current_emotion / current_drive / attention_target / stream_status を保持する
- `AgentState` は last_user_input_at / last_speech_started_at / last_speech_finished_at を保持する
- `AgentState` は immutable な dataclass として扱い、状態更新時は新しいインスタンスを返す
- `EmotionState` は mood / arousal / valence / talkativeness を保持する
- `EmotionState` は arousal / talkativeness を 0.0〜1.0、valence を -1.0〜1.0 に制限する
- `EmotionState` は気分に応じた発話抑制・反応増加・発話間隔の判断を提供する
- `DriveState` は curiosity / engagement / boredom / energy を保持する
- `DriveState` は各値を 0.0〜1.0 に制限する
- `DriveState` は内的動機として自律発話を始める強さがあるかを判定する
- `DriveState` は現在もっとも強い内的動機名を返す
- `ExecuteActionUsecase` の `SPEAK` Action から `SPEECH_STARTED` / `SPEECH_FINISHED` Event を発行できる
- `RuntimeCoordinator` は `SPEECH_STARTED` / `SPEECH_FINISHED` を AgentState 更新専用Eventとして扱える

テストで確認済みの内容:

- `AgentLifeLoop` の初期 AgentState が正しく設定される
- USER_TEXT / YOUTUBE_COMMENT で last_user_input_at が更新される
- SPEECH_STARTED で last_speech_started_at が更新される
- SPEECH_FINISHED で last_speech_finished_at が更新される
- ActivityManager から active / pending / suspended Activity を AgentState に同期できる
- `AgentLifeLoop` 経由で EmotionState を更新できる
- `AgentLifeLoop` 経由で DriveState を更新できる
- 内的動機が強い場合、AgentLifeLoop は `CURIOSITY_PEAK` Event を返す
- 内的動機が弱い場合、AgentLifeLoop は自律 Event を返さない
- active Activity がある場合、内的動機が強くても AgentLifeLoop は自律 Event を返さない
- 発話直後またはユーザー入力直後は、内的動機が強くても AgentLifeLoop は自律 Event を返さない
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
自律発話や話題選択の主導権は Input Receiver ではなく AgentLifeLoop / TopicState / DriveState 側に置く。

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

ResponseGenerator は、Activity から応答テキストを生成する Port である。
PromptBuilder は、Activity と CharacterProfile から LLM に渡すプロンプトを生成する Port である。
CharacterProfile は、AIライバーの人格・口調・配信スタイルを保持するドメインモデルである。

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
現時点では、発話内容を最大数件だけ保持し、PromptBuilder に参考情報として渡す。

目的:

- 直近発話の重複を避ける
- 話題が唐突に飛びすぎることを避ける
- 同じ豆知識や同じ感想の反復を抑制する
- ただし、直近発話をユーザー入力のように扱って返答対象にしない

現時点の実装済みファイル:

- `app/runtime/short_term_memory.py`

現時点の実装仕様:

- `ShortTermMemory` は直近発話をメモリ上に保持する
- `SpeechMemoryItem` は text / activity_type / created_at を持つ
- `ShortTermMemory.add_speech()` は SPEAK 完了後の発話を保存する
- `ShortTermMemory.build_recent_speech_summary()` は Prompt に渡すための箇条書き文字列を返す
- RuntimeFactory は `ShortTermMemory` を生成し、`SimplePromptBuilder` と `ExecuteActionUsecase` に同じインスタンスを渡す

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

## RuntimeFactory

RuntimeFactory は、RuntimeCoordinator とその周辺部品を組み立てる Factory である。

目的:

- `app/__main__.py` から Runtime 構築責務を分離する
- EventQueue / EventBus / ActivityManager / ActionPlanner / ActionScheduler / ActivityPlanningLoop / ActivityExecutionLoop / ExecuteActionUsecase / RuntimeCoordinator の生成を一箇所に集約する
- ResponseGenerator や CharacterProfile の生成を Runtime 起動処理から分離する
- 今後 TTS / OBS / Live2D / YouTube コメント入力などの Adapter が増えても、起動処理を肥大化させない

実装済みファイル:

- `app/runtime/runtime_factory.py`
- `tests/test_runtime_factory.py`

現時点の実装仕様:

- `create_character_profile(config)` で CharacterProfile を生成する
- `create_response_generator(config, character_profile, prompt_builder)` で Dummy / Ollama / OpenAI の ResponseGenerator を切り替える
- `create_runtime_coordinator(config)` で RuntimeCoordinator を生成する
- `create_runtime_coordinator(config)` は EventQueue と EventBus を同じ Queue で接続する
- `create_runtime_coordinator(config)` は `ExecuteActionUsecase(event_publisher=event_bus)` を生成する
- `create_runtime_coordinator(config)` は `ShortTermMemory` を生成し、`SimplePromptBuilder` と `ExecuteActionUsecase` に共有インスタンスとして渡す
- `app/runtime/__init__.py` から `create_runtime_coordinator` を export する
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
