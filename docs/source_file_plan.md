# ソースファイル作成方針

## 目的

初期実装では、外部APIへ接続せず、活動駆動型Runtimeの最小骨格を作成する。

## 今回作成する範囲

- Event
- Activity
- Action
- EventQueue
- ActivityManager
- ActionPlanner
- RuntimeCoordinator
- ExecuteActionUsecase
- 起動確認用 `app/__main__.py`
- Runtimeのスモークテスト

## 方針

- Event は「起きたこと」
- Activity は「継続する目的」
- Action は「今この瞬間に実行する命令」
- RuntimeCoordinator が EventQueue → ActivityManager → ActionPlanner → Executor を接続する
- 初期段階では TTS / LLM / OBS / YouTube へ接続しない
- 外部接続は後続工程で Adapter / Channel Executor として追加する

## EventFilter / Prioritizer 方針

RuntimeCoordinator.publish_event は、EventQueue へ直接投入せず、次の順で処理する。

1. EventFilter でイベントを正規化・破棄判定する
2. EventPrioritizer で優先度を補正する
3. EventQueue へ投入する

追加ファイル:

- `app/runtime/event_filter.py`
- `app/runtime/event_prioritizer.py`

現時点のルール:

- user_text は高優先度で保持する
- youtube_comment は中〜高優先度で保持する
- camera_frame は discardable とし、replace_key に `camera_frame` を設定する
- silence_timeout は discardable とし、replace_key に `silence_timeout` を設定する
- speech_finished は内部連鎖イベントとして優先度を補正する

discardable / replace_key は EventFilter で付与し、EventBuffer が replace_key 単位で最新イベントだけを保持する。

## EventBuffer / publish_events 方針

RuntimeCoordinator は、単一イベント投入と複数イベント投入の両方を扱う。

- `publish_event(event)` は単一イベント投入用
- `publish_events(events)` は複数イベント投入用
- `publish_event(event)` は内部的に `publish_events([event])` へ委譲する

追加ファイル:

- `app/runtime/event_buffer.py`
- `tests/test_event_buffer.py`
- `tests/test_runtime_coordinator.py`

EventBuffer のルール:

- replace_key がないイベントは投入順に全件保持する
- replace_key があるイベントは同じ replace_key の最新イベントだけ保持する
- user_text / youtube_comment は全件保持する
- camera_frame / silence_timeout は複数投入時に最新だけ保持する

RuntimeCoordinator.publish_events の処理順:

1. EventFilter でイベントを正規化する
2. EventPrioritizer で優先度を補正する
3. EventBuffer に投入する
4. EventBuffer.drain で通常イベントと最新化済みイベントを取り出す
5. EventQueue へ投入する

現時点で確認済みのテスト:

- user_text は複数件すべて処理される
- camera_frame は複数件投入しても最新だけ処理される
- user_text と camera_frame が混在しても、user_text と最新 camera_frame が処理される

## ActivityManager 優先度・中断制御方針

ActivityManager は、Event から Activity を生成するだけでなく、現在の foreground Activity と新しい Activity を比較し、活動の前面化・保留・一時停止を判断する。

基本方針:

- Activity は foreground / pending / suspended / completed / canceled として管理する
- 新しい Activity が来たら、現在の foreground Activity と優先度を比較する
- 新しい Activity の優先度が高く、現在の foreground Activity が interruptible=True の場合、新しい Activity を foreground にする
- その場合、元の foreground Activity は suspended にする
- 現在の foreground Activity が interruptible=False の場合、新しい Activity は pending にする
- 新しい Activity の優先度が foreground Activity 以下の場合も pending にする

初期実装で扱う代表ケース:

- idle_observation 中に user_text が来た場合、conversation_with_user を active にする
- autonomous_talk 中に user_text が来た場合、autonomous_talk を suspended にし、conversation_with_user を active にする
- conversation_with_user 中に silence_timeout が来た場合、conversation_with_user を維持し、autonomous_talk を pending にする

追加・修正予定ファイル:

- `app/runtime/activity_manager.py`
- `tests/test_activity_manager.py`
- 必要に応じて `tests/test_runtime_coordinator.py`

現時点では ActivityTransitionService は作成せず、ActivityManager 内に最小実装する。
ロジックが複雑化した段階で、ActivityTransitionService へ分離する。

## Activity 完了・pending 再開方針

ActivityManager は、Action 実行後に Activity を完了状態へ進め、必要に応じて pending Activity を active に戻す。

基本方針:

- Action 実行が完了した Activity は completed にする
- 完了した Activity が foreground Activity の場合、foreground を空にする
- pending Activity が存在する場合、優先度が最も高い Activity を active にする
- pending Activity が複数ある場合は priority が高いものを優先する
- priority が同じ場合は、現時点では登録順に依存する
- suspended Activity の自動再開はまだ行わない

追加予定メソッド:

- `complete_activity(activity_id)`
- `complete_foreground_activity()`
- `resume_next_pending()`

初期実装で扱う代表ケース:

- conversation_with_user が完了したら completed になる
- foreground Activity 完了後、pending の autonomous_talk が active になる
- pending がない場合、foreground Activity は `None` になる

この段階では、ActionExecutor からの成功・失敗イベント連携はまだ行わない。
まず ActivityManager 単体でライフサイクルを閉じる。

## ActionResource / ActionPlanGroup / ActionScheduler 方針

AIライバーは常時稼働するため、入力受信・判断・出力実行を分けて扱う。

基本方針:

- Input Receiver は並行して動作する
- Event は発生タイミングで受け入れ、EventQueue / EventBuffer へ投入する
- RuntimeCoordinator は Event を Activity / Action へ変換する判断部分を担当する
- 実際の出力・操作は ActionScheduler が物理I/Oリソースごとに制御する
- 同時実行できるかどうかは、Activity そのものではなく Action が使用するリソースで判定する

追加予定の概念:

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

ActionPlanGroup は、1つの Activity から生成される複数 ActionPlan のまとまりである。

例:

- conversation_with_user
  - `SPEAK` uses `MOUTH`
  - `CHANGE_EXPRESSION` uses `FACE`
  - `UPDATE_SUBTITLE` uses `SUBTITLE`

ActionScheduler の基本ルール:

- required_resources が衝突しない Action は並列実行できる
- required_resources が衝突する Action は同時実行しない
- `MOUTH` を使う Action は同時に1つまで
- `HANDS` を使う Action は同時に1つまで
- `HEAVY_BRAIN` を使う Action は同時数を制限する
- `FACE` や `SUBTITLE` は将来的に最新値上書き型にできる

次の実装順:

1. `app/domain/actions/action_resource.py` を追加する
2. `ActionPlan` に `required_resources` を追加する
3. `app/domain/actions/action_plan_group.py` を追加する
4. `ActionPlanner.plan()` の戻り値を `ActionPlan` から `ActionPlanGroup` に変更する
5. `app/runtime/action_scheduler.py` を追加する
6. `ExecuteActionUsecase` は単一 ActionPlan の実行責務として残す
7. RuntimeCoordinator は ActionPlanGroup を ActionScheduler に渡す形へ変更する

この段階では、ActivityManager の複数 ACTIVE 対応はまだ行わない。
まずは、1つの Activity から複数 Action を生成し、リソース単位で並列実行できる土台を作る。
その後、Activity に required_resources を追加し、複数 Activity を同時 ACTIVE にできる設計へ拡張する。

### 実装済みの確定仕様

追加済みファイル:

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

現時点の実装仕様:

- `ActionPlan` は `required_resources` を持つ
- `ActionPlanner.plan()` は `ActionPlanGroup` を返す
- `conversation_with_user` は `SPEAK` / `UPDATE_SUBTITLE` / `CHANGE_EXPRESSION` を返す
- `autonomous_talk` は `SPEAK` / `UPDATE_SUBTITLE` を返す
- `idle_observation` 系は `OBSERVE` を返す
- `RuntimeCoordinator.run_once()` は `ActionPlanGroup | None` を返す
- `RuntimeCoordinator` は `ActionScheduler` 経由で ActionPlanGroup を実行する
- `ExecuteActionUsecase` は単一 `ActionPlan` の実行責務として残す

ActionScheduler の確定仕様:

- 空の `ActionPlanGroup` は何も実行しない
- `required_resources` が空の ActionPlan はそのまま実行する
- 異なる `required_resources` を持つ ActionPlan は並列実行できる
- 同じ `required_resources` を持つ ActionPlan は同時実行しない
- 複数リソースを持つ ActionPlan は、リソース名順で Lock を取得してデッドロックを防ぐ

テストで確認済みの内容:

- 空の ActionPlanGroup は何もしない
- 異なるリソースの Action は実行される
- required_resources なしの Action も実行される
- `MOUTH` を共有する複数 Action は同時実行されない
- RuntimeCoordinator は ActionPlanGroup を返す
- RuntimeCoordinator 経由でも `SPEAK` / `OBSERVE` を取り出して確認できる

現時点での到達点:

- 発話しながら字幕を出す土台ができた
- 発話しながら表情を変える土台ができた
- ただし、複数の発話は同時実行しない
- ActivityManager の複数 ACTIVE 対応はまだ未実装

## RuntimeCoordinator.run / stop 方針

RuntimeCoordinator は、テスト・手動確認用の単発処理と、常時稼働用の継続処理を分けて提供する。

メソッド方針:

- `run_once()` は EventQueue から1件だけ取り出して処理する
- `run()` は `stop()` が呼ばれるまで EventQueue を処理し続ける
- `stop()` は `run()` の継続を停止する

役割分担:

- `run_once()` はユニットテスト・スモークテスト・手動確認に使う
- `run()` はAIライバーの常時稼働Runtimeとして使う
- `stop()` はPyQt6管理画面、終了シグナル、テストから停止するために使う

RuntimeCoordinator.run の基本動作:

1. running フラグを有効にする
2. EventQueue からイベントを待ち受ける
3. Event を ActivityManager に渡す
4. ActionPlanner で ActionPlanGroup を生成する
5. ActionScheduler で ActionPlanGroup を実行する
6. `stop()` が呼ばれるまで繰り返す

注意点:

- Input Receiver は `run()` の中に直接実装しない
- Input Receiver は別タスクとして並行動作し、`publish_event()` / `publish_events()` を呼ぶ
- `run()` はRuntimeの判断・実行ループに集中する
- Action の並列制御は引き続き ActionScheduler が担当する
- 将来的には、PyQt6管理画面から `run()` 開始・`stop()` 停止を操作する

追加・修正予定ファイル:

- `app/runtime/runtime_coordinator.py`
- `tests/test_runtime_coordinator.py`

### 実装済みの確定仕様

修正済みファイル:

- `app/runtime/runtime_coordinator.py`
- `tests/test_runtime_coordinator.py`

現時点の実装仕様:

- `RuntimeCoordinator` は `_running` フラグを持つ
- `run_once()` は EventQueue が空の場合 `None` を返す
- `run_once()` は EventQueue から1件取り出し、`_handle_event()` に処理を委譲する
- `run()` は `_running=True` にして継続ループを開始する
- `run()` は `run_once()` を繰り返し呼び出す
- EventQueue が空の場合、`run()` は短時間待機してから再確認する
- `stop()` は `_running=False` にして `run()` を停止させる
- `_handle_event()` は Event から Activity / ActionPlanGroup / ActionScheduler 実行までを担当する

テストで確認済みの内容:

- `run()` 起動中に `publish_event()` された Event が処理される
- Event がない状態でも `stop()` で `run()` を終了できる

現時点での到達点:

- 常時稼働Runtimeの最小骨格ができた
- Input Receiver はまだ未実装
- 次工程で Input Receiver Port とダミー入力アダプタを追加する

## Input Receiver Port 方針

Input Receiver は、外部入力を受け取り、`AgentEvent` として `RuntimeCoordinator` に投入する入口である。

基本方針:

- Input Receiver は `RuntimeCoordinator.run()` の中に直接実装しない
- Input Receiver は Runtime とは別タスクとして並行動作する
- Input Receiver は入力を受け取ったら `AgentEvent` を生成する
- 生成した `AgentEvent` は `publish_event()` / `publish_events()` 経由で Runtime に渡す
- 入力受信口ごとに上限・間引き・最新値保持の方針を持たせる
- RuntimeCoordinator は入力元を意識しない

Input Receiver の代表例:

- `ConsoleInputReceiver`: コンソール入力を `USER_TEXT` として投入する
- `TimerInputReceiver`: 一定時間ごとに `SILENCE_TIMEOUT` などを投入する
- `YouTubeCommentReceiver`: YouTubeコメントを `YOUTUBE_COMMENT` として投入する
- `SpeechRecognitionReceiver`: 音声認識結果を `USER_SPEECH` として投入する
- `GameStateReceiver`: ゲーム状態変化を Event として投入する
- `CameraFrameReceiver`: カメラ・画面フレームを `CAMERA_FRAME` として投入する

追加予定ファイル:

- `app/runtime/input_receiver.py`
- `app/adapters/input/console_input_receiver.py`
- `app/adapters/input/timer_input_receiver.py`

初期実装では、まず Port のみを定義する。
実際の入力アダプタは次工程で追加する。

## TimerInputReceiver 方針

TimerInputReceiver は、一定間隔で Runtime に `SILENCE_TIMEOUT` Event を投入するダミー入力アダプタである。

目的:

- Input Receiver が Runtime とは別タスクで並行動作することを確認する
- `RuntimeCoordinator.run()` 起動中に外部入力タスクから Event を投入できることを確認する
- 無音時間をきっかけに `AUTONOMOUS_TALK` Activity が生成される流れを確認する

基本方針:

- `InputReceiver` Protocol を実装する
- `start(publish_event)` で内部タスクを起動する
- `stop()` で内部タスクを停止する
- interval 秒ごとに `SILENCE_TIMEOUT` Event を publish する
- `max_events` を指定できるようにし、テストやデモで無限投入を避ける
- `max_events=None` の場合は stop() されるまで投入し続ける

追加予定ファイル:

- `app/adapters/input/timer_input_receiver.py`
- `tests/test_timer_input_receiver.py`

初期テストで確認する内容:

- `start()` 後に `SILENCE_TIMEOUT` Event が publish される
- `max_events` を指定した場合、その件数だけ publish される
- `stop()` を呼ぶと投入が止まる

### 実装済みの確定仕様

追加済みファイル:

- `app/adapters/input/timer_input_receiver.py`
- `app/adapters/input/__init__.py`
- `tests/test_timer_input_receiver.py`

修正済みファイル:

- `app/runtime/input_receiver.py`
- `app/runtime/__init__.py`

現時点の実装仕様:

- `InputReceiver` Protocol を追加済み
- `EventPublisher` 型を追加済み
- `TimerInputReceiver` は `InputReceiver` を実装する
- `TimerInputReceiver.start(publish_event)` は内部 task を起動する
- `TimerInputReceiver.stop()` は内部 task を停止する
- `interval_seconds` ごとに `SILENCE_TIMEOUT` Event を publish する
- `max_events` を指定した場合、その件数に達したら自動停止する
- `max_events=None` の場合は `stop()` されるまで動作する
- publish する Event は `discardable=True` / `replace_key="silence_timeout"` を持つ

テストで確認済みの内容:

- `TimerInputReceiver` が `SILENCE_TIMEOUT` Event を publish できる
- publish された Event の payload は `{"source": "timer"}` になる
- `max_events` で投入件数を制限できる
- `stop()` すると追加 Event が発生しない

現時点での到達点:

- Runtime とは別 task で入力口を動かす土台ができた
- TimerInputReceiver から Runtime へ Event を投入できる準備ができた
- `app/__main__.py` を更新し、`RuntimeCoordinator.run()` と `TimerInputReceiver` の統合デモを作成済み

## ConsoleInputReceiver 方針

ConsoleInputReceiver は、コンソールから入力された文字列を `USER_TEXT` Event として Runtime に投入する入力アダプタである。

目的:

- 手入力で Runtime に Event を投入できるようにする
- 常時稼働 Runtime に対して、外部入力が並行に入る構造を確認する
- 最小の対話デモを作る

基本方針:

- `InputReceiver` Protocol を実装する
- `start(publish_event)` で内部 task を起動する
- `stop()` で内部 task を停止する
- 空文字は Event 化しない
- `exit` / `quit` が入力された場合は停止する
- 入力された文字列は `USER_TEXT` Event の `payload["text"]` に入れる
- Event の `payload["source"]` には `"console"` を入れる
- テストしやすいように、入力取得処理は差し替え可能にする

追加予定ファイル:

- `app/adapters/input/console_input_receiver.py`
- `tests/test_console_input_receiver.py`


初期テストで確認する内容:

- 入力文字列が `USER_TEXT` Event として publish される
- 前後の空白は除去される
- 空文字は publish されない
- `exit` / `quit` で停止する

### 実装済みの確定仕様

追加済みファイル:

- `app/adapters/input/console_input_receiver.py`
- `tests/test_console_input_receiver.py`

修正済みファイル:

- `app/adapters/input/__init__.py`
- `app/__main__.py`

現時点の実装仕様:

- `ConsoleInputReceiver` は `InputReceiver` を実装する
- `ConsoleInputReceiver.start(publish_event)` は内部 task を起動する
- `ConsoleInputReceiver.stop()` は内部 task を停止する
- `ConsoleInputReceiver.wait_until_stopped()` は内部 task の自然終了を待つ
- デフォルト入力は `asyncio.to_thread(input, "> ")` で取得する
- `input_provider` を差し替え可能にし、テストでは FakeInputProvider を使う
- 入力文字列の前後空白は `strip()` で除去する
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
- `exit` で停止する
- `quit` で停止する

現時点での到達点:

- コンソールから手入力した文字列を Runtime に投入できる
- `RuntimeCoordinator.run()` 起動中に ConsoleInputReceiver から `USER_TEXT` Event を投入できる
- 最小の対話デモが動作する

## ResponseGenerator / DummyResponseGenerator 方針

ResponseGenerator は、Activity から応答テキストを生成する Port である。

目的:

- ActionPlanner から固定応答文を分離する
- 応答生成処理を Dummy / Ollama / OpenAI などへ差し替え可能にする
- LLM 接続前でも Runtime 全体の流れをテストできるようにする

基本方針:

- `ResponseGenerator` は Runtime 側の Port として定義する
- `generate_response(activity)` は async メソッドにする
- ActionPlanner は ResponseGenerator をコンストラクタで受け取る
- ActionPlanner は `await response_generator.generate_response(activity)` の結果を使って ActionPlanGroup を作る
- `SPEAK` と `UPDATE_SUBTITLE` には同じ応答テキストを使う
- LLM 接続前の仮実装として `DummyResponseGenerator` を使う

### 実装済みの確定仕様

追加済みファイル:

- `app/runtime/response_generator.py`
- `app/adapters/llm/dummy_response_generator.py`
- `app/adapters/llm/__init__.py`
- `tests/test_action_planner.py`
- `tests/test_dummy_response_generator.py`

修正済みファイル:

- `app/runtime/action_planner.py`
- `app/runtime/runtime_coordinator.py`
- `app/__main__.py`
- `tests/test_runtime_coordinator.py`
- `tests/test_runtime_smoke.py`

現時点の実装仕様:

- `ResponseGenerator` Port を追加済み
- `DummyResponseGenerator` を追加済み
- `ActionPlanner` は `ResponseGenerator` を受け取る
- `ActionPlanner.plan()` は async メソッドになった
- `RuntimeCoordinator` は `await action_planner.plan(activity)` を呼ぶ
- `DummyResponseGenerator` は `CONVERSATION_WITH_USER` に対して `ダミー応答: 入力文字列` を返す
- `DummyResponseGenerator` は `AUTONOMOUS_TALK` に対して `ダミー自律発話: 何か面白い話題を考えています。` を返す
- `app/__main__.py` は `DummyResponseGenerator` を `ActionPlanner` に注入する

テストで確認済みの内容:

- ActionPlanner が ResponseGenerator の返答を使って `SPEAK` / `UPDATE_SUBTITLE` を作る
- conversation Activity で `SPEAK` / `UPDATE_SUBTITLE` / `CHANGE_EXPRESSION` が作られる
- autonomous_talk Activity で `SPEAK` / `UPDATE_SUBTITLE` が作られる
- idle_observation Activity で `OBSERVE` が作られる
- DummyResponseGenerator が text / comment / autonomous_talk / observation の応答を生成できる

現時点での到達点:

- 固定応答文を ActionPlanner から分離できた
- 将来の Ollama / OpenAI / キャラクター応答生成へ差し替える入口ができた
- コンソール対話デモで `ダミー応答: 入力文字列` が出力される


## CharacterProfile / PromptBuilder 方針

CharacterProfile は、AIライバーの人格・口調・配信スタイルを保持するドメインモデルである。
PromptBuilder は、Activity と CharacterProfile から LLM に渡すプロンプトを生成する Port である。

目的:

- LLM に投げる前のキャラクター設定を構造化する
- AIライバーの人格・口調・行動方針を ResponseGenerator から分離する
- Ollama / OpenAI / ローカルLLM のどれに差し替えても、同じ CharacterProfile と PromptBuilder を使えるようにする
- プロンプト生成をテスト可能な部品として独立させる

基本方針:

- `CharacterProfile` は domain 層に置く
- `PromptBuilder` は runtime 側の Port として定義する
- `SimplePromptBuilder` は adapters 側の初期実装として作る
- `PromptBuilder.build_prompt(activity, character_profile)` は同期メソッドにする
- LLM API 呼び出しは PromptBuilder では行わない
- PromptBuilder は文字列の組み立てだけを担当する
- ResponseGenerator は将来的に PromptBuilder を使って LLM 用 prompt を作る

CharacterProfile の初期項目:

- `name`: キャラクター名
- `personality`: 性格
- `speaking_style`: 口調
- `streaming_style`: 配信スタイル
- `likes`: 好きな話題・もの
- `dislikes`: 苦手な話題・もの
- `behavior_policy`: 行動方針・禁止事項

追加予定ファイル:

- `app/domain/character/character_profile.py`
- `app/domain/character/__init__.py`
- `app/runtime/prompt_builder.py`
- `app/adapters/prompt/simple_prompt_builder.py`
- `app/adapters/prompt/__init__.py`
- `tests/test_simple_prompt_builder.py`

初期テストで確認する内容:

- CharacterProfile の値が prompt に含まれる
- conversation Activity のユーザー入力が prompt に含まれる
- autonomous_talk Activity の目的が prompt に含まれる
- likes / dislikes / behavior_policy が複数行として prompt に含まれる
- SimplePromptBuilder は LLM API を呼ばず、文字列生成だけを行う


次工程の到達目標:

- キャラクター人格をコード上の構造として扱えるようにする
- Activity から LLM 用 prompt を作れるようにする
- OllamaResponseGenerator 実装前の土台を作る

### 実装済みの確定仕様

追加済みファイル:

- `app/domain/character/character_profile.py`
- `app/domain/character/__init__.py`
- `app/runtime/prompt_builder.py`
- `app/adapters/prompt/simple_prompt_builder.py`
- `app/adapters/prompt/__init__.py`
- `tests/test_simple_prompt_builder.py`

修正済みファイル:

- `app/runtime/__init__.py`

現時点の実装仕様:

- `CharacterProfile` を domain 層に追加済み
- `CharacterProfile` は `name` / `personality` / `speaking_style` / `streaming_style` を持つ
- `CharacterProfile` は `likes` / `dislikes` / `behavior_policy` を list として持つ
- `PromptBuilder` Port を runtime 層に追加済み
- `PromptBuilder.build_prompt(activity, character_profile)` は同期メソッドとして定義する
- `SimplePromptBuilder` を adapters 層に追加済み
- `SimplePromptBuilder` は LLM API を呼ばず、prompt 文字列の生成だけを担当する
- `SimplePromptBuilder` は CharacterProfile の人格・口調・配信スタイルを prompt に含める
- `SimplePromptBuilder` は likes / dislikes / behavior_policy を箇条書きで prompt に含める
- `SimplePromptBuilder` は Activity の種類と目的を prompt に含める
- conversation Activity では `text` または `comment` をユーザー入力として prompt に含める
- autonomous_talk Activity では自律発話用の指示を prompt に含める
- その他 Activity では必要な場合のみ短く反応する指示を prompt に含める
- likes / dislikes / behavior_policy が空の場合は `- なし` を出力する

テストで確認済みの内容:

- CharacterProfile の値が prompt に含まれる
- likes / dislikes / behavior_policy が箇条書きとして prompt に含まれる
- conversation Activity の `text` が prompt に含まれる
- conversation Activity の `comment` が prompt に含まれる
- autonomous_talk Activity の目的と自律発話指示が prompt に含まれる
- likes / dislikes / behavior_policy が空の場合、各セクションに `- なし` が出力される

現時点での到達点:

- キャラクター人格をコード上の構造として扱えるようになった
- Activity と CharacterProfile から LLM 用 prompt を生成できるようになった
- OllamaResponseGenerator 実装前の prompt 生成土台ができた
- テスト件数は `47 passed` まで増加した

## 起動確認

`app/__main__.py` は、`RuntimeCoordinator.run()` と `ConsoleInputReceiver` を組み合わせたコンソール対話デモとして動作する。

確認できる流れ:

1. `RuntimeCoordinator.run()` を別 task で開始する
2. `ConsoleInputReceiver` を開始する
3. コンソールから文字列を入力する
4. `ConsoleInputReceiver` が `USER_TEXT` Event を publish する
5. Runtime が Event を処理し、ActionPlanGroup を実行する
6. `exit` / `quit` 入力で ConsoleInputReceiver が停止する
7. `runtime.stop()` で Runtime を停止する

```bash
python -m app
```

期待される出力例:

```text
コンソール入力デモを開始します。終了するには exit または quit を入力してください。
> こんにちは

[speak] ダミー応答: こんにちは
[subtitle] ダミー応答: こんにちは
[expression] smile
> quit
終了しました。
```

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```
