# Streaming Admin 運用コンソール設計

Streaming Admin は配信制御を行うCore／UseCase／Adapterとは分離し、状態表示、操作要求、
確認ダイアログ、診断情報の保存を担当する。外部通信はControllerのworker poolで実行し、
WidgetからAdapterを直接呼び出さない。

## 状態取得と更新

- 初期表示と再接続時はRESTの`/api/v1/admin/console`から集約状態を取得する。
- 実行中の変化はSSEを契機にRESTで再同期する。OBSとYouTubeは手動更新も提供する。
- Service statusは`update_mode`、`last_updated_at`、`freshness`を持つ。鮮度は取得時刻と
  設定されたstale閾値からCore側で算出する。
- OBSの状態更新とAdapter再接続は別の操作として表示する。未提供の再接続capabilityは
  無効理由を表示する。

## Adapter capabilityと人間操作

`streaming_capabilities`は公開開始・終了の自動実行、Studio URL、状態確認、確認要否を表す。
UIはAdapter名から人間操作を推測しない。現在のGoogle/Fake control adapterはいずれも公開
遷移を自動実行でき、Fake構成ではStudio操作を要求しない。将来の手動Adapterは同じDTOで
`operator_action`を返す。

`operator_action`は`none`、`youtube_start_required`、`youtube_stop_required`、
`authentication_required`、`obs_confirmation_required`、`recovery_decision_required`を扱い、
状態は`not_required`、`waiting`、`acknowledged`、`completed`、`expired`とする。

## 診断とログ

Coreはファイルログの有効状態に関係なく、イベント、状態遷移、管理操作、失敗を最大500件の
リングバッファへ保持する。診断スナップショットにはruntime、Adapter、直近イベント、エラー、
設定要約を含める。画面の「表示をクリア」はTable modelのみを消去し、Coreのリングバッファや
ファイルを変更しない。

実行時設定APIはログレベル、ファイル出力、保存先、ローテーション、リングバッファ件数、
OBS／YouTube更新間隔、stale閾値、操作待ちダイアログを受け付ける。設定変更は監査イベントに
記録され、配信ライフサイクルを停止しない。

## 画面

タブは「概要」「コメント」「配信進行」「診断・ログ」「設定」とする。概要には現在状態、次の
操作、サービスカード、工程、操作分担を表示する。コメント、Timeline、診断ログはQTableViewと
bounded modelを使用し、選択行の技術詳細を別ペインに表示する。緊急停止と工程スキップは必ず
確認ダイアログを経由する。

### 初期サイズと設定配置

初期ウィンドウサイズは、旧上限（1280×900または利用可能領域の94%）から算出したサイズの
68%を基準とする。最小サイズは720×480とし、低解像度では利用可能領域を超えない値まで
縮小する。サイズ復元や自動最大化は行わず、通常の最大化と手動リサイズは維持する。

設定タブは左上を起点とする3列のグリッドとし、1行目に「ログ設定」「OBS更新設定」
「YouTube更新設定」、2行目に3列を横断する「操作・診断設定」を配置する。各グループ内は
QFormLayoutを使用し、適用ボタンと結果表示はグリッドの下に独立して配置する。

概要タブと設定タブの本文は、タブバーや上部の主要操作を固定したまま縦方向へスクロールできる
QScrollAreaで包む。横スクロールは無効とし、幅が820px未満では概要カードを1列、幅が1000px
未満では設定グループを2列へリフローする。カードは内容を1行以上読める最小高さ、TableViewは
ヘッダーと3行を表示できる最小高さをDPI・フォント由来のsizeHintから確保する。メインLayoutは
上部領域へstretchを与えず、タブ領域へstretch 1を割り当てる。
