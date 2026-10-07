from pathlib import Path

from . import PslType as PslType

ALL: PslType
ICANN: PslType
PRIVATE: PslType

def update(*, timeout: float = ...) -> None:
    """Download and reload the Public Suffix List."""

def get_psl_path() -> Path | None:
    """Return the writable PSL path, if available."""
