from __future__ import annotations

from app.domain.topic_memory import SimilarTopicMemory


class TopicMemoryPromptSection:
    def build(self, similar_topic_memories: list[SimilarTopicMemory]) -> str:
        if not similar_topic_memories:
            return ""

        sorted_memories = sorted(
            similar_topic_memories,
            key=lambda similar_topic_memory: similar_topic_memory.similarity,
            reverse=True,
        )

        lines = ["# 関連する過去の記憶"]
        for similar_topic_memory in sorted_memories:
            entry = similar_topic_memory.entry
            lines.append(f"- {entry.category.value}: {entry.summary}")

        return "\n".join(lines)
