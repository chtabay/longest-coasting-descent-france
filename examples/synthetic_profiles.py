from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from coastdown import RoadProfile, simulate_profile


PROFILES = {
    "flat": RoadProfile(np.array([3_000.0]), np.array([0.0])),
    "gentle_long": RoadProfile(np.array([12_000.0]), np.array([-0.012])),
    "steep_short": RoadProfile(np.array([2_000.0]), np.array([-0.08])),
    "dip_and_rise": RoadProfile(
        np.array([2_000.0, 250.0, 4_000.0]),
        np.array([-0.035, 0.012, -0.008]),
    ),
}


def main() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    for name, profile in PROFILES.items():
        result = simulate_profile(profile)
        print(
            f"{name:12s} time={result.elapsed_time_s:8.1f}s "
            f"distance={result.travelled_distance_m:8.1f}m "
            f"reason={result.stop_reason}"
        )
        plt.figure()
        plt.plot(result.distance_m / 1000, result.speed_m_s * 3.6)
        plt.xlabel("Distance (km)")
        plt.ylabel("Speed (km/h)")
        plt.title(name)
        plt.tight_layout()
        plt.savefig(output_dir / f"synthetic_{name}.png", dpi=160)
        plt.close()


if __name__ == "__main__":
    main()
