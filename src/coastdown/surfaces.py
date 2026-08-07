"""Surface classes and their rolling-resistance scenarios.

A single ``Crr`` across asphalt, gravel and dirt is not a simplification, it is a
modelling error: rolling resistance is the dominant loss at the low speeds where
a coasting run ends, and it varies by roughly an order of magnitude across the
surfaces present in the study area.

Every value below is a **scenario bound, not a measurement**.  No coast-down
test was run for this study, and the published literature reports coefficients
that depend on tyre, pressure, load and surface condition, none of which OSM
records.  Values are therefore quoted to two significant figures at most, each
class carries an explicit low/high interval that the sensitivity analysis must
sweep, and the interval widens as the surface becomes less well characterised.
Treating any of these as a known constant would be a misuse of the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SurfaceClass(str, Enum):
    ASPHALT_GOOD = "asphalt_good"
    ASPHALT_DEGRADED = "asphalt_degraded"
    STABILISED_GRAVEL = "stabilised_gravel"
    COMPACT_TRACK = "compact_track"
    DIRT = "dirt"
    UNSUITABLE = "unsuitable"


@dataclass(frozen=True)
class RollingResistanceScenario:
    """Central value and bounds for one surface class."""

    surface_class: SurfaceClass
    central: float
    low: float
    high: float
    basis: str
    uncertainty: str

    def __post_init__(self) -> None:
        if not 0 < self.low <= self.central <= self.high < 0.1:
            raise ValueError(
                f"{self.surface_class}: bounds must satisfy 0 < low <= central <= high."
            )

    @property
    def relative_width(self) -> float:
        """Width of the interval as a fraction of the central value."""
        return (self.high - self.low) / self.central


# Anchors: Wilson & Papadopoulos, *Bicycling Science* (3rd ed., MIT Press),
# chapter 6, gives Crr of roughly 0.004-0.008 for a well-inflated tyre on smooth
# hard surfaces, and notes the sharp rise on loose or deformable ground. Values
# for unpaved classes are bounded from that published range rather than measured,
# which is why their intervals are wide.
_SCENARIOS: dict[SurfaceClass, RollingResistanceScenario] = {
    SurfaceClass.ASPHALT_GOOD: RollingResistanceScenario(
        SurfaceClass.ASPHALT_GOOD,
        central=0.0060,
        low=0.0045,
        high=0.0080,
        basis=(
            "Smooth hard surface with a well-inflated touring/hybrid tyre; the "
            "published range for this configuration."
        ),
        uncertainty="±30%, driven by tyre choice and inflation rather than by the surface.",
    ),
    SurfaceClass.ASPHALT_DEGRADED: RollingResistanceScenario(
        SurfaceClass.ASPHALT_DEGRADED,
        central=0.0100,
        low=0.0070,
        high=0.0150,
        basis=(
            "Cracked, patched or coarse-chipping asphalt, and the class used when a "
            "classified road carries no surface tag at all."
        ),
        uncertainty=(
            "±50%. Also absorbs the risk of the missing-tag assumption being wrong, "
            "so it is deliberately pessimistic."
        ),
    ),
    SurfaceClass.STABILISED_GRAVEL: RollingResistanceScenario(
        SurfaceClass.STABILISED_GRAVEL,
        central=0.018,
        low=0.012,
        high=0.028,
        basis="Bound, compacted or fine gravel that stays firm under a 90 kg system.",
        uncertainty="Roughly a factor 2 either way; strongly dependent on recent weather.",
    ),
    SurfaceClass.COMPACT_TRACK: RollingResistanceScenario(
        SurfaceClass.COMPACT_TRACK,
        central=0.028,
        low=0.018,
        high=0.045,
        basis="Firm unsealed track, OSM tracktype grade2 or an equivalent compacted way.",
        uncertainty="Factor 2.5 span. Not characterised for this study.",
    ),
    SurfaceClass.DIRT: RollingResistanceScenario(
        SurfaceClass.DIRT,
        central=0.045,
        low=0.028,
        high=0.075,
        basis="Bare earth or loose ground that deforms under load.",
        uncertainty=(
            "Factor 2.7 span and the weakest class. Any ranking that depends on "
            "separating two dirt routes is not supported by this model."
        ),
    ),
}

# Surfaces a standard hybrid bicycle cannot be assumed to roll on at all, either
# because they deform, because they are hazardous without braking, or because the
# tag describes a structure rather than a running surface.
UNSUITABLE_SURFACES = frozenset(
    {
        "grass",
        "sand",
        "mud",
        "rock",
        "stone",
        "pebblestone",
        "snow",
        "ice",
        "salt",
        "woodchips",
        "metal",
        "wood",
        "metal_grid",
        "grass_paver",
    }
)

PAVED_SMOOTH_SURFACES = frozenset(
    {"asphalt", "chipseal", "concrete", "concrete:lanes", "concrete:plates", "paved"}
)
PAVED_ROUGH_SURFACES = frozenset({"paving_stones", "sett", "cobblestone", "unhewn_cobblestone"})
STABILISED_SURFACES = frozenset({"compacted", "fine_gravel"})
LOOSE_SURFACES = frozenset({"gravel", "ground", "dirt", "earth", "unpaved", "clay", "sand_gravel"})


def rolling_resistance(surface_class: SurfaceClass) -> RollingResistanceScenario:
    """Return the scenario for a class; unsuitable surfaces have no scenario."""
    if surface_class is SurfaceClass.UNSUITABLE:
        raise ValueError("SurfaceClass.UNSUITABLE carries no rolling-resistance scenario.")
    return _SCENARIOS[surface_class]


def all_scenarios() -> tuple[RollingResistanceScenario, ...]:
    return tuple(_SCENARIOS[name] for name in SurfaceClass if name is not SurfaceClass.UNSUITABLE)


def coefficient(surface_class: SurfaceClass, variant: str = "central") -> float:
    """Pick the central, low or high coefficient of a class."""
    scenario = rolling_resistance(surface_class)
    if variant == "central":
        return scenario.central
    if variant == "low":
        return scenario.low
    if variant == "high":
        return scenario.high
    raise ValueError("variant must be 'central', 'low' or 'high'.")
