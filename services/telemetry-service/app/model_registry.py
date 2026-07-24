from __future__ import annotations

from typing import Final


SESSION_MODEL_COUNT: Final = 9


def register_models() -> None:
    """Import persistence models so they are attached to Base.metadata."""
    from app.sessions import models as _session_models

    assert len(_session_models.SESSION_STATES) == 7
