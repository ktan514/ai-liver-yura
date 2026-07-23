from __future__ import annotations

import argparse
import json
import math
import socket
import time
from datetime import datetime, timezone


MOODS = ("neutral", "happy", "excited", "tired", "sad")


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send simulated Yura state")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    started = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        try:
            while True:
                elapsed = time.monotonic() - started
                phase = elapsed * 0.18
                mood = MOODS[int(elapsed // 12) % len(MOODS)]
                state = {
                    "schema_version": 1,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "emotion": {
                        "mood": mood,
                        "arousal": clamp(0.5 + math.sin(phase * 1.7) * 0.42),
                        "valence": clamp(
                            math.sin(phase * 0.73), minimum=-1.0, maximum=1.0
                        ),
                        "talkativeness": clamp(
                            0.48 + math.cos(phase * 1.13) * 0.4
                        ),
                    },
                    "drive": {
                        "curiosity": clamp(0.62 + math.sin(phase * 0.91) * 0.3),
                        "engagement": clamp(0.55 + math.cos(phase * 0.67) * 0.34),
                        "boredom": clamp(0.25 + math.sin(phase * 0.41) * 0.22),
                        "energy": clamp(0.62 + math.cos(phase * 0.49) * 0.3),
                    },
                    "activity": {
                        "type": "idle_observation",
                        "active": False,
                        "pending_count": 0,
                    },
                    "attention": {"engaged": elapsed % 20 > 10},
                    "stream": {"status": "idle"},
                }
                sender.sendto(
                    json.dumps(state, separators=(",", ":")).encode(),
                    (args.host, args.port),
                )
                time.sleep(0.08)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
