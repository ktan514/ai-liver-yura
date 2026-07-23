from __future__ import annotations

import json
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from server import AudioStore, EventHub, handler_for


class ServerIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.input_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.input_socket.bind(("127.0.0.1", 0))
        self.input_socket.settimeout(2)
        input_port = int(self.input_socket.getsockname()[1])
        self.hub = EventHub()
        self.audio_store = AudioStore()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler_for(self.hub, self.audio_store, "127.0.0.1", input_port, 2),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.input_socket.close()

    def post(self, path: str, body: bytes, content_type: str) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read())

    def test_input_output_and_audio_completion(self) -> None:
        with urlopen(f"{self.base_url}/", timeout=2) as response:
            self.assertIn(b"YURA / CONVERSATION", response.read())

        accepted = self.post(
            "/api/input",
            json.dumps({"text": "こんにちは"}, ensure_ascii=False).encode(),
            "application/json",
        )
        self.assertEqual(accepted["status"], "accepted")
        packet, _ = self.input_socket.recvfrom(4096)
        self.assertEqual(json.loads(packet)["text"], "こんにちは")

        self.post(
            "/api/output",
            json.dumps({"text": "やっほー", "kind": "speak"}, ensure_ascii=False).encode(),
            "application/json",
        )
        with urlopen(f"{self.base_url}/api/history", timeout=2) as response:
            history = json.loads(response.read())
        self.assertEqual([item["text"] for item in history["messages"]], ["こんにちは", "やっほー"])

        sequence, _ = self.hub.snapshot()
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self.post,
                "/api/audio",
                b"RIFF-test-wav",
                "audio/wav",
            )
            _, events = self.hub.wait_after(sequence, 2)
            audio = next(event for event in events if event["type"] == "audio")
            with urlopen(f"{self.base_url}{audio['url']}", timeout=2) as response:
                self.assertEqual(response.read(), b"RIFF-test-wav")
            self.post(
                f"/api/audio/{audio['audio_id']}/complete",
                b'{"status":"completed"}',
                "application/json",
            )
            self.assertEqual(pending.result(timeout=2)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
