# Python実行環境

このプロジェクトでは、プロジェクト直下の `.venv` を使用する。

Python関連のコマンドを実行するときは、システムの `python`、`pip`、
`pytest` を使用せず、必ず以下を使用すること。

- Python: `.venv/bin/python`
- pip: `.venv/bin/python -m pip`
- pytest: `.venv/bin/python -m pytest`
- Ruff: `.venv/bin/python -m ruff`
- mypy: `.venv/bin/python -m mypy`

例:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pip install <package>
.venv/bin/python app/__main__.py

.envは機密情報(API KEY、パスワードなど)を記載しているので読み取ったり、内容を表示したりしないでください。
