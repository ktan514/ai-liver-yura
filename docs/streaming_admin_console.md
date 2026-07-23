# Streaming Admin Web運用コンソール

Coreを起動したあと、リポジトリ直下で次を実行し、
<http://127.0.0.1:8780> をブラウザで開く。

```bash
.venv/bin/python gui/yura-streaming-admin/server.py
```

待受ポートは `--port` で変更できる。Core APIの接続先、トークン、タイムアウト、操作者名は
`AI_LIVER_ADMIN_API_URL`、`AI_LIVER_ADMIN_API_TOKEN`、
`AI_LIVER_ADMIN_API_TIMEOUT`、`AI_LIVER_ADMIN_OPERATOR` で指定する。

Streaming Admin は配信制御を行うCore／UseCase／Adapterとは分離し、状態表示、操作要求、
確認ダイアログ、診断情報の保存を担当する。ブラウザは同一オリジンのローカルWebサーバーとのみ
通信し、Core APIトークンを受け取らない。画面からAdapterを直接呼び出さない。

## 状態取得と更新

- 初期表示と再接続時はRESTの`/api/v1/admin/console`から集約状態を取得する。
- 実行中の変化はSSEを契機にRESTで再同期する。OBSとYouTubeは手動更新も提供する。
- Service statusは`update_mode`、`last_updated_at`、`freshness`を持つ。鮮度は取得時刻と設定されたstale閾値からCore側で算出する。
- OBSの状態更新とAdapter再接続は別の操作として表示する。未提供の再接続capabilityは無効理由を表示する。

## Adapter capabilityと人間操作

`streaming_capabilities`は公開開始・終了の自動実行、Studio URL、状態確認、確認要否を表す。
UIはAdapter名から人間操作を推測しない。現在のGoogle/Fake control adapterはいずれも公開遷移を
自動実行でき、Fake構成ではStudio操作を要求しない。将来の手動Adapterは同じDTOで
`operator_action`を返す。

`operator_action`は`none`、`youtube_start_required`、`youtube_stop_required`、
`authentication_required`、`obs_confirmation_required`、`recovery_decision_required`を扱い、
状態は`not_required`、`waiting`、`acknowledged`、`completed`、`expired`とする。

## 診断とログ

Coreはファイルログの有効状態に関係なく、イベント、状態遷移、管理操作、失敗を最大500件の
リングバッファへ保持する。診断スナップショットにはruntime、Adapter、直近イベント、エラー、
設定要約を含める。画面の「表示をクリア」はブラウザ上の表示のみを消去し、Coreのリングバッファや
ファイルを変更しない。

実行時設定APIはログレベル、ファイル出力、保存先、ローテーション、リングバッファ件数、
OBS／YouTube更新間隔、stale閾値、操作待ちダイアログを受け付ける。設定変更は監査イベントに
記録され、配信ライフサイクルを停止しない。

## 画面コンセプト

Streaming Adminは「海上に浮かぶ管制塔」をモチーフとする。他の深海・海中画面とは区別し、
空、水平線、海面、防潮ガラス、航海計器、信号灯を連想させる外観とする。背景装飾よりも運用時の
可読性を優先し、水色、白、淡い琥珀色を通常状態のアクセント、赤を警告と緊急操作に使用する。

画面名「配信の灯台」は維持し、配信・OBS・YouTube・コメント・進行状況を監視して必要な指示を
出す海上管制塔として位置づける。

## 画面構成

タブは「概要」「コメント」「配信進行」「診断・ログ」「設定」とする。

画面上部は次の順序で構成する。

1. 固定ヘッダー
   - 画面名
   - Core接続状態
   - 緊急停止
2. 現在状態と次の推奨操作
   - 現在状態と説明を表示する。
   - 認証、準備、開始、通常終了のうち現在実行可能な主要操作を1件だけ強調表示する。
   - 配信開始、通常終了、緊急停止は確認ダイアログを経由する。
3. 配信設定
   - 配信枠と進行表を選択する。
   - 配信枠一覧の再取得を選択欄の近くに配置する。
   - YouTube認証を配信準備操作として配置する。
4. 必要な人間操作
   - `operator_action`の案内とYouTube Studioへの導線を表示する。

概要タブにはサービスカード、復旧操作、操作分担を表示する。

- Core、OBS、YouTube、配信進行をサービスカードとして表示する。
- OBSとYouTubeの手動更新は各サービスカード内に配置する。
- Opening、Main、コメント応答の再試行は、再試行可能な失敗が発生した場合だけ復旧カードとして表示する。
- 操作分担は折りたたみ表示とし、通常監視時の情報量を抑える。
- 安全なcapabilityが未提供の工程スキップは画面に表示しない。

コメント、Timeline、診断ログはスクロール可能なテーブルまたは一覧として表示する。

## レスポンシブ表示と設定配置

画面はブラウザの表示領域に追従する。900px以下ではカードを2列、620px以下では1列へ
リフローし、テーブルは必要に応じて横スクロールする。

設定タブは左上を起点とする3列のグリッドとし、1行目に「ログ設定」「OBS更新設定」
「YouTube更新設定」、2行目に3列を横断する「操作・診断設定」を配置する。適用ボタンは
グリッドの下に配置する。狭い画面では2列、1列へ順にリフローする。

固定ヘッダーにはCore接続状態と緊急停止を配置する。タブもヘッダー直下で固定し、長い一覧を
スクロールしている間も画面切替と緊急操作へ到達できるようにする。
