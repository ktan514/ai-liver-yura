from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from app.config.app_config import load_app_config
from app.runtime.runtime_factory import create_stream_preparation_runtime
from app.ui.pyqt import (
    RuntimeCommandGateway,
    StreamPreparationController,
    StreamPreparationWindow,
)


def main() -> int:
    app = QApplication(sys.argv)
    runtime = create_stream_preparation_runtime(load_app_config())
    gateway = RuntimeCommandGateway(runtime.usecase)
    controller = StreamPreparationController(gateway)
    window = StreamPreparationWindow(controller)
    window.resize(1100, 700)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
