#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="${1:-ai-liver}"

echo "Initialize project: ${PROJECT_NAME}"

mkdir -p "${PROJECT_NAME}"
cd "${PROJECT_NAME}"

# ============================================================
# Directories
# ============================================================

mkdir -p \
  app/config \
  app/domain/events \
  app/domain/activities \
  app/domain/actions \
  app/domain/emotions \
  app/domain/memory \
  app/runtime \
  app/usecases \
  app/adapters/llm \
  app/adapters/tts \
  app/adapters/stt \
  app/adapters/obs \
  app/adapters/youtube \
  app/adapters/live2d \
  app/ui/pyqt \
  app/infrastructure/storage \
  docs \
  tests

# ============================================================
# Python package marker files
# ============================================================

touch app/__init__.py
touch app/config/__init__.py

touch app/domain/__init__.py
touch app/domain/events/__init__.py
touch app/domain/activities/__init__.py
touch app/domain/actions/__init__.py
touch app/domain/emotions/__init__.py
touch app/domain/memory/__init__.py

touch app/runtime/__init__.py
touch app/usecases/__init__.py

touch app/adapters/__init__.py
touch app/adapters/llm/__init__.py
touch app/adapters/tts/__init__.py
touch app/adapters/stt/__init__.py
touch app/adapters/obs/__init__.py
touch app/adapters/youtube/__init__.py
touch app/adapters/live2d/__init__.py

touch app/ui/__init__.py
touch app/ui/pyqt/__init__.py

touch app/infrastructure/__init__.py
touch app/infrastructure/storage/__init__.py

touch tests/__init__.py

# ============================================================
# app/__main__.py
# Create only if it does not exist
# ============================================================

if [ ! -f app/__main__.py ]; then
  cat > app/__main__.py <<'EOF'
def main() -> None:
    print("AI Liver runtime starting...")


if __name__ == "__main__":
    main()
EOF
fi

# ============================================================
# README.md
# Create only if it does not exist
# ============================================================

if [ ! -f README.md ]; then
  cat > README.md <<'EOF'
# AI Liver

Activity-driven modular AI liver agent.

## Runtime

- Python 3.10.5
- PyQt6

## Architecture

This project uses an activity-driven modular agent architecture.

Core concepts:

- Event
- Activity
- Action
- Activity Runtime
- Event Queue
- Activity Manager
- Action Planner
- Channel Executors
- Ports & Adapters
EOF
fi

# ============================================================
# requirements.txt
# Create only if it does not exist
# ============================================================

if [ ! -f requirements.txt ]; then
  cat > requirements.txt <<'EOF'
PyQt6
python-dotenv
PyYAML
pydantic
EOF
fi

# ============================================================
# requirements-dev.txt
# Create only if it does not exist
# ============================================================

if [ ! -f requirements-dev.txt ]; then
  cat > requirements-dev.txt <<'EOF'
pytest
ruff
mypy
types-PyYAML
EOF
fi

# ============================================================
# pyproject.toml
# Create only if it does not exist
# ============================================================

if [ ! -f pyproject.toml ]; then
  cat > pyproject.toml <<'EOF'
[project]
name = "ai-liver"
version = "0.1.0"
description = "Activity-driven modular AI liver agent"
requires-python = ">=3.10,<3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.10"
strict = true
mypy_path = "."
EOF
fi

# ============================================================
# .gitignore
# Create only if it does not exist
# ============================================================

if [ ! -f .gitignore ]; then
  cat > .gitignore <<'EOF'
# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd

# Virtual environment
.venv/
venv/

# Environment
.env

# IDE
.vscode/
.idea/

# OS
.DS_Store

# Logs
logs/
*.log

# Test / type check
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Build
build/
dist/
*.egg-info/
EOF
fi

echo "Project structure initialized."

echo ""
echo "Next steps:"
echo "  cd ${PROJECT_NAME}"
echo "  pyenv local 3.10.5"
echo "  python -m venv .venv"
echo "  source .venv/bin/activate"
echo "  python -m pip install --upgrade pip setuptools wheel"
echo "  pip install -r requirements.txt"
echo "  pip install -r requirements-dev.txt"
echo "  python -m app"
