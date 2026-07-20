import asyncio

import pytest

from app.domain.actions import ActionPlan, ActionType
from app.domain.character_response import VoiceIntent
from app.domain.events import AgentEvent, AgentEventType
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicCategory, TopicHistory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry
from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.usecases import ExecuteActionUsecase


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published_events: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.published_events.append(event)


class FakeSpeechSynthesizer:
    def __init__(self, audio_data: bytes = b"RIFF-test-wav") -> None:
        self.audio_data = audio_data
        self.received_texts: list[str] = []
        self.received_voice_intent: VoiceIntent | None = None

    async def synthesize(
        self, text: str, voice_intent: VoiceIntent | None = None
    ) -> bytes:
        self.received_texts.append(text)
        self.received_voice_intent = voice_intent
        return self.audio_data


class FakeAudioPlayer:
    def __init__(self) -> None:
        self.received_audio: list[bytes] = []

    async def play(self, audio_data: bytes) -> None:
        self.received_audio.append(audio_data)


class FailingSpeechSynthesizer:
    async def synthesize(
        self, text: str, voice_intent: VoiceIntent | None = None
    ) -> bytes:
        raise RuntimeError("VOICEVOX unavailable")


# FakeTopicClassifier for testing topic classification and history recording
class FakeTopicClassifier:
    def __init__(self, category: TopicCategory) -> None:
        self.category = category
        self.classified_texts: list[str] = []

    async def classify(self, text: str) -> TopicCategory:
        self.classified_texts.append(text)
        return self.category


class BlockingTopicClassifier(FakeTopicClassifier):
    def __init__(self, category: TopicCategory) -> None:
        super().__init__(category)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def classify(self, text: str) -> TopicCategory:
        self.started.set()
        await self.release.wait()
        return await super().classify(text)


# FakeEmbeddingGenerator and FakeTopicMemoryStore for topic memory tests


class FakeEmbeddingGenerator:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding
        self.received_texts: list[str] = []

    async def generate_embedding(self, text: str) -> list[float]:
        self.received_texts.append(text)
        return self.embedding


class FakeMemorySummaryGenerator(MemorySummaryGenerator):
    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.received_texts: list[str] = []

    async def generate_summary(self, text: str) -> str:
        self.received_texts.append(text)
        return self.summary


class FakeTopicMemoryStore:
    def __init__(self) -> None:
        self.saved_entries: list[TopicMemoryEntry] = []

    async def save(self, entry: TopicMemoryEntry) -> None:
        self.saved_entries.append(entry)

    async def fetch_recent(self, limit: int = 10) -> list[TopicMemoryEntry]:
        return []

    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[SimilarTopicMemory]:
        return []


@pytest.mark.asyncio
async def test_speak_action_publishes_speech_started_and_finished_events() -> None:
    event_publisher = FakeEventPublisher()
    usecase = ExecuteActionUsecase(event_publisher=event_publisher)
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="こんにちは",
        source_activity_id="activity-1",
        output_unit_id="output-1",
    )

    await usecase.execute(action_plan)

    assert [event.event_type for event in event_publisher.published_events] == [
        AgentEventType.SPEECH_STARTED,
        AgentEventType.SPEECH_FINISHED,
    ]
    assert event_publisher.published_events[0].payload == {
        "action_id": action_plan.action_id,
        "source_activity_id": "activity-1",
        "output_unit_id": "output-1",
        "text": "こんにちは",
    }
    assert event_publisher.published_events[1].payload == {
        "action_id": action_plan.action_id,
        "source_activity_id": "activity-1",
        "output_unit_id": "output-1",
        "text": "こんにちは",
    }


@pytest.mark.asyncio
async def test_speak_action_without_event_publisher_does_not_raise_error() -> None:
    usecase = ExecuteActionUsecase()
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="こんにちは",
    )

    await usecase.execute(action_plan)


@pytest.mark.asyncio
async def test_speak_action_synthesizes_and_plays_audio() -> None:
    synthesizer = FakeSpeechSynthesizer()
    player = FakeAudioPlayer()
    usecase = ExecuteActionUsecase(
        speech_synthesizer=synthesizer,
        audio_player=player,
    )
    intent = VoiceIntent(style="excited")
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="こんにちは",
        metadata={"voice_intent": intent},
    )

    await usecase.execute(action_plan)

    assert synthesizer.received_texts == ["こんにちは"]
    assert synthesizer.received_voice_intent == intent
    assert player.received_audio == [b"RIFF-test-wav"]


@pytest.mark.asyncio
async def test_speak_keeps_original_text_for_display_and_memory(capsys) -> None:
    synthesizer = FakeSpeechSynthesizer()
    memory = ShortTermMemory()
    usecase = ExecuteActionUsecase(
        short_term_memory=memory,
        speech_synthesizer=synthesizer,
        audio_player=FakeAudioPlayer(),
    )

    await usecase.execute(
        ActionPlan(action_type=ActionType.SPEAK, text="どんな風に話せばいいかな")
    )

    assert "[speak] どんな風に話せばいいかな" in capsys.readouterr().out
    assert synthesizer.received_texts == ["どんな風に話せばいいかな"]
    assert memory.recent_speeches()[0].text == "どんな風に話せばいいかな"


@pytest.mark.asyncio
async def test_speak_action_falls_back_when_synthesis_fails(monkeypatch) -> None:
    sleep_durations: list[float] = []
    memory = ShortTermMemory()
    topic_history = TopicHistory()
    classifier = FakeTopicClassifier(category=TopicCategory.SEA_LIFE)

    async def fake_sleep(duration: float) -> None:
        sleep_durations.append(duration)

    monkeypatch.setattr("app.usecases.execute_action_usecase.asyncio.sleep", fake_sleep)
    usecase = ExecuteActionUsecase(
        short_term_memory=memory,
        topic_history=topic_history,
        topic_classifier=classifier,
        speech_synthesizer=FailingSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
    )

    await usecase.execute(ActionPlan(action_type=ActionType.SPEAK, text="こんにちは"))

    assert sleep_durations == [1.0]
    assert memory.recent_speeches() == []
    assert topic_history.recent_entries() == []
    assert classifier.classified_texts == []


# Test: SPEAK action records topic history when classifier is set
@pytest.mark.asyncio
async def test_speak_action_records_topic_history_when_classifier_is_set() -> None:
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.SEA_LIFE)
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
    )
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="透明な体でゆらゆら漂う生き物って不思議だよね。",
        source_activity_id="activity-1",
    )

    await usecase.execute(action_plan)

    entries = topic_history.recent_entries()
    assert topic_classifier.classified_texts == [
        "透明な体でゆらゆら漂う生き物って不思議だよね。"
    ]
    assert len(entries) == 1
    assert entries[0].category == TopicCategory.SEA_LIFE
    assert entries[0].summary == "透明な体でゆらゆら漂う生き物って不思議だよね。"
    assert entries[0].source_text == "透明な体でゆらゆら漂う生き物って不思議だよね。"
    assert entries[0].activity_type == ActionType.SPEAK.value


@pytest.mark.asyncio
async def test_speak_can_record_topic_memory_outside_output_critical_path() -> None:
    topic_history = TopicHistory()
    classifier = BlockingTopicClassifier(TopicCategory.SEA_LIFE)
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=classifier,
        speech_synthesizer=FakeSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
        background_topic_memory=True,
    )

    await usecase.execute(
        ActionPlan(action_type=ActionType.SPEAK, text="クラゲの話")
    )
    await asyncio.wait_for(classifier.started.wait(), timeout=1.0)

    assert usecase.pending_background_task_count == 1
    assert topic_history.recent_entries() == []

    classifier.release.set()
    for _ in range(10):
        if usecase.pending_background_task_count == 0:
            break
        await asyncio.sleep(0)

    assert usecase.pending_background_task_count == 0
    assert topic_history.recent_entries()[0].category == TopicCategory.SEA_LIFE


@pytest.mark.asyncio
async def test_game_speech_does_not_record_topic_history_or_memory() -> None:
    topic_history = TopicHistory()
    classifier = FakeTopicClassifier(TopicCategory.OTHER)
    embedding_generator = FakeEmbeddingGenerator([0.1])
    store = FakeTopicMemoryStore()
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=store,
        speech_synthesizer=FakeSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
    )

    await usecase.execute(
        ActionPlan(
            action_type=ActionType.SPEAK,
            text="『たこ』！",
            metadata={"skip_topic_memory": True},
        )
    )

    assert classifier.classified_texts == []
    assert topic_history.recent_entries() == []
    assert embedding_generator.received_texts == []
    assert store.saved_entries == []


# Test: SPEAK action records topic memory when embedding and store are set
@pytest.mark.asyncio
async def test_speak_action_records_topic_memory_when_embedding_and_store_are_set() -> (
    None
):
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.NATURE)
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore()
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="海の色は時間や天気で変わるのが面白いよね。",
        source_activity_id="activity-1",
    )

    await usecase.execute(action_plan)

    assert embedding_generator.received_texts == [
        "海の色は時間や天気で変わるのが面白いよね。"
    ]
    assert len(topic_memory_store.saved_entries) == 1
    saved_entry = topic_memory_store.saved_entries[0]
    assert saved_entry.category == TopicCategory.NATURE
    assert saved_entry.summary == "海の色は時間や天気で変わるのが面白いよね。"
    assert saved_entry.source_text == "海の色は時間や天気で変わるのが面白いよね。"
    assert saved_entry.activity_type == ActionType.SPEAK.value
    assert saved_entry.embedding == [0.1, 0.2, 0.3]
    assert saved_entry.source_activity_id == "activity-1"


# Test: SPEAK action does not record topic memory when embedding generator is not set
@pytest.mark.asyncio
async def test_speak_action_does_not_record_topic_memory_when_embedding_generator_is_not_set() -> (
    None
):
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.NATURE)
    topic_memory_store = FakeTopicMemoryStore()
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        topic_memory_store=topic_memory_store,
    )
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="海の色の話。",
    )

    await usecase.execute(action_plan)

    assert topic_memory_store.saved_entries == []


# Test: SPEAK action does not record topic memory when embedding is empty
@pytest.mark.asyncio
async def test_speak_action_does_not_record_topic_memory_when_embedding_is_empty() -> (
    None
):
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.NATURE)
    embedding_generator = FakeEmbeddingGenerator(embedding=[])
    topic_memory_store = FakeTopicMemoryStore()
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
    )
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="海の色の話。",
    )

    await usecase.execute(action_plan)

    assert embedding_generator.received_texts == ["海の色の話。"]
    assert topic_memory_store.saved_entries == []


# Test: SPEAK action does not record topic history when classifier is not set
@pytest.mark.asyncio
async def test_speak_action_does_not_record_topic_history_when_classifier_is_not_set() -> (
    None
):
    topic_history = TopicHistory()
    usecase = ExecuteActionUsecase(topic_history=topic_history)
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="こんにちは",
    )

    await usecase.execute(action_plan)

    assert topic_history.recent_entries() == []


# Test: SPEAK action records topic memory with generated summary


@pytest.mark.asyncio
async def test_speak_action_records_topic_memory_with_generated_summary() -> None:
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.SEA_LIFE)
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore()
    memory_summary_generator = FakeMemorySummaryGenerator(
        summary="クラゲ展示がきれいだった記憶"
    )
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
        memory_summary_generator=memory_summary_generator,
    )
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="今日は眠いけど、前に見たクラゲ展示がきれいだった",
        source_activity_id="activity-1",
    )

    await usecase.execute(action_plan)

    assert memory_summary_generator.received_texts == [
        "今日は眠いけど、前に見たクラゲ展示がきれいだった"
    ]
    assert embedding_generator.received_texts == ["クラゲ展示がきれいだった記憶"]
    assert len(topic_memory_store.saved_entries) == 1
    saved_entry = topic_memory_store.saved_entries[0]
    assert saved_entry.category == TopicCategory.SEA_LIFE
    assert saved_entry.summary == "クラゲ展示がきれいだった記憶"
    assert saved_entry.source_text == "今日は眠いけど、前に見たクラゲ展示がきれいだった"
    assert saved_entry.embedding == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_speak_action_uses_original_text_when_generated_summary_is_empty() -> (
    None
):
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.SEA_LIFE)
    embedding_generator = FakeEmbeddingGenerator(embedding=[0.1, 0.2, 0.3])
    topic_memory_store = FakeTopicMemoryStore()
    memory_summary_generator = FakeMemorySummaryGenerator(summary="   ")
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=topic_memory_store,
        memory_summary_generator=memory_summary_generator,
    )
    action_plan = ActionPlan(
        action_type=ActionType.SPEAK,
        text="クラゲの話をした",
    )

    await usecase.execute(action_plan)

    assert memory_summary_generator.received_texts == ["クラゲの話をした"]
    assert embedding_generator.received_texts == ["クラゲの話をした"]
    assert topic_memory_store.saved_entries[0].summary == "クラゲの話をした"
    assert topic_memory_store.saved_entries[0].source_text == "クラゲの話をした"


# Test: Non-SPEAK action does not record topic history
@pytest.mark.asyncio
async def test_non_speak_action_does_not_record_topic_history() -> None:
    topic_history = TopicHistory()
    topic_classifier = FakeTopicClassifier(category=TopicCategory.STREAMING)
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=topic_classifier,
    )
    action_plan = ActionPlan(
        action_type=ActionType.UPDATE_SUBTITLE,
        text="字幕です",
    )

    await usecase.execute(action_plan)

    assert topic_classifier.classified_texts == []
    assert topic_history.recent_entries() == []


@pytest.mark.asyncio
async def test_non_speak_action_does_not_publish_speech_events() -> None:
    event_publisher = FakeEventPublisher()
    usecase = ExecuteActionUsecase(event_publisher=event_publisher)
    action_plan = ActionPlan(
        action_type=ActionType.UPDATE_SUBTITLE,
        text="字幕です",
    )

    await usecase.execute(action_plan)

    assert event_publisher.published_events == []
