from enum import Enum


class ActivityType(str, Enum):
    """継続する目的を表す Activity の種別。"""

    CONVERSATION_WITH_USER = "conversation_with_user"
    AUTONOMOUS_TALK = "autonomous_talk"
    LISTENING_MODE = "listening_mode"
    STIMULUS_REACTION = "stimulus_reaction"
    CURIOSITY_RESEARCH = "curiosity_research"
    TOPIC_EXPLORATION = "topic_exploration"
    EXTERNAL_TREND_WATCH = "external_trend_watch"
    BODY_EXPRESSION_LOOP = "body_expression_loop"
    IDLE_OBSERVATION = "idle_observation"
