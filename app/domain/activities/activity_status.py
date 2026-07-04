from enum import Enum


class ActivityStatus(str, Enum):
    """Activity の状態。"""

    PENDING = "pending"
    ACTIVE = "active"
    WAITING = "waiting"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    CANCELED = "canceled"
