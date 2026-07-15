from __future__ import annotations

from app.domain.autonomous_planning import (
    AutonomousSituationAnalysis,
    AutonomousSituationContext,
)
from app.utils.trace import TraceLogger


class AutonomousSituationEvaluator:
    """内的状態を発話本文を伴わない自律行動候補へ正規化する。"""

    def evaluate(self, context: AutonomousSituationContext) -> AutonomousSituationAnalysis:
        event = context.event_context
        continuation = str(event.get("continuation_decision") or "")
        selected_topic = str(event.get("selected_topic") or "").strip()
        interrupted = context.interrupted_topic
        interrupted_text = (
            str(interrupted.get("original_text") or "").strip() if interrupted is not None else ""
        )
        if continuation in {"resume_original", "resume_with_reframing"}:
            action = "topic_continue"
            relation = continuation
            topic = selected_topic or interrupted_text
        elif continuation in {
            "branch_from_original",
            "branch_from_interruption",
            "start_new_topic",
        }:
            action = "topic_shift"
            relation = continuation
            topic = selected_topic
        else:
            action = "autonomous_talk"
            relation = "none"
            topic = selected_topic

        if not topic:
            drive = max(
                context.drive_state,
                key=lambda name: context.drive_state[name],
                default="curiosity",
            )
            topic = {
                "curiosity": "いま気になっていること",
                "engagement": "この配信でこれから話したいこと",
                "boredom": "気分転換に考えてみたいこと",
                "energy": "いまの気分",
            }.get(drive, "いま気になっていること")
        analysis = AutonomousSituationAnalysis(
            suggested_action=action,
            topic_candidate=topic,
            planning_reason=str(event.get("reason") or "internal_drive"),
            relation_to_interrupted_topic=relation,
            constraints={
                "max_length": "short",
                "avoid_repetition": True,
                "do_not_claim_external_execution": True,
            },
        )
        TraceLogger().debug(
            "autonomous_situation_evaluator:evaluated",
            **(context.trace_context.as_log_fields() if context.trace_context else {}),
            component_role="autonomous_situation_evaluator",
            suggested_action=analysis.suggested_action,
            topic_candidate=analysis.topic_candidate,
        )
        return analysis
