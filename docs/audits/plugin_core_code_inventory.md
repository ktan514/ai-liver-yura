# Plugin / Core responsibility and code inventory

調査日: 2026-07-17  
性質: 設計書ではなく、現状コードの静的棚卸しレポート  
制約: 本番コード・設定・テスト・設計書は変更していない。Secret値、`.env`、実YouTube/OBSは参照していない。

## 1. Executive Summary

配信の縦経路は、Admin APIがComposition Rootとなる構成では一通り接続されている。ただし「Streaming Plugin」としての実装境界はまだ成立していない。`app/plugins/youtube_streaming`は準備Capabilityの宣言に留まり、実際のSession、Lifecycle、開始・終了、コメント処理は`app/domain/streaming`、`app/usecases`、`app/admin_api/service.py`、`app/runtime`へ分散している。

最優先の問題は次の4点である。

1. `AdminApiService.configure_opening()`がStreaming Composition Rootになり、Usecase、Repository、Lifecycle、Runtime callbackを直接組み立てている。
2. `RuntimeCoordinator`が1,939行、`AdminApiService`が906行、管理Windowが664行あり、配信固有オーケストレーションと共通Runtime/UI表示が集中している。
3. `CommentRankingUsecase`がin-memory Adapterを直接importし、`YouTubeLiveChatPoller`がYouTube AdapterのError型を直接importしている。Port境界を逆流している。
4. Admin側でmoderation handlerを構成しないRuntimeでは、`YOUTUBE_COMMENT`が従来どおりActivityManagerへ到達し、直接会話Activityになり得る。新しいModeration→Ranking→Response経路と旧直接応答経路が構成条件付きで並存する。

削除を先行させるべきではない。まず縦経路のCharacterization Test、Streaming Runtime Facade、Portの引き上げ、旧経路の明示的Feature Gate化を行い、その後にShimや互換入力を小単位で除去する。

## 2. 現在の縦経路

管理プロセスを含む現在の主要経路は以下である。

```text
streaming_admin
  -> REST/SSE
  -> app.admin_api.server / AdminApiService
  -> PrepareStreamSessionUsecase
  -> StartStreamSessionUsecase
  -> OBS / YouTube control adapters
  -> StreamOpeningUsecase
  -> RuntimeCoordinator.execute_stream_opening
  -> STREAM_STARTED / STREAM_OPENING_GREETING
  -> CharacterResponsePipeline / Claim validation
  -> ActionPlanner / ActionScheduler / output adapters
  -> StreamMainSegmentUsecase
  -> STREAM_MAIN_SEGMENT / same output pipeline
  -> YouTubeLiveChatPoller
  -> RuntimeCoordinator moderation interception
  -> CommentModerationUsecase
  -> CommentRankingUsecase / reservation
  -> CommentResponseUsecase
  -> STREAM_COMMENT_RESPONSE / same output pipeline
  -> EndStreamSessionUsecase
  -> Closing output
  -> YouTube end / OBS stop
```

この経路は`AdminApiService.configure_opening()`が呼ばれた場合に成立する。Core Runtime単独生成時のコメント経路は同一ではない。

## 3. Package責務一覧

| Package | Files | Python LOC | 現在の主責務 | 推奨分類 |
|---|---:|---:|---|---|
| `app/domain` | 54 | 3,495 | Event、Activity、Action、共通Result、Streaming/Game model | Core + Streaming Plugin + Game Pluginが混在 |
| `app/runtime` | 36 | 11,801 | Runtime loop、Character pipeline、Scheduler、Factory、Game実行 | Core中心だがComposition/Plugin固有分岐が混在 |
| `app/usecases` | 13 | 4,478 | Streaming縦経路と共通Action実行 | 主にStreaming Plugin |
| `app/ports` | 15 | 343 | 外部境界、Repository契約 | Core/Plugin契約 |
| `app/adapters` | 65 | 5,752 | YouTube、OBS、LLM、TTS、Storage、Fake | Platform Adapter |
| `app/plugins` | 19 | 1,253 | Games pluginと薄いYouTube plugin宣言 | Plugin registration |
| `app/admin_api` | 5 | 1,344 | REST、SSE、DTO、Composition | Admin API。ただしStreaming orchestration過多 |
| `app/ui` | 3 | 8 | 廃止UI launcher shim | Legacy / Migration |
| `streaming_admin` | 13 | 1,264 | 別プロセスPyQt6 client/controller/window | Streaming Admin UI |
| `tests` | 85 | 15,864 | Unit/回帰テスト | Test infrastructure |
| `scripts` | 1 | 52 | Topic memory DB初期化 | Infrastructure |

補助集計:

- `RuntimeCoordinator`: 1,939行
- `AdminApiService`: 906行
- Admin API server: 351行
- Streaming Admin Window: 664行
- Streaming Admin Controller: 214行
- `*usecase.py`: 10ファイル
- Port module: 15ファイル
- 名前にrepositoryを含む本番module: 5ファイル（実クラス/Protocolはこれより多い）
- `fake*.py`: 5ファイル（Factory内のFake構築も別途存在）
- `stream.*` capability文字列: 静的ユニーク61件
- `stream_comments.*` SSE event文字列: 静的ユニーク23件
- `config.yaml` leaf項目: 179件、うち`streaming.*`は55件

数値はPython sourceのみで、vendor/generated/cacheを除外した静的集計である。

## 4. Coreに残す責務

- `AgentEvent`、汎用Activity/Action/Result、Trace correlation
- EventBuffer、EventFilter、EventPrioritizer
- ActivityManagerの汎用queue/foreground/ongoing規則
- ActionPlannerの共通Plan生成契約
- ActionSchedulerのResource arbitrationと同期Output Unit
- CharacterResponsePipeline、Claim Extractor/Validatorの共通契約
- Capability Registry、Plugin Context/Protocol、matcher契約
- 汎用Repository/Portのプロトコル定義

Streaming固有Enum値をCore Enumに持つ現状は実用上動作するが、外部Plugin追加を考えると登録可能なActivity/Event discriminatorへ寄せる余地がある。

## 5. Streaming Pluginへ属する責務

- `app/domain/streaming/*`のSession、RunOfShow、Lifecycle、Opening/Main/End、Comment model
- Start/End/Emergency、Opening/Main、Poller、Moderation、Ranking、Response Usecase
- Streaming固有Lifecycle operationとCapability policy
- Streaming Repository契約とin-process実装の選択
- Streaming RuntimeへのEvent変換
- YouTube/OBS AdapterをPortへ束ねるComposition

現状これらは`app/plugins/youtube_streaming`から所有・登録されていない。Plugin packageはCapability宣言だけで、実装の所有権を表していない。

## 6. Adapter責務

- `app/adapters/youtube`: Google API、OAuth、Live Chat、状態/Error mapping
- `app/adapters/obs`: WebSocket client、状態/Error mapping、control/preparation
- `app/adapters/tts`: synthesis/playback境界
- `app/adapters/llm`, `prompt`, `topic`, `embedding`: model/platform実装
- `app/adapters/storage`: persistence
- `app/adapters/streaming`: in-memory/YAML/Fake implementations

Fakeは`RuntimeFactory`がconfigに応じて本番Compositionでも明示的に利用するため、一律削除対象ではない。FakeとUnavailable Adapterの役割を別名・別packageに分ける検討は可能である。

## 7. Admin API / UI責務

Admin APIに残すもの:

- REST request/response DTO変換
- SSE replay/fan-out
- 認証操作と非同期Command受付
- Streaming facadeの照会・Command呼出し
- Secretを返さない境界

移動すべきもの:

- Lifecycle Gate、全Repository、全Streaming Usecaseの構築
- Candidate選定後にResponseを自動開始するcallback
- Main topicからRanking contextを組み立てる処理
- Capability availabilityのStreaming固有判定

Streaming Admin UIの依存方向は良好で、`streaming_admin -> HTTP/SSE -> Admin API`に限定される。Domain Repositoryへの直接アクセスはない。PyQt6 importも`streaming_admin`とUIテストだけで、Coreにはない。

## 8. 重複経路

### Opening

`StreamOpeningUsecase`は状態・冪等性・RunOfShow・失敗を担当し、出力は`STREAM_STARTED -> STREAM_OPENING_GREETING`へ委譲する。現在は二重発話ではなくlayered orchestrationである。ただし`STREAM_STARTED`を外部から直接publishできるため、Usecaseを通さない旧入口は残る。入口をpackage-private相当にするか、Session/Activity correlation必須にするCharacterizationが必要。

### Main

Main Segment出力とAutonomous Talkは同じCharacter/Action pipelineを使うが、開始条件と目的は別である。重複はPipeline再利用として妥当。一方、Topic selection、AgentLife autonomous planning、Main topicの責務境界はRuntimeCoordinator/AgentLife/Usecaseに跨り、同じ「次に何を話すか」を複数箇所で決めている。調停Policyの統合が必要。

### Comment Response

新経路は`YOUTUBE_COMMENT(not_evaluated) -> moderation -> candidate -> ranking -> reserved target -> STREAM_COMMENT_RESPONSE`である。しかしmoderation handler未設定時、または`moderation_status`がないEventはActivityManagerの従来のYouTube comment会話経路へ流れる。これは最重要の重複経路であり、旧入口の明示的無効化前にCore-only runtime testとAdmin-composed runtime testを分離して固定する必要がある。

### Output

Opening/Main/Closing/Comment ResponseのActivity固有ExecutorはすべてRuntimeCoordinatorを経由して共通ActionSchedulerへ到達するため、通常の出力は統合されている。Legacy ResponseGenerator fallbackはCharacter pipeline未構成時のfallbackとして並存し、直ちに削除できない。RuntimeCoordinatorに直接output helperとActivity固有wrapperが多数ある点はFacade抽出候補である。

### End

通常終了と緊急停止は意図的に別Policyである。旧markerベースstopはStreamingではなくActivity matcher互換層に残る。OBS/YouTube stopの実処理はEnd Usecase側へ集約されており、明白な二重停止経路は静的調査では確認できない。Race/partial failure testを維持してから互換markerを整理すべきである。

## 9. Legacy / Migration候補

- `app/ui/pyqt/__main__.py`, `app/ui/pyqt/__init__.py`: 新UIへのlauncher shim
- `ActivityDefinition.start_markers/stop_markers`
- `runtime/activity_matcher_resolver.py`のlegacy marker adapter
- `activity_constraints.py`のlegacy schema adapter/deprecation warning
- Character pipeline未構成時のlegacy ResponseGenerator fallback
- `app/domain/games/shiritori.py` + `app/runtime/shiritori_game_service.py`と`app/plugins/games/shiritori/*`の二系統

いずれも参照・テストがあり、A判定にはしない。

## 10. Game固有漏出

- Core Domainに`app/domain/games/shiritori.py`が残る。
- Core Runtimeに`shiritori_game_service.py`とActionPlanner/RuntimeCoordinatorのShiritori分岐が残る。
- 新Games Pluginにも`app/plugins/games/shiritori/*`が存在する。
- Prompt Builder、GameInputClassifier、RuntimeFactoryが`shiritori`文字列・stateを認識する。
- `siritori`表記の本番実装は見つからず、現行表記は`shiritori`に統一されている。

Game plugin registrationとRuntime executionが移行途中であり、旧Domain/Runtime実装を削除する前にPlugin側が同じsession continuity、validation、AI turn、failure rollbackを提供する必要がある。

## 11. 依存方向違反

確認できた問題:

- `CommentRankingUsecase -> app.adapters.streaming.in_memory_comment_ranking_repositories`
- `YouTubeLiveChatPoller -> app.adapters.youtube.youtube_api_error_mapper`
- `CharacterResponsePipeline`、`SituationEvaluator -> app.adapters.prompt` concrete builder
- `RuntimeFactory -> 全Adapter`はComposition Rootとしては妥当だが、`app.runtime` package内にあるため境界が曖昧
- Admin API ServiceがAdapter実装を直接newし、Streaming Plugin compositionを代行

確認できなかった問題:

- Domain→Adapter/Admin/FastAPI/PyQt6依存
- CoreのGoogle API/OBS WebSocket型import
- UI→Domain Repository直接依存
- 静的な複数module循環import（SCC 0件）

遅延importはRuntime packageのfactory facade等にあるが、今回の簡易AST SCC検査では循環は検出されなかった。

## 12. 責務集中箇所

1. `RuntimeCoordinator` 1,939行: Game routing、Activity execution、Stream wrapper、event loop、trace/result coordination。
2. `AdminApiService` 906行: DTO service、Composition Root、async task、Streaming orchestration、Capability policy。
3. `RuntimeFactory`: Adapter選択、Plugin/Game/Character/Streaming構築が集中。
4. `StreamPreparationWindow` 664行: 全状態表示、操作、retry payload組立、button policy。
5. `ActionPlanner`: Character generation fallback、game special case、stream special style、ActionPlan生成。

行数自体を削減目標にはせず、変更理由が異なる責務をFacade/Policy/Presenter単位で分離する。

## 13. Config棚卸し

`config.yaml`は179 leaf項目。Streamingは55、Games pluginは7。

| 区分 | 状況 |
|---|---|
| `streaming.readiness.*`, `streaming.obs.*`, `run_of_show.*` | 使用中 |
| `streaming.fake.*` | Fake/test modeおよび接続不能時の明示的Adapter選択に使用 |
| `streaming.moderation.*` | 使用中。ただし`url_policy`は現行ruleが固定reviewを返し、設定反映が不完全 |
| `streaming.comment_ranking.*` | 使用中。weight validationあり |
| `streaming.comment_response.*` | Prompt/style/retryに使用。ただし`response_cooldown_seconds`は実行時enforcement未接続、`max_sentences`は主にPrompt制約 |
| `plugins.games.*` | 使用中。Plugin on/offとintent/Shiritori設定 |
| YouTube/OBS secret | 値は調査対象外。設定はsecret referenceとして扱う |
| UI config | `streaming_admin.config`側。Core configと分離 |

`youtube`/`obs`はトップレベルではなくservice/plugin設定内に分散している。今後の整理では値を移す前にloader参照と環境変数名をCharacterizationする。

## 14. Test棚卸し

強い点:

- Start/Open/Main/End/Lifecycle/Poller/Moderation/Ranking/Responseのunit testがある。
- ActionSchedulerの同一resourceと同期Output Unitが保護されている。
- Claim validation、trace correlation、Admin API/UI境界が保護されている。
- Legacy marker adapterの存在とdeprecation一回通知が明示テストされている。

不足:

- Admin compositionを通した準備→開始→Opening→Main→Comment→Response→Endの単一統合テスト
- moderation handler未設定Runtimeと設定済みRuntimeでの`YOUTUBE_COMMENT`経路差
- Opening/Main eventをUsecase外から直接投入した際の拒否
- コメントResponse中のClosing/Emergency raceを実Runtime Scheduler込みで確認するテスト
- Streaming PluginをPlugin Managerからロードして縦経路Capabilityを解決するテスト

重複/過剰結合候補:

- RuntimeFactory/RuntimeCoordinator/Shiritori testが旧Game executionの具体的state構造を広範囲に固定
- UI testがWindow widget単位のbutton policyを直接固定
- Fakesがtest-localと`app.adapters.streaming`に分散

削除せず、まず縦経路integration testへ価値を集約する。

## 15. 削除・移動候補一覧

| 対象 | 現在の責務 / 参照元 | 代替経路 | 分類 | 根拠・リスク | 必要な回帰テスト | 順序 |
|---|---|---|---|---|---|---:|
| 明白な未参照本番module | なしと判断 | - | A | grepだけでなくentry point/import/testを確認した範囲で安全な候補なし | - | - |
| `app/ui/pyqt` shim | 旧起動名から新UIを案内 | `python -m streaming_admin` | B | 外部script利用はrepo内検索で判断不能 | launcher smoke | 8 |
| legacy marker adapter | 旧Plugin definition互換 | matcher契約 | B | testsとdeprecated fieldが現存 | plugin matcher parity | 7 |
| legacy constraint schema adapter | 旧schema互換 | strict schema | B | warning/testが現存 | schema parity | 7 |
| Streaming composition in Admin service | Usecase/Repo構築 | Streaming Runtime Facade/Plugin factory | C | AdminがPlugin実装を所有 | Admin API contract + vertical integration | 2 |
| in-memory Repo imports in Ranking Usecase | concrete persistence | Repository Ports | C | Usecase→Adapter逆依存 | ranking repository contract | 1 |
| YouTube error import in Poller | retry/error classification | Port-level neutral error | C | Usecase→YouTube Adapter逆依存 | poller transient/auth tests | 1 |
| Prompt concrete imports in Runtime | prompt construction | Prompt ports/factory injection | C | Core Runtime→Adapter concrete | character/claim prompt snapshots | 5 |
| Streaming Enum/branch in Core | stream-specific event/activity routing | plugin activity handler registry | C | 外部Plugin拡張を阻害 | all stream activity routing | 6 |
| direct `YOUTUBE_COMMENT` response | handler未構成時の会話化 | moderation/ranking/response | D | 新旧経路が構成依存で並存 | configured/unconfigured characterization | 3 |
| Main topic/autonomous selection | 次の話題決定 | shared talk arbitration policy | D | 複数責務が同じ発話資源を判断 | main/autonomous/comment arbitration | 6 |
| Core Shiritori + Games Plugin Shiritori | Game session/rules/execution | Games Plugin implementation | D | 二系統が存在しCore分岐が多い | full game continuity suite | 9 |
| `STREAM_STARTED` naming | Opening output event | explicit opening-output event | E | 実体はUsecaseのExecutorで重複発話ではない | opening event correlation | 5 |
| `app/adapters/streaming`配置 | Repo/Fake implementations | plugin adapters package | E | 機能は必要、所有packageが曖昧 | adapter contract | 4 |
| EventBuffer/Filter/Prioritizer | 共通input制御 | なし | F | Core共通責務 | existing event tests | 維持 |
| Character/Claim/Action pipeline | 共通出力安全経路 | なし | F | 全Activityが共有 | claim/output suite | 維持 |
| Platform Adapters | 外部接続 | Ports | F | 実/Fake双方に必要 | adapter unit tests | 維持 |
| Fake Adapters | test/test-mode | なし | F | RuntimeFactoryが明示利用 | factory no-real-connection | 維持 |
| legacy ResponseGenerator fallback | pipeline未構成時fallback | Character pipeline | G | production composition全形態の確認不足 | factory matrix | 5以降 |
| top-level config再配置 | 設定ownership | plugin-scoped config | G | deploy環境の外部参照不明 | config compatibility | 最後 |

## 16. リスク

- 旧コメント経路を先に削るとCore-only tests/利用者がコメントを処理できなくなる。
- Admin serviceからCompositionを移す際、async task lifetimeとSSE event順が変わりやすい。
- Streaming Event/Activityをregistry化するとLifecycle metadataがActionSchedulerへ届かない事故が起き得る。
- Shiritori移行はsession metadata、rollback、confirmation、ongoing activityを同時に壊す可能性が高い。
- Config移動は環境変数/secret referenceを壊す可能性がある。
- UI分割はbutton enable policyとstale state表示の不整合を起こしやすい。

## 17. 推奨整理順序

1. Comment Ranking/Response Repository Protocolを`app.ports`またはplugin-owned portへ移す。
2. Streaming vertical integration characterization testを追加する。
3. `StreamingRuntimeFacade`を作り、Admin serviceの構築・callback・status集約を移す。
4. `YOUTUBE_COMMENT`の旧直接応答を明示Feature Gate化し、productionでは新経路のみとする。
5. YouTube errorをPort-level neutral exceptionへ変換する。
6. Opening/Main/Comment/ClosingのRuntime wrapperをplugin handler registryまたはStreaming bridgeへ集約する。
7. Prompt builderをRuntimeへ注入し、Runtime→Adapter concrete importを減らす。
8. Admin WindowをPoller/Moderation/Ranking/Response presenter widgetへ分割する。
9. legacy matcher/schemaを利用Plugin確認後に個別廃止する。
10. Shiritoriを最後にPlugin実装へ一本化する。
11. launcher shim、import、configを最後に整理する。

各段階で「Characterization追加→呼出元移行→旧経路無効化→全回帰→削除」の順を守る。

## 18. 実施単位

- PR/変更単位1: Comment repository portsのみ
- 単位2: Vertical integration testのみ
- 単位3: StreamingRuntimeFacade導入、挙動不変
- 単位4: Comment legacy route feature gate
- 単位5: Poller error boundary
- 単位6: Runtime stream activity bridge
- 単位7: Prompt dependency injection
- 単位8: Admin UI presenter分割
- 単位9: Legacy marker/schema除去
- 単位10以降: Games migration

一度にファイル移動と挙動変更を混ぜない。

## 19. 回帰テスト計画

必須suite:

1. 既存全pytest
2. Start/Open/Main/End/Emergency/Lifecycle
3. Poller/Moderation/Ranking/Response
4. Character Claim validation
5. ActionScheduler resource/output ordering
6. Admin REST/SSE/UI
7. RuntimeFactory Fake/real-unavailable matrix
8. Games/Shiritori session continuity
9. Trace correlation/secret masking

追加Characterization:

- Admin-composed full vertical happy path
- 各external step failure後のSession/Activity/reservation状態
- unconfigured moderation handler時のcomment route
- duplicate/replayed EventとCommandのside-effect回数
- closing/emergency during moderation/ranking/LLM/output
- Streaming plugin unload/shutdown時のpoller/task停止

## 20. 判断保留事項

- repo外の利用者が旧`app.ui.pyqt` launcherを使っているか。
- legacy markerを提供する外部Plugin packageが存在するか。
- Character pipelineなしのproduction構成が正式サポート対象か。
- Streaming機能を単一Pluginとするか、platform-neutral streaming plugin + YouTube adapterに分割するか。
- Admin APIをStreaming Pluginの外側に置くか、plugin-provided routesを許すか。
- safe author display nameをCandidate contractへ追加するか。
- comment response cooldownをRanking、Reservation、Responseのどこで強制するか。

これらは削除・移動前に利用環境または設計判断が必要である。
