from enum import IntEnum


class InputAuthority(IntEnum):
    """ゆらが入力元に付与する信頼レベル。OSの権限とは無関係。"""

    VIEWER = 10
    USER = 40
    ADMINISTRATOR = 100
    SYSTEM = 120

    @property
    def role(self) -> str:
        return self.name.lower()

    @property
    def instruction_trusted(self) -> bool:
        return self >= InputAuthority.ADMINISTRATOR
