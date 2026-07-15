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
        return "\n".join(
            [
                "あなたはSituation Evaluatorです。発話本文は生成せず意味構造JSONだけ返す。",
                f"ユーザー入力: {context.user_text}",
                f"認識可能なActivity定義: {json.dumps(candidates, ensure_ascii=False)}",
                f"進行中Activity: {json.dumps(ongoing_payload, ensure_ascii=False)}",
                "Capabilityの利用可否、Provider選択、実行成功を推測しない。",
                "疑問形と知識質問、提案を別々の軸で評価する。",
                "進行中Activityがあっても無条件にcontinueにしない。",
                "ongoing_input_decisionはcontinue_current/stop_current/pause_current/"
                "resume_current/conversation_about_current/conversation_unrelated/"
                "start_other_activity/switch_activity/ask_confirmation/no_actionから選ぶ。",
                "全キーを含むJSONだけを返す:",
                '{"decision":"conversation","activity_type":"conversation",'
                '"operation":"discuss","goal":"話題について会話する",'
                '"constraints":{},"speech_act":"question","negated":false,'
                '"hypothetical":false,"past_reference":false,'
                '"knowledge_question":true,"confidence":0.9,"reason":"reason",'
                '"ongoing_input_decision":"conversation_about_current"}',
            ]
        )
