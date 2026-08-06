# Rotational-inertia scenarios for a representative Decathlon hybrid

Reference category: Decathlon Riverside 500 / comparable 700c Riverside hybrid, sold across
multiple revisions during the early-to-mid 2020s. The product family is a category anchor, not
evidence that one component specification represents every VTC. Official product entry point
recorded 2026-08-06: <https://www.decathlon.fr/>. Live product/archive verification was blocked
by the execution proxy and must be completed before this range is promoted beyond provisional.

For components rotating at wheel angular speed, equivalent mass is `m_eq = I/r²`. A thin ring
of mass `m` near radius `r` contributes about `m`; a uniform disk contributes `m/2`; a hub near
the axis contributes little. Tires and tubes are mostly near the rim; rims/spokes are between a
ring and a distributed structure. Non-wheel rotating drivetrain parts need their gear-ratio-
adjusted inertia but are small during freewheel and remain outside this first range.

| Scenario | Two rims/spokes contribution | Two tires/tubes contribution | Hubs/other | Total `m_eq` |
|---|---:|---:|---:|---:|
| Null/control | 0 | 0 | 0 | 0.0 kg |
| Low | 0.55 | 0.55 | 0.05 | 1.15 kg |
| Central | 0.75 | 0.75 | 0.10 | 1.60 kg |
| High | 1.00 | 1.05 | 0.15 | 2.20 kg |

These are reproducible scenario assumptions, not weighed component values. Required follow-up:
freeze exact Riverside revisions; record wheel radius and component masses from official
specifications or measurements; calculate component moments/radius distributions; propagate
the resulting low/central/high range without using it yet to rank routes.
