from enum import Enum


class ActionResource(str, Enum):
    MOUTH = "mouth"
    FACE = "face"
    BODY = "body"
    HANDS = "hands"
    EYES = "eyes"
    HEAVY_BRAIN = "heavy_brain"
    LIGHT_BRAIN = "light_brain"
    SUBTITLE = "subtitle"
    OBS = "obs"
