from __future__ import annotations

import json

from app.domain.behavior import BehaviorPlanningContext


class SituationEvaluatorPromptBuilder:
    """客観的意味解析だけを要求するrole専用PromptBuilder。"""

    def build(self, context: BehaviorPlanningContext) -> str:
        candidates = [
            {
                "activity_type": item.activity_type,
                "description": item.description,
                "supported_operations": [
                    operation.value for operation in item.supported_operations
                ],
                "semantic_descriptions": list(item.semantic_descriptions),
                "constraints_schema": item.constraints_schema,
                "constraints_schema_version": item.constraints_schema_version,
            }
            for item in context.activity_definitions
        ]
        ongoing = context.ongoing_activity
        ongoing_payload = (
            {
                "ongoing_activity_id": ongoing.ongoing_activity_id,
                "activity_type": ongoing.activity_type,
                "status": ongoing.status,
                "goal": ongoing.goal,
                "constraints": ongoing.constraints,
                "expected_input": ongoing.expected_input,
                "turn_count": ongoing.turn_count,
                "current_operation": ongoing.current_operation,
                "plugin_state_summary": ongoing.plugin_state_summary,
                "recent_turns": ongoing.recent_turns,
            }
            if ongoing is not None
            else None
        )
        planning_input = {
            "event": {
                "type": context.event_type,
                "source_event_id": context.source_event_id,
                "user_text": context.user_text,
                "request_kind": context.request_kind,
                "authority_role": context.authority_role,
                "instruction_trusted": context.instruction_trusted,
            },
            "situation": context.situation,
            "emotion": context.emotion,
            "drive": context.drive,
            "relationship": context.relationship,
            "conversation_history": list(context.conversation_history),
            "memory": context.memory,
            "related_knowledge": list(context.related_knowledge),
            "last_activity_result": context.last_activity_result,
            "ongoing_activity": ongoing_payload,
            "available_activities": candidates,
        }
        output_schema = {
            "decision": "string",
            "activity_type": "string|null",
            "operation": "start|continue|stop|explain|discuss|null",
            "goal": "string",
            "constraints": "object",
            "speech_act": "statement|question|request|proposal|command",
            "negated": "boolean",
            "hypothetical": "boolean",
            "past_reference": "boolean",
            "knowledge_question": "boolean",
            "confidence": "number",
            "reason": "string",
            "ongoing_input_decision": "string|null",
        }
        return "\n".join(
            [
                "あなたはSituation Evaluatorです。入力を総合して次のActivityを決定します。",
                "# 判断入力",
                json.dumps(planning_input, ensure_ascii=False, default=str),
                "# 出力JSONスキーマ",
                json.dumps(output_schema, ensure_ascii=False),
            ]
        )
