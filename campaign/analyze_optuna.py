# Summarize the structured Optuna studies (run INSIDE the container: optuna is not on the host).
#   sbatch -A gts-<PI> --export=ALL,WORK_ROOT=<study_optuna dir>,SCRIPT=/campaign/analyze_optuna.py run_script.sbatch
# Writes /work/optuna_summary.json and /work/optuna_summary.md, plus /work/tasks_validate.jsonl:
# (with scikit-learn + shap installed, each study also gets a SHAP importance table; see
# lazagna_shap.py. Without them that table is skipped and everything else is unchanged.)
# 5-seed "custom" validation tasks for the top-K layouts of each study (structured params),
# to be run with experiment.sbatch in the main study dir.
#
# Multi-benchmark studies (campaign/suite_study.py; their trials carry per-design results) get
# their own report in /work/analysis/<study>/: report.md (Pareto front with the champion,
# per-design results of the champion, Spearman and SHAP tables, top trials), pareto.* and
# shap.* files, trials.csv, and tasks_champion.jsonl (5-seed validation of the champion on
# every design, for experiment.sbatch). Journals without such studies give the same output
# as before.
import glob
import json
import math
import os
import sys

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
TOPK = int(os.environ.get("TOPK", "3"))
sys.path[:0] = [CODE, ROOT]
import optuna
from lazagna_optuna import journal_storage

try:
    import lazagna_shap
    lazagna_shap._require()
    HAVE_SHAP = True
except ImportError as _e:
    HAVE_SHAP = False
    print(f"note: SHAP tables skipped ({_e})")

optuna.logging.set_verbosity(optuna.logging.WARNING)
PARAMS = ["dsp_on_l0", "bram_on_l0", "cluster", "stagger", "band_pos"]


def spearman(xs, ys):
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2.0
            i = j + 1
        return r
    if len(xs) < 3:
        return float("nan")
    rx, ry = ranks(xs), ranks(ys); mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    c = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx)); sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return c / (sx * sy) if sx and sy else float("nan")


# Designs of the structured studies, in the order the validation tasks were first written for.
FULL = {"koios": ["tpu_like.small.os", "attention_layer", "tpu_like.small.ws", "conv_layer", "eltwise_layer",
                  "robot_rl", "reduction_layer", "spmv", "clstm_like.small"],
        "vtr": ["stereovision1", "stereovision2", "arm_core", "mkDelayWorker32B", "LU8PEEng"]}


def design_entry(design):
    """'<suite>/<name>' for a study's design label (study names turn '.' into '_'): the list
    above first, then every suite in benchmark_suites. None if no suite has the design."""
    for s, ds in FULL.items():
        for d in ds:
            if d.replace(".", "_") == design:
                return f"{s}/{d}"
    from benchmark_suites import SUITES, list_designs
    for s in SUITES:
        try:
            names = list_designs(s, ROOT)
        except FileNotFoundError:
            continue
        for d in names:
            if d.replace(".", "_") == design:
                return f"{s}/{d}"
    return None


summary, md, tasks = {}, ["# Structured layout search (Optuna, routed, 3 seeds)", ""], []
suite_studies = []
for log in sorted(glob.glob(os.path.join(WORK, "journal", "*.log"))):
    name = os.path.basename(log)[:-4]
    try:
        st = optuna.load_study(study_name=name, storage=journal_storage(log))
    except Exception as e:
        print("skip", name, e); continue
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if done and "per_design" in done[0].user_attrs:
        suite_studies.append((name, st))
        continue
    if not done or "dsp_on_l0" not in done[0].params:
        continue
    design = name.replace("columns_", "").split("_tall")[0].split("_1x1")[0]
    rows = [{"n": t.number, **{p: t.params[p] for p in PARAMS},
             "cpd_impr": t.user_attrs.get("cpd_impr_pct"), "wl_impr": t.user_attrs.get("wl_impr_pct")}
            for t in done]
    # Normalized fractions on layer 0 (0.5 = balanced like the reference)
    n_dsp_tot = max(r["dsp_on_l0"] for r in rows) or 1
    corr = {}
    for p in PARAMS:
        xs = [r[p] for r in rows]
        corr[p] = {"cpd": spearman(xs, [r["cpd_impr"] for r in rows]),
                   "wl": spearman(xs, [r["wl_impr"] for r in rows])}
    # imbalance = how far from an even per-layer split
    for r in rows:
        r["imbalance"] = abs(r["dsp_on_l0"] / max(1, n_dsp_tot) - 0.5) * 2
    corr["imbalance(dsp)"] = {"cpd": spearman([r["imbalance"] for r in rows], [r["cpd_impr"] for r in rows]),
                              "wl": spearman([r["imbalance"] for r in rows], [r["wl_impr"] for r in rows])}
    score = lambda r: (r["cpd_impr"] or -99) + (r["wl_impr"] or -99)
    top = sorted(rows, key=score, reverse=True)[:TOPK]
    pareto = [t.number for t in st.best_trials]
    summary[name] = {"design": design, "n_complete": len(done), "baseline_cpd": st.user_attrs.get("baseline_cpd"),
                     "corr": corr, "top": top, "pareto": pareto, "rows": rows}
    md += [f"## {design} ({len(done)} trials)", "",
           "| parameter | Spearman vs CPD gain | Spearman vs WL gain |", "|---|---|---|"]
    md += [f"| {p} | {c['cpd']:+.2f} | {c['wl']:+.2f} |" for p, c in corr.items()]
    if HAVE_SHAP:
        try:
            shap_res = lazagna_shap.explain_study(st, targets=("cpd_impr_pct", "wl_impr_pct"), params=PARAMS)
            summary[name]["shap"] = [{k: v for k, v in r.items() if k != "per_sample"} for r in shap_res]
            by = [{e["param"]: e for e in r["importance"]} for r in shap_res]
            md += ["", f"SHAP importance (tree surrogate; mean |SHAP| in % points of gain; surrogate CV R² "
                       f"CPD {shap_res[0]['cv_r2']:.2f}, WL {shap_res[1]['cv_r2']:.2f}):", "",
                   "| parameter | CPD mean \\|SHAP\\| | CPD direction | WL mean \\|SHAP\\| | WL direction |",
                   "|---|---|---|---|---|"]
            md += [f"| {p} | {by[0][p]['mean_abs_shap']:.2f} | {lazagna_shap._fmt_dir(by[0][p])} | "
                   f"{by[1][p]['mean_abs_shap']:.2f} | {lazagna_shap._fmt_dir(by[1][p])} |" for p in PARAMS]
        except Exception as e:   # too few trials etc.: keep the rest of the summary
            md += ["", f"SHAP importance skipped: {type(e).__name__}: {e}"]
    md += ["", "Top trials (sum of CPD + WL gain vs aligned reference, 3 seeds):", "",
           "| trial | dsp_on_l0 | bram_on_l0 | cluster | stagger | band_pos | CPD % | WL % |",
           "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['n']} | {r['dsp_on_l0']} | {r['bram_on_l0']} | {r['cluster']:.2f} | {r['stagger']:.2f} | "
           f"{r['band_pos']:.2f} | {r['cpd_impr']:+.2f} | {r['wl_impr']:+.2f} |" for r in top]
    md.append("")
    entry = design_entry(design)
    if entry is None:
        md += [f"(No validation tasks: design '{design}' was not found in the benchmark suites.)", ""]
        continue
    for r in top:
        tasks.append({"id": f"custom__{design}__t{r['n']}", "kind": "custom", "design": entry, "seeds": 5,
                      "structured": {p: r[p] for p in PARAMS}})

if not summary and suite_studies:   # only multi-benchmark studies: say where their reports are
    md += ["No single-design studies in this journal; see "
           + ", ".join(f"analysis/{n}/report.md" for n, _ in suite_studies), ""]
json.dump(summary, open(os.path.join(WORK, "optuna_summary.json"), "w"), indent=1)
open(os.path.join(WORK, "optuna_summary.md"), "w").write("\n".join(md))
open(os.path.join(WORK, "tasks_validate.jsonl"), "w").write("\n".join(json.dumps(t) for t in tasks) + "\n")
print("\n".join(md))


# ------------------------------------------------------------------- multi-benchmark studies
GAIN_NOTE = ("Gains are % improvement over each design's own 3D reference (evenly spread, aligned "
             "hard-block columns, full connectivity, delay ratio 0.739), combined over the designs "
             "as a geometric mean of the ratios.")


def _varying_params(trials):
    """Parameters that take more than one value (a fixed connectivity or delay says nothing)."""
    names = []
    for t in trials:
        for p in t.params:
            if p not in names:
                names.append(p)
    return [p for p in names if len({repr(t.params.get(p)) for t in trials}) > 1]


def champion_tasks(name, st, t, entries):
    """5-seed validation of the champion on every design (experiment.py tasks), plus each
    design's rq1 task (2D baseline + 3D reference); rq1 ids match the study's, so results that
    already exist are reused. Structured and connectivity searches only."""
    mode = st.user_attrs.get("search_mode")
    p = t.params
    out = []
    for e in entries:
        d = e.split("/", 1)[1]
        task = {"id": f"champ__{name}__{d}", "design": e, "seeds": 5}
        if mode == "structured":
            task.update(kind="custom", conn=p.get("connectivity", 1.0), delay=p.get("delay_ratio", 0.739),
                        structured_frac={k: p[k] for k in ("dsp_frac_l0", "bram_frac_l0", "cluster",
                                                           "stagger", "band_pos")})
        elif mode == "connectivity" and p.get("type_sb") == st.user_attrs.get("arch_type"):
            # experiment.py's "conn" kind: the reference columns with this connectivity
            task.update(kind="conn", conn=p.get("connectivity", 1.0), delay=p.get("delay_ratio", 0.739))
        else:
            return []
        out += [{"id": f"rq1__{d}", "kind": "rq1", "design": e, "seeds": 5}, task]
    return out


def suite_report(name, st):
    import csv
    from collections import Counter
    import lazagna_pareto as lp

    out = os.path.join(WORK, "analysis", name)
    os.makedirs(out, exist_ok=True)
    ua = st.user_attrs
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE
            and isinstance(t.user_attrs.get("cpd_impr_pct"), (int, float))
            and isinstance(t.user_attrs.get("wl_impr_pct"), (int, float))]
    by_num = {t.number: t for t in done}
    entries = ua.get("designs") or (done[0].user_attrs.get("designs") if done else []) or []
    states = Counter(t.state.name for t in st.trials)
    points, res = lp.study_analysis(st)
    files = lp.write_outputs(points, res, out, title=name)
    champ = by_num.get(points[res["champion"]]["id"]) if res["champion"] is not None else None
    w = ua.get("objective_weights")
    objective = (f"one weighted objective, {w[0]:g} x CPD gain + {w[1]:g} x WL gain" if w
                 else "two objectives (CPD gain, WL gain), Pareto front")
    if ua.get("link_penalty"):
        objective += f", link penalty {ua['link_penalty']:g} points per unit of vertical links"
    md = [f"# Multi-benchmark study: {name}", "",
          f"- Designs: {', '.join(entries)}",
          f"- Search mode: {ua.get('search_mode', '?')}; sampler: {ua.get('sampler', '?')}; seeds: "
          f"{ua.get('seeds', '?')}; fidelity: {ua.get('fidelity', '?')}; objective: {objective}",
          f"- Trials: {states.get('COMPLETE', 0)} complete, {states.get('PRUNED', 0)} pruned, "
          f"{states.get('FAIL', 0)} failed, {states.get('RUNNING', 0)} still running", "",
          GAIN_NOTE, "",
          lp.to_markdown(points, res, title="CPD gain vs WL gain")]
    if any(f.endswith(".png") for f in files):
        md += ["![Pareto front](pareto.png)", ""]

    if champ is not None:
        per = champ.user_attrs.get("per_design") or {}
        md += [f"## Champion: trial {champ.number}", "",
               "Parameters: " + ", ".join(f"{k} = {v:.3g}" if isinstance(v, float) else f"{k} = {v}"
                                         for k, v in champ.params.items()), "",
               "| design | CPD gain % | WL gain % | reference CPD (ns) | reference WL |", "|---|---|---|---|---|"]
        for e in entries:
            r = per.get(e)
            if r:
                md.append(f"| {e} | {r['cpd_impr_pct']:+.2f} | {r['wl_impr_pct']:+.2f} | "
                          f"{r['baseline_cpd'] * 1e9:.3f} | {r['baseline_wl']:.0f} |")
        md += [f"| **geomean** | **{champ.user_attrs['cpd_impr_pct']:+.2f}** | "
               f"**{champ.user_attrs['wl_impr_pct']:+.2f}** | | |", ""]
        tasks_c = champion_tasks(name, st, champ, entries)
        if tasks_c:
            with open(os.path.join(out, "tasks_champion.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(t) for t in tasks_c) + "\n")
            md += ["`tasks_champion.jsonl` re-runs the champion at 5 seeds on every design (with each "
                   "design's rq1 baseline) through experiment.sbatch.", ""]

    varying = _varying_params(done)
    params = [p for p in varying if all(isinstance(t.params[p], (int, float)) for t in done if p in t.params)]
    if len(done) >= 3 and params:
        md += ["## Spearman correlation of each parameter with the gains", "",
               "| parameter | vs CPD gain | vs WL gain |", "|---|---|---|"]
        for p in params:
            sub = [t for t in done if p in t.params]
            xs = [float(t.params[p]) for t in sub]
            c = spearman(xs, [t.user_attrs["cpd_impr_pct"] for t in sub])
            wl = spearman(xs, [t.user_attrs["wl_impr_pct"] for t in sub])
            md.append(f"| {p} | {c:+.2f} | {wl:+.2f} |")
        md.append("")

    if HAVE_SHAP:
        try:
            shap_res = lazagna_shap.explain_study(st, params=varying)
            lazagna_shap.write_outputs(shap_res, out, title=name)
            md += [lazagna_shap.to_markdown(shap_res, title="SHAP importance (tree surrogate)")]
        except Exception as e:   # too few trials etc.: keep the rest of the report
            md += [f"SHAP importance skipped: {type(e).__name__}: {e}", ""]
    else:
        md += ["SHAP importance skipped: scikit-learn and shap are not installed "
               "(pip install -r requirements-analysis.txt).", ""]

    top = sorted(done, key=lambda t: -lp.score({"x": t.user_attrs["cpd_impr_pct"], "y": t.user_attrs["wl_impr_pct"],
                                                "link_fraction": t.user_attrs.get("link_fraction")},
                                               res["weights"], res["link_penalty"]))[:10]
    if top:
        md += ["## Top trials", "", f"Ranked by {res['weights'][0]:g} x CPD gain + {res['weights'][1]:g} x WL gain"
               + (f" with link penalty {res['link_penalty']:g}" if res["link_penalty"] else "") + ".", "",
               "| trial | CPD gain % | WL gain % | " + " | ".join(entries) + " |",
               "|---|---|---|" + "---|" * len(entries)]
        for t in top:
            per = t.user_attrs.get("per_design") or {}
            cells = [f"{per[e]['cpd_impr_pct']:+.1f} / {per[e]['wl_impr_pct']:+.1f}" if e in per else "–"
                     for e in entries]
            md.append(f"| {t.number} | {t.user_attrs['cpd_impr_pct']:+.2f} | {t.user_attrs['wl_impr_pct']:+.2f} | "
                      + " | ".join(cells) + " |")
        md += ["", "(per-design cells: CPD / WL gain %)", ""]

    keys = [p for p in dict.fromkeys(k for t in done for k in t.params)]
    on_front = {points[i]["id"] for i in res["front"]}
    with open(os.path.join(out, "trials.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["trial"] + keys + ["cpd_impr_pct", "wl_impr_pct", "link_fraction", "on_front", "champion"]
                    + [f"{k}_{e}" for e in entries for k in ("cpd_impr_pct", "wl_impr_pct")])
        for t in done:
            per = t.user_attrs.get("per_design") or {}
            wr.writerow([t.number] + [t.params.get(k, "") for k in keys]
                        + [t.user_attrs["cpd_impr_pct"], t.user_attrs["wl_impr_pct"],
                           t.user_attrs.get("link_fraction", ""), int(t.number in on_front),
                           int(champ is not None and t.number == champ.number)]
                        + [per.get(e, {}).get(k, "") for e in entries for k in ("cpd_impr_pct", "wl_impr_pct")])
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write("\n".join(md))
    print(f"\n{name}: {len(done)} complete trials, {len(res['front'])} on the Pareto front"
          + (f", champion trial {champ.number} (CPD {champ.user_attrs['cpd_impr_pct']:+.2f}%, "
             f"WL {champ.user_attrs['wl_impr_pct']:+.2f}%)" if champ is not None else "")
          + f" -> {os.path.join(out, 'report.md')}")


for _name, _st in suite_studies:
    try:
        suite_report(_name, _st)
    except Exception as _e:   # one broken study must not lose the others' reports
        print(f"{_name}: report failed: {type(_e).__name__}: {_e}")
