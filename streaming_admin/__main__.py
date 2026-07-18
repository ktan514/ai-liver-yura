from __future__ import annotations

import sys
import threading

from PyQt6.QtWidgets import QApplication

from streaming_admin.client import CoreApiClient, EventStreamClient
from streaming_admin.config import AdminClientConfig
from streaming_admin.ui import StreamPreparationController, StreamPreparationWindow


def main() -> int:
    app = QApplication(sys.argv)
    config = AdminClientConfig.from_environment()
    controller = StreamPreparationController(CoreApiClient(config))
    events = EventStreamClient(config)
    controller.add_shutdown_callback(events.stop)
    thread = threading.Thread(
        target=events.run,
        args=(controller.handle_event, controller.core_connection_changed),
        name="core-event-stream",
        daemon=True,
    )
    thread.start()
    window = StreamPreparationWindow(controller)
    window.show()
    result = app.exec()
    controller.close()
    thread.join(timeout=config.timeout_seconds + 1)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
