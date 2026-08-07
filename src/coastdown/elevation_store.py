"""Lookup of already-acquired terrain elevations.

Acquisition and analysis are separate steps, so the analysis side needs a way to
ask for the elevation of a sample point without knowing how it was fetched.  The
store is keyed on coordinates rounded to seven decimals, about a centimetre,
which is finer than any sampling this study performs and coarse enough that two
ways meeting at a junction agree on the value.

A point the store does not know is an error, not a zero: silently substituting a
default would put an invented cliff into a profile.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

from .sampling import SamplePoint

COORDINATE_DECIMALS = 7


class MissingElevationError(LookupError):
    """Raised when a sample point was never acquired."""


def store_key(longitude: float, latitude: float) -> str:
    return f"{longitude:.{COORDINATE_DECIMALS}f},{latitude:.{COORDINATE_DECIMALS}f}"


def load_store(path: str | Path) -> dict[str, float]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {key: float(value) for key, value in raw.items()}


def elevations_for(
    store: dict[str, float], samples: Sequence[SamplePoint]
) -> tuple[float, ...] | None:
    """Elevations for every sample, or ``None`` when any of them is unknown.

    ``None`` rather than an exception because an edge outside the acquired set
    is an ordinary outcome for a scenario narrower than the one acquired; the
    caller marks the edge unsimulable and moves on.
    """
    values: list[float] = []
    for sample in samples:
        value = store.get(store_key(sample.longitude, sample.latitude))
        if value is None or not math.isfinite(value):
            return None
        values.append(value)
    return tuple(values)
