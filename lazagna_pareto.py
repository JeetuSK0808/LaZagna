"""Architectural Pareto fronts: CPD gain vs wirelength gain, with the chosen champion.

Reads the COMPLETE trials of an Optuna study (or the rows of a CSV), keeps the points that no
other point beats on both gains (the Pareto front; higher is better on both axes), and picks
one champion from the front: the point with the highest

    w_cpd * (CPD gain - p) + w_wl * (WL gain - p),   p = link_penalty * link_fraction

with weights (1, 1) by default, i.e. the sum of the two gains (the ranking campaign/
analyze_optuna.py uses for its top trials). This is the same score SearchConfig's
objective_weights / link_penalty give the sampler (lazagna_optuna.objective_values). For a
study run with one weighted objective, the champion is the study's best trial.

Outputs: <prefix>.csv (every point, with on_front / champion flags), <prefix>.md (the front as
a table) and, if matplotlib is installed, <prefix>.png (every trial, the front, the champion).

  python3 lazagna_pareto.py --journal <run>/journal/<study>.log --study <study> --out pareto_out
  python3 lazagna_pareto.py --storage sqlite:///study.db --study lazagna_3d --weights 1,0
  python3 lazagna_pareto.py --csv runs.csv --x cpd_gain --y wl_gain --id-col id
"""
from __future__ import annotations

import csv
import json
import math
import os
from typing import Optional, Sequence

X_DEFAULT, Y_DEFAULT = "cpd_impr_pct", "wl_impr_pct"

# Reference palette (light), as in campaign/analyze.py.
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, MUTED = "#2a78d6", "#eb6834", "#b5b3ad"


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def pareto_front(xs: Sequence[float], ys: Sequence[float]) -> list[int]:
    """Indices of the points no other point dominates (maximizing both x and y), in input
    order. Identical points are all kept."""
    front = []
    for i, (xi, yi) in enumerate(zip(xs, ys)):
        if not any((xj >= xi and yj >= yi) and (xj > xi or yj > yi) for xj, yj in zip(xs, ys)):
            front.append(i)
    return front


def score(point: dict, weights: Sequence[float] = (1.0, 1.0), link_penalty: float = 0.0) -> float:
    p = link_penalty * (point.get("link_fraction") or 0.0)
    return weights[0] * (point["x"] - p) + weights[1] * (point["y"] - p)


def choose_champion(points: list[dict], front: list[int], weights: Sequence[float] = (1.0, 1.0),
                    link_penalty: float = 0.0, best_id=None) -> Optional[int]:
    """Index (into points) of the champion: the point with id best_id if given (a weighted,
    single-objective study's best trial), else the front point with the highest score()."""
    if best_id is not None:
        for i, p in enumerate(points):
            if p["id"] == best_id:
                return i
    if not front:
        return None
    return max(front, key=lambda i: (score(points[i], weights, link_penalty), -i))


def points_from_study(study, x: str = X_DEFAULT, y: str = Y_DEFAULT) -> list[dict]:
    """One point per COMPLETE trial with both user attrs finite."""
    import optuna
    out = []
    for t in study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,)):
        xv, yv = t.user_attrs.get(x), t.user_attrs.get(y)
        if _finite(xv) and _finite(yv):
            out.append({"id": t.number, "x": float(xv), "y": float(yv),
                        "link_fraction": t.user_attrs.get("link_fraction"), "params": dict(t.params)})
    return out


def points_from_csv(path: str, x: str, y: str, id_col: Optional[str] = None) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for i, r in enumerate(rows):
        try:
            xv, yv = float(r[x]), float(r[y])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(xv) and math.isfinite(yv):
            lf = r.get("link_fraction")
            out.append({"id": r[id_col] if id_col else i, "x": xv, "y": yv,
                        "link_fraction": float(lf) if lf not in (None, "") else None,
                        "params": {k: v for k, v in r.items() if k not in (x, y, id_col)}})
    return out


def analyze(points: list[dict], weights: Sequence[float] = (1.0, 1.0), link_penalty: float = 0.0,
            best_id=None) -> dict:
    front = pareto_front([p["x"] for p in points], [p["y"] for p in points])
    champ = choose_champion(points, front, weights, link_penalty, best_id)
    return {"front": front, "champion": champ, "weights": list(weights), "link_penalty": link_penalty,
            "champion_rule": "best trial of the weighted study" if best_id is not None else
            f"front point with the highest {weights[0]:g}*CPD + {weights[1]:g}*WL gain"
            + (f" (link penalty {link_penalty:g})" if link_penalty else "")}


def study_analysis(study, weights: Optional[Sequence[float]] = None, link_penalty: Optional[float] = None,
                   x: str = X_DEFAULT, y: str = Y_DEFAULT) -> tuple[list[dict], dict]:
    """points + analyze() for an Optuna study. Weights / penalty default to the ones the study
    was run with (user attrs objective_weights / link_penalty, set by campaign/suite_study.py),
    else (1, 1) / 0. A single-objective study's champion is its best trial."""
    points = points_from_study(study, x, y)
    ua = study.user_attrs
    w = tuple(weights) if weights else tuple(ua.get("objective_weights") or (1.0, 1.0))
    pen = float(link_penalty if link_penalty is not None else ua.get("link_penalty") or 0.0)
    best_id = None
    if len(study.directions) == 1 and points:
        try:
            best_id = study.best_trial.number
        except ValueError:
            best_id = None
    return points, analyze(points, w, pen, best_id)


def to_markdown(points: list[dict], res: dict, title: str = "", x_label: str = "CPD gain %",
                y_label: str = "WL gain %") -> str:
    front = sorted(res["front"], key=lambda i: -points[i]["x"])
    champ = res["champion"]
    # parameters that never change (e.g. a fixed connectivity) would only add noise
    keys = sorted({k for p in points for k in p["params"]})
    varying = [k for k in keys if len({repr(p["params"].get(k)) for p in points}) > 1]
    out = [f"## Pareto front: {title}", ""] if title else []
    out += [f"{len(front)} of {len(points)} trials are on the front (no other trial is better on both). "
            f"Champion: {res['champion_rule']}.", "",
            f"| trial | {x_label} | {y_label} | links | params |", "|---|---|---|---|---|"]
    for i in front:
        p = points[i]
        mark = " **(champion)**" if i == champ else ""
        lf = p.get("link_fraction")
        params = ", ".join(f"{k}={_fmt(p['params'][k])}" for k in varying if k in p["params"])
        out.append(f"| {p['id']}{mark} | {p['x']:+.2f} | {p['y']:+.2f} | "
                   f"{'' if lf is None else f'{lf:.2f}'} | {params} |")
    if champ is not None and champ not in res["front"]:
        p = points[champ]
        out.append(f"| {p['id']} **(champion, best weighted value)** | {p['x']:+.2f} | {p['y']:+.2f} | | |")
    out.append("")
    return "\n".join(out)


def _fmt(v):
    return f"{v:.3g}" if isinstance(v, float) else str(v)


def plot(points: list[dict], res: dict, path: str, title: str = "", x_label: str = "CPD gain (%)",
         y_label: str = "Wirelength gain (%)") -> bool:
    """Scatter of every point, the front as a step line, the champion marked. False if
    matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    front = sorted(res["front"], key=lambda i: points[i]["x"])
    champ = res["champion"]
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(True, color=GRID, lw=0.6)
    ax.tick_params(colors=INK2, labelsize=8)
    on_front = set(front)
    others = [i for i in range(len(points)) if i not in on_front]
    ax.scatter([points[i]["x"] for i in others], [points[i]["y"] for i in others], s=30, color=MUTED,
               edgecolor=SURFACE, linewidth=1.2, label="trial", zorder=2)
    fx, fy = [points[i]["x"] for i in front], [points[i]["y"] for i in front]
    if front:
        # Sorted by CPD gain the front's WL gain falls, so "pre" traces the edge of the region
        # the front dominates (a "post" step would pass through unreachable corners).
        ax.step(fx, fy, where="pre", color=BLUE, lw=1.5, zorder=3)
        ax.scatter(fx, fy, s=42, color=BLUE, edgecolor=SURFACE, linewidth=1.5, label="Pareto front", zorder=4)
    if champ is not None:
        c = points[champ]
        ax.scatter([c["x"]], [c["y"]], s=150, marker="*", color=ORANGE, edgecolor=SURFACE, linewidth=1.5,
                   label="champion", zorder=5)
        ax.annotate(f"trial {c['id']}", (c["x"], c["y"]), xytext=(6, 6), textcoords="offset points",
                    fontsize=8, color=INK)
    ax.axhline(0, color=INK2, lw=0.7, zorder=1)
    ax.axvline(0, color=INK2, lw=0.7, zorder=1)
    ax.set_xlabel(x_label, color=INK2, fontsize=9)
    ax.set_ylabel(y_label, color=INK2, fontsize=9)
    if title:
        ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK)
    ax.legend(loc="best", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return True


def write_outputs(points: list[dict], res: dict, out_dir: str, prefix: str = "pareto", title: str = "",
                  plot_png: bool = True) -> list[str]:
    """<prefix>.csv, <prefix>.md, <prefix>.json and (with matplotlib) <prefix>.png."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    on_front = set(res["front"])
    keys = sorted({k for p in points for k in p["params"]})
    p_csv = os.path.join(out_dir, prefix + ".csv")
    with open(p_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "cpd_gain_pct", "wl_gain_pct", "link_fraction", "on_front", "champion"] + keys)
        for i, p in enumerate(points):
            lf = p.get("link_fraction")
            w.writerow([p["id"], p["x"], p["y"], "" if lf is None else lf, int(i in on_front),
                        int(i == res["champion"])] + [p["params"].get(k, "") for k in keys])
    paths.append(p_csv)
    p_md = os.path.join(out_dir, prefix + ".md")
    with open(p_md, "w") as f:
        f.write(to_markdown(points, res, title))
    paths.append(p_md)
    p_json = os.path.join(out_dir, prefix + ".json")
    champ = points[res["champion"]] if res["champion"] is not None else None
    with open(p_json, "w") as f:
        json.dump({**res, "front_ids": [points[i]["id"] for i in res["front"]],
                   "champion_id": champ["id"] if champ else None, "champion_point": champ,
                   "n_points": len(points)}, f, indent=1, default=str)
    paths.append(p_json)
    if plot_png:
        p_png = os.path.join(out_dir, prefix + ".png")
        if plot(points, res, p_png, title):
            paths.append(p_png)
    return paths


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Pareto front (CPD gain vs WL gain) of an Optuna study or a CSV.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--journal", help="Optuna JournalStorage log file (campaign studies)")
    src.add_argument("--storage", help="Optuna storage URL, e.g. sqlite:///study.db")
    src.add_argument("--csv", help="CSV with one row per run")
    ap.add_argument("--study", help="study name (with --journal / --storage)")
    ap.add_argument("--x", default=X_DEFAULT, help=f"x gain: trial user attr or CSV column (default {X_DEFAULT})")
    ap.add_argument("--y", default=Y_DEFAULT, help=f"y gain: trial user attr or CSV column (default {Y_DEFAULT})")
    ap.add_argument("--id-col", help="(--csv) column with the row id")
    ap.add_argument("--weights", help="champion weights w_cpd,w_wl (default: the study's, else 1,1)")
    ap.add_argument("--link-penalty", type=float, help="champion link penalty (default: the study's, else 0)")
    ap.add_argument("--out", default="pareto_out", help="output directory (default pareto_out)")
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args(argv)
    weights = tuple(float(v) for v in a.weights.split(",")) if a.weights else None
    if weights is not None and len(weights) != 2:
        ap.error("--weights needs two numbers, e.g. 1,1")
    if a.csv:
        points = points_from_csv(a.csv, a.x, a.y, a.id_col)
        res = analyze(points, weights or (1.0, 1.0), a.link_penalty or 0.0)
        title = os.path.basename(a.csv)
    else:
        import optuna
        if not a.study:
            ap.error("--journal / --storage need --study")
        if a.journal:
            from lazagna_optuna import journal_storage
            storage = journal_storage(a.journal)
        else:
            storage = a.storage
        study = optuna.load_study(study_name=a.study, storage=storage)
        points, res = study_analysis(study, weights, a.link_penalty, a.x, a.y)
        title = a.study
    if not points:
        print("no complete trials with both gains")
        return 1
    for p in write_outputs(points, res, a.out, title=title, plot_png=not a.no_plot):
        print("wrote", p)
    print(to_markdown(points, res, title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
