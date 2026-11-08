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

Studies with vertical links as a third objective (SearchConfig.links_objective; three
directions): the front is the set no other point beats on CPD gain, WL gain and link_fraction
(fewer links is better), shown as a table sorted by links and as two panels, WL gain and CPD
gain against links. There are two champions: "best" = the front point with the highest
w_cpd * CPD + w_wl * WL gain (res["champion"]), and "lean" = the same among front points with
link_fraction <= max_links (default 0.1; res["lean"], None if no front point qualifies).

  python3 lazagna_pareto.py --journal <run>/journal/<study>.log --study <study> --out pareto_out
  python3 lazagna_pareto.py --storage sqlite:///study.db --study lazagna_3d --weights 1,0
  python3 lazagna_pareto.py --csv runs.csv --x cpd_gain --y wl_gain --id-col id
  python3 lazagna_pareto.py --csv runs.csv --links-objective --max-links 0.25   # needs a link_fraction column
"""
from __future__ import annotations

import csv
import json
import math
import os
from typing import Optional, Sequence

X_DEFAULT, Y_DEFAULT = "cpd_impr_pct", "wl_impr_pct"
MAX_LINKS_DEFAULT = 0.1     # link budget of the "lean" champion (studies with links as an objective)

# Reference palette (light), as in campaign/analyze.py.
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, MUTED = "#2a78d6", "#eb6834", "#b5b3ad"
AQUA = "#1baf7a"


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


def pareto_front_links(xs: Sequence[float], ys: Sequence[float], links: Sequence[float]) -> list[int]:
    """Indices of the points no other point dominates when maximizing x and y and minimizing
    links (at least as good on all three, better on one), in input order. Ties are all kept."""
    pts = list(zip(xs, ys, links))
    return [i for i, (xi, yi, li) in enumerate(pts)
            if not any(xj >= xi and yj >= yi and lj <= li and (xj > xi or yj > yi or lj < li)
                       for xj, yj, lj in pts)]


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
    """One point per COMPLETE trial with both user attrs finite. In a study with links as the
    third objective, a trial without a link_fraction attr takes its third objective value."""
    import optuna
    three = len(study.directions) == 3
    out = []
    for t in study.get_trials(deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,)):
        xv, yv = t.user_attrs.get(x), t.user_attrs.get(y)
        if _finite(xv) and _finite(yv):
            lf = t.user_attrs.get("link_fraction")
            if three and not _finite(lf) and t.values and len(t.values) == 3:
                lf = t.values[2]
            out.append({"id": t.number, "x": float(xv), "y": float(yv),
                        "link_fraction": lf, "params": dict(t.params)})
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


def analyze_links(points: list[dict], weights: Sequence[float] = (1.0, 1.0),
                  max_links: float = MAX_LINKS_DEFAULT) -> dict:
    """analyze() with vertical links as a third objective (every point needs a finite
    link_fraction): the front over (max CPD gain, max WL gain, min links). "best" =
    res["champion"], the front point with the highest w_cpd * CPD + w_wl * WL gain (ties: fewer
    links); "lean" = res["lean"], the same among front points with links <= max_links (None if
    there is none)."""
    links = [float(p["link_fraction"]) for p in points]
    front = pareto_front_links([p["x"] for p in points], [p["y"] for p in points], links)
    key = lambda i: (score(points[i], weights), -links[i], -i)
    best = max(front, key=key) if front else None
    budget = [i for i in front if links[i] <= max_links + 1e-12]
    lean = max(budget, key=key) if budget else None
    return {"front": front, "champion": best, "lean": lean, "weights": list(weights), "link_penalty": 0.0,
            "objectives": 3, "max_links": max_links,
            "champion_rule": f"front point with the highest {weights[0]:g}*CPD + {weights[1]:g}*WL gain",
            "lean_rule": f"the same among front points with links <= {max_links:g}"}


def study_analysis(study, weights: Optional[Sequence[float]] = None, link_penalty: Optional[float] = None,
                   x: str = X_DEFAULT, y: str = Y_DEFAULT,
                   max_links: Optional[float] = None) -> tuple[list[dict], dict]:
    """points + analyze() for an Optuna study. Weights / penalty default to the ones the study
    was run with (user attrs objective_weights / link_penalty, set by campaign/suite_study.py),
    else (1, 1) / 0. A single-objective study's champion is its best trial. A study with three
    objectives (links as the third) gets analyze_links(), with max_links (default 0.1) for the
    lean champion."""
    points = points_from_study(study, x, y)
    ua = study.user_attrs
    w = tuple(weights) if weights else tuple(ua.get("objective_weights") or (1.0, 1.0))
    if len(study.directions) == 3:
        points = [p for p in points if _finite(p.get("link_fraction"))]
        return points, analyze_links(points, w, MAX_LINKS_DEFAULT if max_links is None else float(max_links))
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
    if res.get("objectives") == 3:
        return _markdown_links(points, res, title, x_label, y_label)
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


def _markdown_links(points: list[dict], res: dict, title: str, x_label: str, y_label: str) -> str:
    """The 3-objective front as a table sorted by links (then by score), best and lean marked."""
    w = res["weights"]
    front = sorted(res["front"], key=lambda i: (points[i]["link_fraction"], -score(points[i], w), i))
    best, lean = res["champion"], res.get("lean")
    keys = sorted({k for p in points for k in p["params"]})
    varying = [k for k in keys if len({repr(p["params"].get(k)) for p in points}) > 1]
    out = [f"## Pareto front: {title}", ""] if title else []
    none = (f" No front point has links <= {res['max_links']:g}, so there is no lean champion."
            if lean is None and best is not None else "")
    out += [f"{len(front)} of {len(points)} trials are on the front (no other trial is at least as good on CPD "
            f"gain, WL gain and vertical links, and better on one). Champions: **best** = {res['champion_rule']}; "
            f"**lean** = {res['lean_rule']}.{none}", "",
            f"| trial | links | {x_label} | {y_label} | params |", "|---|---|---|---|---|"]
    for i in front:
        p = points[i]
        tags = [n for n, j in (("best", best), ("lean", lean)) if j == i]
        mark = f" **({', '.join(tags)})**" if tags else ""
        params = ", ".join(f"{k}={_fmt(p['params'][k])}" for k in varying if k in p["params"])
        out.append(f"| {p['id']}{mark} | {p['link_fraction']:.3g} | {p['x']:+.2f} | {p['y']:+.2f} | {params} |")
    out.append("")
    return "\n".join(out)


def _fmt(v):
    return f"{v:.3g}" if isinstance(v, float) else str(v)


def plot(points: list[dict], res: dict, path: str, title: str = "", x_label: str = "CPD gain (%)",
         y_label: str = "Wirelength gain (%)") -> bool:
    """Scatter of every point, the front as a step line, the champion marked. False if
    matplotlib is missing. With three objectives: plot_links()."""
    if res.get("objectives") == 3:
        return plot_links(points, res, path, title, cpd_label=x_label, wl_label=y_label)
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


def plot_links(points: list[dict], res: dict, path: str, title: str = "", cpd_label: str = "CPD gain (%)",
               wl_label: str = "Wirelength gain (%)") -> bool:
    """Three objectives: two panels, WL gain and CPD gain against vertical links, every trial in
    gray, the 3D front in blue, the best champion as a star, the lean one as a diamond, and the
    lean champion's link budget as a dashed line. False if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter, NullLocator
    except ImportError:
        return False
    front, best, lean = set(res["front"]), res["champion"], res.get("lean")
    links = [float(p["link_fraction"]) for p in points]
    budget = res.get("max_links", MAX_LINKS_DEFAULT)
    log = bool(links) and min(links) > 0
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0))
    fig.patch.set_facecolor(SURFACE)
    others = [i for i in range(len(points)) if i not in front]
    on = sorted(front)
    for ax, key, label in ((axes[0], "y", wl_label), (axes[1], "x", cpd_label)):
        ax.set_facecolor(SURFACE)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        ax.grid(True, color=GRID, lw=0.6)
        ax.tick_params(colors=INK2, labelsize=8)
        ax.scatter([links[i] for i in others], [points[i][key] for i in others], s=30, color=MUTED,
                   edgecolor=SURFACE, linewidth=1.2, label="trial", zorder=2)
        ax.scatter([links[i] for i in on], [points[i][key] for i in on], s=42, color=BLUE,
                   edgecolor=SURFACE, linewidth=1.5, label="Pareto front", zorder=3)
        if best is not None:
            ax.scatter([links[best]], [points[best][key]], s=150, marker="*", color=ORANGE, edgecolor=SURFACE,
                       linewidth=1.5, label="champion: best" + (" (= lean)" if lean == best else ""), zorder=5)
            ax.annotate(f"best: trial {points[best]['id']}", (links[best], points[best][key]), xytext=(6, 6),
                        textcoords="offset points", fontsize=8, color=INK)
        if lean is not None and lean != best:
            ax.scatter([links[lean]], [points[lean][key]], s=70, marker="D", color=AQUA, edgecolor=SURFACE,
                       linewidth=1.5, label="champion: lean", zorder=5)
            ax.annotate(f"lean: trial {points[lean]['id']}", (links[lean], points[lean][key]), xytext=(6, -12),
                        textcoords="offset points", fontsize=8, color=INK)
        if budget > 0 or not log:
            ax.axvline(budget, color=INK2, lw=0.8, ls=(0, (3, 3)), zorder=1, label=f"lean budget (links <= {budget:g})")
        ax.axhline(0, color=INK2, lw=0.7, zorder=1)
        if log:
            ax.set_xscale("log")
            lo_, hi_ = min(links + [budget] if budget > 0 else links), max(links)
            ax.set_xticks([v for v in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0) if lo_ / 1.6 <= v <= hi_ * 1.6])
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
            ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xlabel("Vertical links (share of full 3D)", color=INK2, fontsize=9)
        ax.set_ylabel(label, color=INK2, fontsize=9)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=len(labels), fontsize=8, frameon=False)
    if title:
        fig.suptitle(title, x=0.01, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return True


def write_outputs(points: list[dict], res: dict, out_dir: str, prefix: str = "pareto", title: str = "",
                  plot_png: bool = True) -> list[str]:
    """<prefix>.csv, <prefix>.md, <prefix>.json and (with matplotlib) <prefix>.png."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    on_front = set(res["front"])
    three = res.get("objectives") == 3      # + a "lean" column / lean_id, lean_point
    keys = sorted({k for p in points for k in p["params"]})
    p_csv = os.path.join(out_dir, prefix + ".csv")
    with open(p_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "cpd_gain_pct", "wl_gain_pct", "link_fraction", "on_front", "champion"]
                   + (["lean"] if three else []) + keys)
        for i, p in enumerate(points):
            lf = p.get("link_fraction")
            w.writerow([p["id"], p["x"], p["y"], "" if lf is None else lf, int(i in on_front),
                        int(i == res["champion"])] + ([int(i == res.get("lean"))] if three else [])
                       + [p["params"].get(k, "") for k in keys])
    paths.append(p_csv)
    p_md = os.path.join(out_dir, prefix + ".md")
    with open(p_md, "w") as f:
        f.write(to_markdown(points, res, title))
    paths.append(p_md)
    p_json = os.path.join(out_dir, prefix + ".json")
    champ = points[res["champion"]] if res["champion"] is not None else None
    meta = {**res, "front_ids": [points[i]["id"] for i in res["front"]],
            "champion_id": champ["id"] if champ else None, "champion_point": champ}
    if three:
        lean = points[res["lean"]] if res.get("lean") is not None else None
        meta.update(lean_id=lean["id"] if lean else None, lean_point=lean)
    meta["n_points"] = len(points)
    with open(p_json, "w") as f:
        json.dump(meta, f, indent=1, default=str)
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
    ap.add_argument("--links-objective", action="store_true",
                    help="(--csv) link_fraction is a third objective, fewer is better (a study with three "
                         "objectives is detected by itself)")
    ap.add_argument("--max-links", type=float,
                    help=f"links objective: link budget of the lean champion (default {MAX_LINKS_DEFAULT:g})")
    ap.add_argument("--out", default="pareto_out", help="output directory (default pareto_out)")
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args(argv)
    weights = tuple(float(v) for v in a.weights.split(",")) if a.weights else None
    if weights is not None and len(weights) != 2:
        ap.error("--weights needs two numbers, e.g. 1,1")
    if a.csv:
        points = points_from_csv(a.csv, a.x, a.y, a.id_col)
        if a.links_objective:
            points = [p for p in points if _finite(p.get("link_fraction"))]
            res = analyze_links(points, weights or (1.0, 1.0),
                                MAX_LINKS_DEFAULT if a.max_links is None else a.max_links)
        else:
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
        points, res = study_analysis(study, weights, a.link_penalty, a.x, a.y, max_links=a.max_links)
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
