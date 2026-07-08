

from app.domain.drives import DriveState


def test_drive_state_has_default_values() -> None:
    drive_state = DriveState()

    assert drive_state.curiosity == 0.5
    assert drive_state.engagement == 0.5
    assert drive_state.boredom == 0.0
    assert drive_state.energy == 0.7


def test_drive_state_clamps_values_to_0_1_range() -> None:
    drive_state = DriveState(
        curiosity=1.5,
        engagement=-0.5,
        boredom=2.0,
        energy=-1.0,
    )

    assert drive_state.curiosity == 1.0
    assert drive_state.engagement == 0.0
    assert drive_state.boredom == 1.0
    assert drive_state.energy == 0.0


def test_should_start_autonomous_talk_when_curiosity_is_high() -> None:
    drive_state = DriveState(curiosity=0.7)

    assert drive_state.should_start_autonomous_talk() is True


def test_should_start_autonomous_talk_when_engagement_is_high() -> None:
    drive_state = DriveState(engagement=0.75)

    assert drive_state.should_start_autonomous_talk() is True


def test_should_start_autonomous_talk_when_boredom_is_high() -> None:
    drive_state = DriveState(boredom=0.8)

    assert drive_state.should_start_autonomous_talk() is True


def test_should_not_start_autonomous_talk_when_energy_is_low() -> None:
    drive_state = DriveState(curiosity=0.9, energy=0.2)

    assert drive_state.should_start_autonomous_talk() is False


def test_should_not_start_autonomous_talk_when_drive_is_weak() -> None:
    drive_state = DriveState(
        curiosity=0.69,
        engagement=0.74,
        boredom=0.79,
        energy=0.7,
    )

    assert drive_state.should_start_autonomous_talk() is False


def test_strongest_drive_name_returns_highest_drive() -> None:
    drive_state = DriveState(
        curiosity=0.4,
        engagement=0.6,
        boredom=0.9,
        energy=0.7,
    )

    assert drive_state.strongest_drive_name() == "boredom"