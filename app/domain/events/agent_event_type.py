from enum import Enum


class AgentEventType(str, Enum):
    """AIライバー内部で扱うイベント種別。"""

    USER_TEXT = "user_text"
    YOUTUBE_COMMENT = "youtube_comment"
    USER_SPEECH = "user_speech"
    CAMERA_FRAME = "camera_frame"

    SILENCE_TIMEOUT = "silence_timeout"
    SPEECH_STARTED = "speech_started"
    SPEECH_FINISHED = "speech_finished"
    CURIOSITY_PEAK = "curiosity_peak"
    TREND_UPDATED = "trend_updated"
    ACTION_FAILED = "action_failed"

    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"

    APP_STARTED = "app_started"
    STREAM_STARTED = "stream_started"
    STREAM_MAIN_SEGMENT = "stream_main_segment"
    STREAM_COMMENT_RESPONSE = "stream_comment_response"
    STREAM_ENDING = "stream_ending"
    STREAM_ENDED = "stream_ended"
