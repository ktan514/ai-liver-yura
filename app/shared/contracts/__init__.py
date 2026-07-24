"""実装へ依存しないShared Contracts。"""

from app.shared.contracts.expression import VoiceIntent
from app.shared.contracts.memory import (
    AgentMemorySnapshot,
    AgentMemoryStore,
    EmotionHistoryRecord,
    EpisodicMemoryRecord,
    SemanticMemoryRecord,
    SnapshotStore,
    UnfinishedActivityRecord,
    UnrecoveredTopicRecord,
)
from app.shared.contracts.output import AudioPlayer, SpeechSynthesizer

__all__ = [
    "AgentMemorySnapshot",
    "AgentMemoryStore",
    "EmotionHistoryRecord",
    "EpisodicMemoryRecord",
    "SemanticMemoryRecord",
    "SnapshotStore",
    "UnfinishedActivityRecord",
    "UnrecoveredTopicRecord",
    "AudioPlayer",
    "SpeechSynthesizer",
    "VoiceIntent",
]
