"""Create synthetic wound-patch trajectories for the demo ML pipeline.

HONEST LIMIT: there is no public dataset of pH + skin temperature + moisture
patch readings. These curves are written by us from the general idea that an
infection pushes pH up, warms the skin and wets the dressing. A model trained on
them learns OUR simulator, not real wounds. The point is a complete, repeatable
pipeline that can be retrained on real patch data when it exists.

Usage: python -m ml.generate_data --out ml/data/synthetic.jsonl --n 4000 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from ml.features import HORIZON, PH_LINE, WINDOW

LENGTH = 40  # readings per trajectory


def trajectory(rng: random.Random) -> list[dict[str, float | None]]:
    """One wound course: healing, stalled, or healing that turns into infection."""
    kind = rng.choices(["healing", "stalled", "infection"], weights=[0.45, 0.2, 0.35])[0]
    onset = rng.randint(WINDOW + 2, LENGTH - HORIZON - 2) if kind == "infection" else None
    ramp = rng.randint(3, 8)
    ph0, t0, m0 = rng.uniform(6.6, 7.2), rng.uniform(36.3, 36.9), rng.uniform(35, 55)
    rows: list[dict[str, float | None]] = []
    for i in range(LENGTH):
        progress = 0.0
        if onset is not None and i >= onset:
            progress = min(1.0, (i - onset + 1) / ramp)
        if kind == "healing":
            ph = ph0 - 0.004 * i
            temp = t0 - 0.002 * i
            moist = m0 - 0.25 * i
        elif kind == "stalled":
            ph = ph0 + rng.uniform(-0.05, 0.05) + 0.25
            temp = t0 + 0.25
            moist = m0 + 12
        else:
            ph = ph0 + progress * rng.uniform(0.9, 1.4)
            temp = t0 + progress * rng.uniform(0.7, 1.3)
            moist = m0 + progress * rng.uniform(15, 35)
        row: dict[str, float | None] = {
            "ph": round(ph + rng.gauss(0, 0.06), 3),
            "skin_temp_c": round(temp + rng.gauss(0, 0.1), 3),
            "moisture_pct": round(min(100.0, max(0.0, moist + rng.gauss(0, 2.5))), 2),
        }
        for key in list(row):  # occasional sensor dropout
            if rng.random() < 0.02:
                row[key] = None
        rows.append(row)
    return rows


def label_windows(rows: list[dict[str, float | None]]) -> list[tuple[list[dict], int]]:
    """(window, y) pairs. y = 1 if pH crosses the see-a-doctor line within HORIZON readings."""
    out = []
    for end in range(WINDOW, len(rows) - HORIZON + 1):
        window = rows[end - WINDOW : end]
        future = rows[end : end + HORIZON]
        already = any((r["ph"] or 0) > PH_LINE for r in window)
        if already:
            continue  # nothing to foresee: the rules already fired
        y = int(any((r["ph"] or 0) > PH_LINE for r in future))
        out.append((window, y))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="ml/data/synthetic.jsonl")
    parser.add_argument("--n", type=int, default=4000, help="number of wounds")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for wound in range(args.n):
            rows = trajectory(rng)
            for window, y in label_windows(rows):
                handle.write(json.dumps({"wound": wound, "window": window, "y": y}) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
