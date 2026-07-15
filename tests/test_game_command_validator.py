from app.domain.games import ShiritoriGameDefinition, ShiritoriPlayer, ShiritoriState
from app.plugins.games.intent import GameCommandValidator, GameIntent, GameIntentCommand
from app.runtime.game_engine import GameEngine


def _command(
    intent: GameIntent,
    *,
    state_version: int = 0,
    confidence: float = 0.99,
    game_type: str | None = "shiritori",
    game_move: str | None = None,
    control: str | None = None,
    requires_confirmation: bool = False,
) -> GameIntentCommand:
    return GameIntentCommand(
        intent=intent,
        game_type=game_type,
        confidence=confidence,
        state_version=state_version,
        game_move=game_move,
        control=control,
        requires_confirmation=requires_confirmation,
    )


def test_validator_accepts_supported_start_and_rejects_duplicate() -> None:
    engine = GameEngine((ShiritoriGameDefinition(),))
    validator = GameCommandValidator(engine)

    assert validator.validate(_command(GameIntent.START_GAME), current_state_version=0).accepted
    engine.start_game("shiritori")

    result = validator.validate(_command(GameIntent.START_GAME), current_state_version=0)

    assert result.accepted is False
    assert result.reason == "active_session_exists"


def test_validator_rejects_stale_and_low_confidence_commands() -> None:
    validator = GameCommandValidator(GameEngine((ShiritoriGameDefinition(),)))

    stale = validator.validate(
        _command(GameIntent.START_GAME, state_version=1), current_state_version=2
    )
    low = validator.validate(
        _command(GameIntent.START_GAME, confidence=0.7), current_state_version=0
    )

    assert stale.reason == "stale_state"
    assert low.requires_confirmation is True


def test_validator_requires_session_user_turn_move_and_allowed_control() -> None:
    engine = GameEngine((ShiritoriGameDefinition(),))
    validator = GameCommandValidator(engine)
    missing = validator.validate(
        _command(GameIntent.PLAY_GAME_MOVE, game_move="みみず"),
        current_state_version=0,
    )
    engine.start_game(
        "shiritori",
        metadata={"shiritori_state": ShiritoriState(current_turn=ShiritoriPlayer.AI)},
    )
    wrong_turn = validator.validate(
        _command(GameIntent.PLAY_GAME_MOVE, game_move="みみず"),
        current_state_version=0,
    )
    invalid_control = validator.validate(
        _command(GameIntent.GAME_CONTROL, control="restart"),
        current_state_version=0,
    )

    assert missing.reason == "session_or_move_missing"
    assert wrong_turn.reason == "not_user_turn"
    assert invalid_control.reason == "invalid_control"
