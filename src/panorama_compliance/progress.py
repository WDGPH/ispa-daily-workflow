from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Sized
from typing import TypeVar

from tqdm import tqdm as _tqdm

_TRUE_TOKENS = {"1", "true", "yes", "on"}
_FALSE_TOKENS = {"0", "false", "no", "off"}

_PROGRESS_OVERRIDE: bool | None = None


def configure_progress(enabled: bool | None) -> None:
    """Override progress enablement for the current process.

    enabled=None resets to the default behavior (auto when stderr is a TTY).
    """

    global _PROGRESS_OVERRIDE
    _PROGRESS_OVERRIDE = enabled


def progress_enabled() -> bool:
    override = _PROGRESS_OVERRIDE
    if override is not None:
        return bool(override)

    env = os.getenv("PANORAMA_PROGRESS")
    if env is not None:
        token = env.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False

    isatty = getattr(sys.stderr, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


_T = TypeVar("_T")


def tqdm(
    iterable: Iterable[_T] | None = None,
    *,
    total: int | None = None,
    desc: str | None = None,
    unit: str = "it",
    disable: bool | None = None,
    leave: bool = False,
) -> _tqdm[_T]:
    effective_total = total
    if effective_total is None and isinstance(iterable, Sized):
        effective_total = len(iterable)
    if disable is None:
        disable = not progress_enabled()
    if effective_total is not None and effective_total <= 1:
        disable = True
    return _tqdm(
        iterable,
        total=total,
        desc=desc,
        unit=unit,
        leave=leave,
        disable=disable,
        file=sys.stderr,
        dynamic_ncols=True,
    )
