# 継続的インテグレーション方針

## 1. 目的

GitHub Actions を利用し、Pull Request 単位で Python テストを自動実行する。
不具合を main へ取り込む前に検出しつつ、GitHub Actions の無料枠を不要に消費しない構成とする。

## 2. 対象環境

- Python: 3.10.5
- 依存管理: Pipfile / Pipfile.lock
- テストランナー: pytest
- 実行OS: ubuntu-latest

`pyproject.toml` の Python 制約および pytest 設定を正とし、CI固有のテスト対象は定義しない。
ローカルとCIは、どちらもリポジトリ直下から `python -m pytest` を実行する。

## 3. 起動条件

Workflow は次の条件で起動する。

- Pull Request の作成・更新
- main ブランチへの push
- GitHub画面からの手動実行

作業ブランチへの通常 push だけでは起動しない。
Pull Request を作成した段階から自動検証を開始する。

## 4. 無料枠を保護する制御

- Pythonバージョンのマトリクス実行は行わず、プロジェクト標準の3.10.5だけを検証する
- 同一ブランチで新しい実行が始まった場合、古い実行を自動キャンセルする
- 1ジョブの上限を15分とし、ハング時の消費を抑える
- Pipfile.lockをキーとしてpipキャッシュを利用する
- Workflowの権限はリポジトリ内容の読み取りだけに限定する

## 5. 依存関係の再現性

CIでは `pipenv sync --dev --system` を使用し、Pipfile.lock に固定された通常依存・開発依存を導入する。
Pipfile.lock と Pipfile の不整合や、固定済み依存を導入できない状態はテスト前に失敗させる。

## 6. 判定

次のいずれかに該当した場合、Workflowを失敗とする。

- Pythonまたは依存関係を準備できない
- pytestの収集に失敗する
- 1件以上のテストが失敗する
- 15分以内に処理が完了しない

外部サービスへ接続する実環境テストは標準Workflowへ含めず、Adapterを差し替えた単体・結合テストを基本とする。
実サービスを必要とする検証は、Secretsと実行条件を分離した専用Workflowとして追加する。

## 7. Workflow配置

- `.github/workflows/python-tests.yml`

Workflow名は `Python tests`、ジョブ名は `pytest (Python 3.10.5)` とする。
