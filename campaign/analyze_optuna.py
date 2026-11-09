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
# Studies with vertical links as a third objective (LINKS_OBJECTIVE=1) get the 3D front sorted
# by links, WL and CPD gain against links, and two champions: "best" (highest CPD + WL gain on
# the front) and "lean" (the same among front points with links <= CHAMPION_MAX_LINKS, env,
# default 0.1); tasks_champion.jsonl then re-runs both. Routed studies that kept VPR's
# placement estimates also get a "Placement vs routing" section.
import glob
import json
import math
import os
import sys

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
TOPK = int(os.environ.get("TOPK", "3"))


def _env_float(name, default):
    v = os.environ.get(name, "").strip()
    try:
        return float(v) if v else default
    except ValueError:
        print(f"note: {name}={v!r} is not a number; using {default:g}")
        return default


MAX_LINKS = _env_float("CHAMPION_MAX_LINKS", 0.1)
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


def trial_vconn(st, t):
    """A trial's vertical connectivity when the search set it (the sampled parameter, or a fixed
    VCONN_CHOICES value other than 1), else None: every channel crossed, as before the option."""
    if "vertical_connectivity" in t.params:
        return t.params["vertical_connectivity"]
    fixed = st.user_attrs.get("vertical_connectivity_choices") or []
    return fixed[0] if len(fixed) == 1 and fixed[0] != 1.0 else None


def champion_task(st, t, task_id, entry):
    """One experiment.py task re-running trial t on one design, or None (search mode without one)."""
    mode, p = st.user_attrs.get("search_mode"), t.params
    task = {"id": task_id, "design": entry, "seeds": 5}
    if mode == "structured":
        task.update(kind="custom", conn=p.get("connectivity", 1.0))
        vconn = trial_vconn(st, t)
        if vconn is not None:
            task["vconn"] = vconn
        task.update(delay=p.get("delay_ratio", 0.739),
                    structured_frac={k: p[k] for k in ("dsp_frac_l0", "bram_frac_l0", "cluster",
                                                       "stagger", "band_pos")})
    elif mode == "connectivity" and p.get("type_sb") == st.user_attrs.get("arch_type"):
        # experiment.py's "conn" kind: the reference columns with this connectivity
        task.update(kind="conn", conn=p.get("connectivity", 1.0), delay=p.get("delay_ratio", 0.739))
    else:
        return None
    return task


def champion_tasks(name, st, t, entries, lean=None):
    """5-seed validation of the champion on every design (experiment.py tasks, ids
    champ__<study>__<design>), plus each design's rq1 task (2D baseline + 3D reference); rq1 ids
    match the study's, so results that already exist are reused. `lean`: a second champion (the
    lean one of a study with links as an objective), ids lean__<study>__<design>. Structured and
    connectivity searches only; vconn is set when the search set the vertical connectivity."""
    out = []
    for e in entries:
        d = e.split("/", 1)[1]
        rows = [champion_task(st, tr, f"{prefix}__{name}__{d}", e)
                for prefix, tr in (("champ", t), ("lean", lean)) if tr is not None]
        if any(r is None for r in rows):
            return []
        out += [{"id": f"rq1__{d}", "kind": "rq1", "design": e, "seeds": 5}] + rows
    return out


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _ranks_desc(v):
    """Rank 1 = highest; ties share their mean rank."""
    o = sorted(range(len(v)), key=lambda i: -v[i])
    r, i = [0.0] * len(v), 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def placement_section(done, entries, weights):
    """'Placement vs routing' for a routed study whose trials kept VPR's placement estimates
    (lazagna_optuna.make_suite_objective): Spearman rho of placement-estimated vs routed gains
    over the trials (geomean over the designs), over trial x design pairs and per design; the
    mean placement - routing difference; the trials whose rank differs most. [] without data."""
    trials = [t for t in done if _num(t.user_attrs.get("place_cpd_impr_pct"))
              and _num(t.user_attrs.get("place_wl_impr_pct"))]
    per_design = {e: [] for e in entries}
    for t in done:
        for e, r in (t.user_attrs.get("per_design") or {}).items():
            if e in per_design and _num(r.get("place_cpd_impr_pct")) and _num(r.get("place_wl_impr_pct")):
                per_design[e].append((r["place_cpd_impr_pct"], r["cpd_impr_pct"],
                                      r["place_wl_impr_pct"], r["wl_impr_pct"]))
    pairs = [x for e in entries for x in per_design[e]]
    if not trials and not pairs:
        return []
    f = lambda v: "–" if v != v else f"{v:+.2f}"

    def row(label, items):
        rc = spearman([i[0] for i in items], [i[1] for i in items])
        rw = spearman([i[2] for i in items], [i[3] for i in items])
        dc = sum(i[0] - i[1] for i in items) / len(items)
        dw = sum(i[2] - i[3] for i in items) / len(items)
        return f"| {label} | {len(items)} | {f(rc)} | {f(rw)} | {dc:+.2f} | {dw:+.2f} |"

    md = ["## Placement vs routing", "",
          "Every routed trial also kept VPR's placement estimate of the same runs (before routing); the "
          "placement gains are against the reference's placement estimate. ρ is Spearman's rank correlation "
          "of the placement-estimated with the routed gain (1 = a placement-only search, FIDELITY=place, "
          "would rank these trials the same way); place − route is how far placement over- (+) or "
          "under-states (−) the routed gain, in % points.", "",
          "| trials | n | ρ CPD | ρ WL | place − route, CPD | place − route, WL |", "|---|---|---|---|---|---|"]
    if trials:
        md.append(row("geomean over the designs", [(t.user_attrs["place_cpd_impr_pct"], t.user_attrs["cpd_impr_pct"],
                                                    t.user_attrs["place_wl_impr_pct"], t.user_attrs["wl_impr_pct"])
                                                   for t in trials]))
    if pairs:
        md.append(row("trial × design pairs", pairs))
    md += [row(e, per_design[e]) for e in entries if per_design[e]]
    md.append("")
    if len(trials) >= 2:
        w0, w1 = weights
        rp = _ranks_desc([w0 * t.user_attrs["place_cpd_impr_pct"] + w1 * t.user_attrs["place_wl_impr_pct"]
                          for t in trials])
        rr = _ranks_desc([w0 * t.user_attrs["cpd_impr_pct"] + w1 * t.user_attrs["wl_impr_pct"] for t in trials])
        worst = sorted(range(len(trials)), key=lambda i: (-abs(rp[i] - rr[i]), rr[i]))[:5]
        if abs(rp[worst[0]] - rr[worst[0]]) == 0:
            md += ["Placement and routing rank the trials the same way.", ""]
        else:
            md += [f"Largest rank disagreements (rank 1 = highest {w0:g} x CPD + {w1:g} x WL gain, of {len(trials)}):",
                   "", "| trial | placement CPD / WL % | routed CPD / WL % | rank by placement | rank by routing |",
                   "|---|---|---|---|---|"]
            for i in worst:
                u = trials[i].user_attrs
                md.append(f"| {trials[i].number} | {u['place_cpd_impr_pct']:+.2f} / {u['place_wl_impr_pct']:+.2f} | "
                          f"{u['cpd_impr_pct']:+.2f} / {u['wl_impr_pct']:+.2f} | {rp[i]:g} | {rr[i]:g} |")
            md.append("")
    return md


def _champion_lines(t, entries, heading, note=None):
    per = t.user_attrs.get("per_design") or {}
    md = [heading, ""] + ([note, ""] if note else []) + [
          "Parameters: " + ", ".join(f"{k} = {v:.3g}" if isinstance(v, float) else f"{k} = {v}"
                                     for k, v in t.params.items()), "",
          "| design | CPD gain % | WL gain % | reference CPD (ns) | reference WL |", "|---|---|---|---|---|"]
    for e in entries:
        r = per.get(e)
        if r:
            md.append(f"| {e} | {r['cpd_impr_pct']:+.2f} | {r['wl_impr_pct']:+.2f} | "
                      f"{r['baseline_cpd'] * 1e9:.3f} | {r['baseline_wl']:.0f} |")
    md += [f"| **geomean** | **{t.user_attrs['cpd_impr_pct']:+.2f}** | "
           f"**{t.user_attrs['wl_impr_pct']:+.2f}** | | |", ""]
    return md


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
    points, res = lp.study_analysis(st, max_links=MAX_LINKS)
    three = res.get("objectives") == 3      # links are the third objective: best + lean champions
    files = lp.write_outputs(points, res, out, title=name)
    champ = by_num.get(points[res["champion"]]["id"]) if res["champion"] is not None else None
    lean = by_num.get(points[res["lean"]]["id"]) if three and res.get("lean") is not None else None
    w = ua.get("objective_weights")
    objective = (f"one weighted objective, {w[0]:g} x CPD gain + {w[1]:g} x WL gain" if w
                 else "three objectives (CPD gain, WL gain, vertical links), Pareto front" if three
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
          lp.to_markdown(points, res, title="CPD gain, WL gain and vertical links" if three
                         else "CPD gain vs WL gain")]
    if any(f.endswith(".png") for f in files):
        md += ["![Pareto front: WL and CPD gain against vertical links](pareto.png)" if three
               else "![Pareto front](pareto.png)", ""]
    seeded = [t for t in done if t.user_attrs.get("seeded_from")]
    if ua.get("anchors") and seeded:   # how the known layouts did (ANCHORS=1 studies)
        md += ["Anchors (known layouts queued first): " + ", ".join(
            f"{t.user_attrs['seeded_from']} = trial {t.number} ({t.user_attrs['cpd_impr_pct']:+.2f} / "
            f"{t.user_attrs['wl_impr_pct']:+.2f}, links {t.user_attrs.get('link_fraction', float('nan')):.3g})"
            for t in seeded) + " (CPD / WL gain %).", ""]

    if champ is not None and not three:
        md += _champion_lines(champ, entries, f"## Champion: trial {champ.number}")
        tasks_c = champion_tasks(name, st, champ, entries)
        if tasks_c:
            with open(os.path.join(out, "tasks_champion.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(t) for t in tasks_c) + "\n")
            md += ["`tasks_champion.jsonl` re-runs the champion at 5 seeds on every design (with each "
                   "design's rq1 baseline) through experiment.sbatch.", ""]
    elif champ is not None:
        links = lambda t: t.user_attrs.get("link_fraction", float("nan"))
        md += _champion_lines(champ, entries, f"## Champion \"best\": trial {champ.number}",
                              f"Highest CPD + WL gain on the front; vertical links {links(champ):.3g} (1 = full 3D).")
        if lean is None:
            md += ['## Champion "lean"', "", f"No front point has links <= {res['max_links']:g} "
                   "(CHAMPION_MAX_LINKS).", ""]
        elif lean.number == champ.number:
            md += [f"## Champion \"lean\": trial {lean.number}, the best champion", "",
                   f"Its links ({links(lean):.3g}) are within the {res['max_links']:g} budget.", ""]
        else:
            md += _champion_lines(lean, entries, f"## Champion \"lean\": trial {lean.number}",
                                  f"Highest CPD + WL gain among front points with links <= {res['max_links']:g} "
                                  f"(CHAMPION_MAX_LINKS); vertical links {links(lean):.3g} (1 = full 3D).")
        second = lean if lean is not None and lean.number != champ.number else None
        tasks_c = champion_tasks(name, st, champ, entries, lean=second)
        if tasks_c:
            with open(os.path.join(out, "tasks_champion.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(t) for t in tasks_c) + "\n")
            md += ["`tasks_champion.jsonl` re-runs " + ("both champions (ids champ__… = best, lean__… = lean)"
                                                         if second else "the champion")
                   + " at 5 seeds on every design, with their connectivity and vertical connectivity "
                     "(and each design's rq1 baseline), through experiment.sbatch.", ""]

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
               "| trial | CPD gain % | WL gain % | " + ("links | " if three else "") + " | ".join(entries) + " |",
               "|---|---|---|" + ("---|" if three else "") + "---|" * len(entries)]
        for t in top:
            per = t.user_attrs.get("per_design") or {}
            cells = [f"{per[e]['cpd_impr_pct']:+.1f} / {per[e]['wl_impr_pct']:+.1f}" if e in per else "–"
                     for e in entries]
            lf = (f"{t.user_attrs.get('link_fraction', float('nan')):.3g} | " if three else "")
            md.append(f"| {t.number} | {t.user_attrs['cpd_impr_pct']:+.2f} | {t.user_attrs['wl_impr_pct']:+.2f} | "
                      + lf + " | ".join(cells) + " |")
        md += ["", "(per-design cells: CPD / WL gain %)", ""]
    md += placement_section(done, entries, res["weights"])

    keys = [p for p in dict.fromkeys(k for t in done for k in t.params)]
    on_front = {points[i]["id"] for i in res["front"]}
    # placement-estimate columns only for studies that have them (routed runs of this version)
    place = any("place_cpd_impr_pct" in r for t in done for r in (t.user_attrs.get("per_design") or {}).values())
    gk = ("place_cpd_impr_pct", "place_wl_impr_pct")
    with open(os.path.join(out, "trials.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["trial"] + keys + ["cpd_impr_pct", "wl_impr_pct", "link_fraction", "on_front", "champion"]
                    + (["lean"] if three else [])
                    + [f"{k}_{e}" for e in entries for k in ("cpd_impr_pct", "wl_impr_pct")]
                    + (list(gk) + [f"{k}_{e}" for e in entries for k in gk] if place else []))
        for t in done:
            per = t.user_attrs.get("per_design") or {}
            wr.writerow([t.number] + [t.params.get(k, "") for k in keys]
                        + [t.user_attrs["cpd_impr_pct"], t.user_attrs["wl_impr_pct"],
                           t.user_attrs.get("link_fraction", ""), int(t.number in on_front),
                           int(champ is not None and t.number == champ.number)]
                        + ([int(lean is not None and t.number == lean.number)] if three else [])
                        + [per.get(e, {}).get(k, "") for e in entries for k in ("cpd_impr_pct", "wl_impr_pct")]
                        + ([t.user_attrs.get(k, "") for k in gk] + [per.get(e, {}).get(k, "") for e in entries
                                                                     for k in gk] if place else []))
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write("\n".join(md))
    print(f"\n{name}: {len(done)} complete trials, {len(res['front'])} on the Pareto front"
          + (f", champion trial {champ.number} (CPD {champ.user_attrs['cpd_impr_pct']:+.2f}%, "
             f"WL {champ.user_attrs['wl_impr_pct']:+.2f}%)" if champ is not None else "")
          + (f", lean champion trial {lean.number} (CPD {lean.user_attrs['cpd_impr_pct']:+.2f}%, "
             f"WL {lean.user_attrs['wl_impr_pct']:+.2f}%, links {lean.user_attrs.get('link_fraction', 0):.3g})"
             if three and lean is not None else "")
          + f" -> {os.path.join(out, 'report.md')}")


for _name, _st in suite_studies:
    try:
        suite_report(_name, _st)
    except Exception as _e:   # one broken study must not lose the others' reports
        print(f"{_name}: report failed: {type(_e).__name__}: {_e}")
