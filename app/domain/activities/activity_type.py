from enum import Enum


class ActivityType(str, Enum):
    """継続する目的を表す Activity の種別。"""

    CONVERSATION_WITH_USER = "conversation_with_user"
    DIRECTED_TALK = "directed_talk"
    PLUGIN_ACTIVITY = "plugin_activity"
    BEHAVIOR_PLANNING = "behavior_planning"
    AUTONOMOUS_TALK = "autonomous_talk"
    STARTUP_REACTION = "startup_reaction"
    STREAM_OPENING_GREETING = "stream_opening_greeting"
    STREAM_MAIN_SEGMENT = "stream_main_segment"
    STREAM_COMMENT_RESPONSE = "stream_comment_response"
    STREAM_CLOSING_GREETING = "stream_closing_greeting"
    LISTENING_MODE = "listening_mode"
    STIMULUS_REACTION = "stimulus_reaction"
    CURIOSITY_RESEARCH = "curiosity_research"
    TOPIC_EXPLORATION = "topic_exploration"
    EXTERNAL_TREND_WATCH = "external_trend_watch"
    BODY_EXPRESSION_LOOP = "body_expression_loop"
    IDLE_OBSERVATION = "idle_observation"
