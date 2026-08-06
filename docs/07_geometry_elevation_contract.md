# Normative geometry and elevation contract

## Coordinate and direction contract

Every metropolitan-France production coordinate is transformed to **Lambert-93, EPSG:2154**
before metric operations. WGS84 longitude/latitude is an interchange representation only.
Every road edge has an explicit travel direction; samples are ordered in that direction.

For consecutive samples `i` and `i+1`:

- `dx = hypot(x[i+1]-x[i], y[i+1]-y[i])` is horizontal planimetric length in metres;
- `dz = z[i+1]-z[i]` is oriented elevation change in metres;
- `grade_ratio = dz / dx` (negative downhill, positive uphill);
- `grade_angle_rad = atan(grade_ratio)`;
- `segment_length_m = hypot(dx, dz)` is three-dimensional travelled length.

The simulator receives `segment_length_m` and `grade_ratio`, never horizontal length as a
substitute. This makes `sin(grade_angle_rad) * segment_length_m = dz`, so gravitational work
`-m*g*sin(theta)*segment_length` equals the potential-energy loss `-m*g*dz`.

## Sampling chain

1. retain raw source geometry and units in provenance;
2. reproject to EPSG:2154;
3. remove consecutive duplicates without changing topology;
4. densify at a declared horizontal spacing;
5. sample an identified, versioned elevation source;
6. reject or flag missing elevation and discontinuities;
7. apply smoothing only as a named, parameterized scenario;
8. calculate `dx`, `dz`, grade, angle and 3D length;
9. emit an oriented typed edge and simulator profile.

Zero horizontal length, missing elevation, absolute grade above the declared guard and abnormal
elevation jumps are errors. Reversing an edge reverses sample/elevation order and grade signs,
while preserving the multiset of horizontal and 3D lengths.

## Structures

Terrain elevation is not roadway elevation on bridges, tunnels or stacked roads. Such edges
retain their structure and `layer`/level metadata. They are simulable only with a compatible
roadway/structure altitude source; otherwise their elevation is unknown and they enter the
inspection list. Missing access data similarly maps to `review`, never silently to admissible.

## Provenance minimum

Geometry and elevation each record producer, dataset, source version/date, retrieval date,
URL/identifier, original CRS, original units and SHA-256 when a file is frozen. Quality flags
survive profile creation. The 50% grade limit is an anomaly guard, not dimensional typing.
