from app.refrigeration.structural_api import _sample_state


def test_no_sample_channel_is_unknown() -> None:
    assert _sample_state(None, "no-data") == "unknown"


def test_non_good_sample_is_stale() -> None:
    assert _sample_state(4.2, "stale") == "stale"


def test_good_sample_is_known() -> None:
    assert _sample_state(4.2, "good") == "known"
