# SHAP view of the fixed-configuration study: which architecture knobs and which design
# properties drive the 3D gains. Runs locally on the versioned results (needs scikit-learn,
# shap and matplotlib: pip install -r requirements-analysis.txt):
#     python3 campaign/shap_study.py docs/study docs/study
# Writes <out>/study_runs.csv, <out>/shap_tables.md and <out>/figs/shap_study.png
# (docs/study/shap_study.md is the write-up of these tables).
#
# study_runs.csv has one row per routed 3D configuration of a design: its knobs (layout,
# conn = share of 3D switch blocks, vconn = share of their channels that cross, loc, delay
# ratio), the design's properties (from its rq1 sizing, as in campaign/analyze.py), and its
# gains. Gains are defined as in analyze.py: % improvement per seed, paired by seed, then the
# mean over seeds. vs2d = over the design's equal-resource 2D device (its rq1 2D run). vs3d =
# over the aligned 3D reference (its rq1 3D run, or the 10-seed aligned run for 10-seed
# confirmations); the reference rows themselves have no vs3d value. Each configuration of a
# design appears once: the rq1 run for the reference (the separate "aligned" layout runs are
# bit-identical to it), and the 5-seed run when there is also a 10-seed confirmation.
#
# The surrogate's R² is reported twice: plain 5-fold CV, and with whole designs held out. The
# design properties identify each design, so only the second says whether the model predicts
# a design it has not seen.
import csv
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import analyze as A          # paired(), hb_share(), short(): the study's own definitions
import lazagna_shap as ls

KNOBS = ["layout", "conn", "vconn", "loc", "delay"]
DESIGN = ["hb_share", "side_2d", "clb_util_2d", "hb_util_2d"]
TARGETS = {"vs2d": ("cpd_vs2d_pct", "wl_vs2d_pct"), "vs3d": ("cpd_vs3d_pct", "wl_vs3d_pct")}
COLS = (["id", "design", "suite", "kind", "tag", "seeds"] + KNOBS + ["links"] + DESIGN
        + ["cpd_vs2d_pct", "wl_vs2d_pct", "n_vs2d", "cpd_vs3d_pct", "wl_vs3d_pct", "n_vs3d"])


def build_rows(results_dir: str) -> list[dict]:
    recs = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(results_dir, "results", "*.json")))]
    ok = [r for r in recs if "error" not in r and (r.get("3d") or {}).get("per_seed")]
    rq1 = {A.short(r["task"]["design"]): r for r in ok if r["task"]["kind"] == "rq1"}
    s10_aligned = {A.short(r["task"]["design"]): r for r in ok if r["task"].get("tag") == "s10"
                   and r["task"]["kind"] == "layout" and r["task"]["layout"] == "aligned"}
    rows, seen = [], {}
    # rq1 first, then the other 5-seed runs, so a re-run of the same configuration is the duplicate
    for r in sorted(ok, key=lambda r: (r["task"].get("tag") == "s10", r["task"]["kind"] != "rq1",
                                       r["task"]["id"])):
        t = r["task"]
        d = A.short(t["design"])
        if d not in rq1:
            continue
        kind = t["kind"]
        layout = {"rq1": "aligned", "conn": "aligned", "custom": "searched"}.get(kind, t.get("layout"))
        conn, vconn = float(t.get("conn", 1.0)), float(t.get("vconn", 1.0))
        loc, delay = t.get("loc", "repeated_interval"), float(t.get("delay", 0.739))
        key = (d, layout, conn, vconn, loc, delay, json.dumps(t.get("structured"), sort_keys=True))
        if key in seen:
            continue
        seen[key] = t["id"]
        ref = rq1[d]
        (c2, _, n2), (w2, _, _) = A.paired(ref["2d"], r["3d"])
        if kind == "rq1":
            c3 = w3 = n3 = ""
        else:
            base3 = s10_aligned[d]["3d"] if t.get("tag") == "s10" and d in s10_aligned else ref["3d"]
            (c3, _, n3), (w3, _, _) = A.paired(base3, r["3d"])
        sz = ref["sizing"]
        util = {k: sz["demand"].get(k, 0) / sz["cap_2d"][k] if sz["cap_2d"].get(k) else 0.0
                for k in ("clb", "complex_dsp", "spram")}
        rows.append({
            "id": t["id"], "design": d, "suite": t["design"].split("/", 1)[0], "kind": kind,
            "tag": t.get("tag", ""), "seeds": len(r["3d"]["per_seed"]),
            "layout": layout, "conn": conn, "vconn": vconn, "loc": loc, "delay": delay,
            "links": round(conn * vconn, 4),
            "hb_share": round(A.hb_share(ref), 4), "side_2d": round(math.sqrt(sz["tiles_2d"]), 2),
            "clb_util_2d": round(util["clb"], 4), "hb_util_2d": round(max(util["complex_dsp"], util["spram"]), 4),
            "cpd_vs2d_pct": round(c2, 3), "wl_vs2d_pct": round(w2, 3), "n_vs2d": n2,
            "cpd_vs3d_pct": c3 if c3 == "" else round(c3, 3), "wl_vs3d_pct": w3 if w3 == "" else round(w3, 3),
            "n_vs3d": n3,
        })
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def cv_spread(table, target, seeds=range(10)):
    """Out-of-fold R² of the surrogate over several random splits: plain 5-fold, and 5-fold
    with whole designs held out. (mean, sd) each; one split alone moves by several points."""
    import numpy as np
    from sklearn.metrics import r2_score
    from sklearn.model_selection import GroupKFold, KFold, cross_val_predict
    X = ls.encode(table)[0]
    y = np.asarray(table.targets[target], dtype=float)
    plain, grouped = [], []
    for s in seeds:
        plain.append(r2_score(y, cross_val_predict(ls._model(s, len(y)), X, y,
                                                   cv=KFold(n_splits=5, shuffle=True, random_state=s))))
        try:
            gkf = GroupKFold(n_splits=5, shuffle=True, random_state=s)
        except TypeError:           # scikit-learn < 1.6: one fixed grouping
            gkf = GroupKFold(n_splits=5)
        grouped.append(r2_score(y, cross_val_predict(ls._model(s, len(y)), X, y, cv=gkf, groups=table.groups)))
    return (float(np.mean(plain)), float(np.std(plain))), (float(np.mean(grouped)), float(np.std(grouped)))


TITLES = {"cpd_vs2d_pct": "CPD gain over 2D", "wl_vs2d_pct": "WL gain over 2D",
          "cpd_vs3d_pct": "CPD gain over aligned 3D", "wl_vs3d_pct": "WL gain over aligned 3D"}


def figure(results: dict, path: str) -> None:
    plt = A.setup_mpl()
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.6))
    for ax, r in zip(axes.ravel(), [x for k in ("vs2d", "vs3d") for x in results[k]]):
        imp = r["importance"][::-1]
        cols = [A.ORANGE if e["param"] in DESIGN else A.BLUE for e in imp]
        ax.barh([e["param"] for e in imp], [e["mean_abs_shap"] for e in imp], height=0.6, color=cols,
                xerr=[e["sd"] for e in imp], error_kw=dict(ecolor=A.INK2, lw=0.8, capsize=2))
        (p, _), (g, _) = r["cv_spread"]
        ax.set_title(f"{TITLES[r['target']]}\nn = {r['n']}, CV R² {p:.2f}, designs held out {g:.2f}".replace("-", "\u2212"),
                     loc="left", fontsize=9)
        ax.set_xlabel("mean |SHAP| (percentage points of gain)")
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=A.BLUE, label="architecture knob"), Patch(color=A.ORANGE, label="design property")],
               loc="lower center", ncol=2, fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _tbl(r):
    out = ["| parameter | kind | mean \\|SHAP\\| (points) | ± sd | share | direction |", "|---|---|---|---|---|---|"]
    for e in r["importance"]:
        out.append(f"| {e['param']} | {'design' if e['param'] in DESIGN else 'knob'} | {e['mean_abs_shap']:.2f} | "
                   f"{e['sd']:.2f} | {100 * e['share']:.0f}% | {ls._fmt_dir(e)} |")
    return out


def _fit_reading(p, g):
    if p < ls.LOW_R2:
        return "weak: mostly seed noise"
    if g < ls.LOW_R2:
        return "fits the known designs, does not predict a new one"
    return "moderate" if p < 0.6 else "good"


def tables_md(rows, results) -> str:
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    out = ["<!-- generated by campaign/shap_study.py from the study results; see shap_study.md -->", "",
           f"{len(rows)} routed 3D configurations of {len({r['design'] for r in rows})} designs "
           f"({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}). Features: knobs "
           f"{', '.join(KNOBS)}; design properties {', '.join(DESIGN)}.", "",
           "## Surrogate fit", "",
           "| target | n | CV R² (10 splits) | designs held out | train R² | reading |", "|---|---|---|---|---|---|"]
    for k in ("vs2d", "vs3d"):
        for r in results[k]:
            (p, ps), (g, gs) = r["cv_spread"]
            out.append(f"| {r['target']} | {r['n']} | {p:.2f} ± {ps:.2f} | {g:.2f} ± {gs:.2f} | "
                       f"{r['train_r2']:.2f} | {_fit_reading(p, g)} |")
    out += ["", "![SHAP importance](figs/shap_study.png)", "",
            "## Share of importance", "",
            "Share of the summed mean |SHAP|; in brackets, the direction of a numeric parameter "
            "(Spearman of its value vs its SHAP value; layout and loc by category further down).", "",
            "| parameter | kind | " + " | ".join(TITLES[r["target"]] for k in ("vs2d", "vs3d") for r in results[k]) + " |",
            "|---|---|---|---|---|---|"]
    for prm in KNOBS + DESIGN:
        cells = []
        for k in ("vs2d", "vs3d"):
            for r in results[k]:
                e = next(x for x in r["importance"] if x["param"] == prm)
                d = ls._fmt_dir(e)
                num = e["kind"] == "numeric" and d not in ("·", "")
                cells.append(f"{100 * e['share']:.0f}%" + (f" ({d})" if num else ""))
        out.append(f"| {prm} | {'design' if prm in DESIGN else 'knob'} | " + " | ".join(cells) + " |")
    out.append("")
    for k in ("vs2d", "vs3d"):
        for r in results[k]:
            out += [f"## {TITLES[r['target']]} ({r['target']})", "",
                    f"Average prediction {r['expected_value']:+.2f} points; n = {r['n']}.", ""] + _tbl(r) + [""]
            for e in r["importance"]:
                if e["kind"] == "categorical":
                    cats = sorted(e["by_category"].items(), key=lambda x: -x[1])
                    out.append(f"- {e['param']}, mean SHAP by category: "
                               + ", ".join(f"{c} {v:+.2f}" for c, v in cats))
            out.append("")
    out += ["Direction: Spearman correlation between a numeric parameter's value and its SHAP value "
            "(+ = larger values raise the gain). Category values are mean SHAP values, i.e. relative to the "
            "average configuration in the study, not to the aligned reference. '·' = share below 5%.", ""]
    return "\n".join(out)


def main(results_dir: str, out_dir: str) -> None:
    rows = build_rows(results_dir)
    csv_path = os.path.join(out_dir, "study_runs.csv")
    write_csv(rows, csv_path)
    results = {}
    for k, targets in TARGETS.items():
        table = ls.table_from_csv(csv_path, list(targets), KNOBS + DESIGN, id_col="id", group_col="design")
        results[k] = []
        for t in targets:
            r = ls.shap_importance(table, t, n_repeats=5, seed=0)
            r["cv_spread"] = cv_spread(table, t)
            results[k].append(r)
    os.makedirs(os.path.join(out_dir, "figs"), exist_ok=True)
    figure(results, os.path.join(out_dir, "figs", "shap_study.png"))
    with open(os.path.join(out_dir, "shap_tables.md"), "w") as f:
        f.write(tables_md(rows, results))
    print(f"wrote {csv_path} ({len(rows)} rows), {out_dir}/shap_tables.md, {out_dir}/figs/shap_study.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/study", sys.argv[2] if len(sys.argv) > 2 else "docs/study")
