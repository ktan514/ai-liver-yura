from enum import Enum


class ActionType(str, Enum):
    """今この瞬間に実行する具体的な命令。"""

    SPEAK = "speak"
    ASK = "ask"
    REACT = "react"
    LISTEN = "listen"
    OBSERVE = "observe"
    MOVE = "move"
    CHANGE_EXPRESSION = "change_expression"
    UPDATE_SUBTITLE = "update_subtitle"
    SEEK_INFORMATION = "seek_information"
