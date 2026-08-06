# Collect verified campaign results into one markdown summary. Enforces the gate: only
# counts runs whose vpr_stdout.log says "VPR succeeded" with real CPD/WL. Dedups symlinked
# logs, groups a config's seed runs and reports the geomean. Reads the optuna studies from
# the JournalStorage files in <work>/journal (sqlite is gone — it died on Lustre with
# 'disk I/O error' in run 11659291). Safe to run after a partial campaign.
# argv: [out=<work>/campaign_summary.md] [work_root=/work]
import os
import re
import sys
import glob
import math

WORK = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WORK", "/work")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, "campaign_summary.md")
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
sys.path.insert(0, ROOT)  # for lazagna_optuna.journal_storage

CPD = re.compile(r"Final critical path delay \(least slack\):\s*([\d.eE+-]+)\s*ns")
WL = re.compile(r"Total wirelength:\s*(\d+)")
PB = re.compile(r"^\s*(io|clb|complex_dsp|spram|dsp)\s*:\s*(\d+)", re.M)


def parse_vpr(path):
    try:
        t = open(path, errors="ignore").read()
    except OSError:
        return None
    if "VPR succeeded" not in t:
        return None
    mc, mw = CPD.search(t), WL.search(t)
    if not (mc and mw):
        return None
    return {"cpd_ns": float(mc.group(1)), "wl": float(mw.group(1)),
            "blocks": {k: int(v) for k, v in PB.findall(t)}}


def geomean(xs):
    xs = [x for x in xs if x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def collect_vpr():
    """Walk every worker's (and the extras job's) tasks_run under the work root."""
    groups = {}
    seen = set()
    for lp in glob.glob(os.path.join(WORK, "*", "tasks_run", "**", "vpr_stdout.log"),
                        recursive=True):
        rp = os.path.realpath(lp)
        if rp in seen:
            continue
        seen.add(rp)
        r = parse_vpr(lp)
        if not r:
            continue
        # folder: 3d_<type>_cw_<cw>_<WxH>_..._<experiment_name>_vp_<delay>_run<N>_<ts>
        folder = os.path.basename(lp.split("/task_")[0])
        key = folder.split("_vp_")[0]
        groups.setdefault(key, []).append(r)
    return groups


def study_summary(name):
    path = os.path.join(WORK, "journal", f"{name}.log")
    if not os.path.exists(path):
        return None
    import optuna
    from lazagna_optuna import journal_storage
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        study = optuna.load_study(study_name=name, storage=journal_storage(path))
    except Exception as e:
        return {"error": str(e)[:200]}
    trials = study.get_trials(deepcopy=False)
    done = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
    out = {"total": len(trials), "complete": len(done),
           "baseline_cpd": study.user_attrs.get("baseline_cpd"),
           "baseline_wl": study.user_attrs.get("baseline_wl"), "best": None}
    if done:
        # objectives are (-cpd_impr%, -wl_impr%): smaller = better
        b = min(done, key=lambda t: t.values[0])
        out["best"] = {"trial": b.number,
                       "cpd_impr_pct": b.user_attrs.get("cpd_impr_pct"),
                       "wl_impr_pct": b.user_attrs.get("wl_impr_pct"),
                       "cpd_raw": b.user_attrs.get("cpd_raw"),
                       "wl_raw": b.user_attrs.get("wl_raw")}
    return out


def main():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    groups = collect_vpr()
    lines = ["# Campaign Results Summary", "",
             "Only `VPR succeeded` runs with real CPD/WL (verification gate). Per config: geomean",
             "over its seed runs.", "",
             "## Per-config VPR results (verified, seed-geomean)", "",
             "| config (folder before _vp_) | seeds | CPD geomean (ns) | WL geomean | clb | complex_dsp | spram | io |",
             "|---|---|---|---|---|---|---|---|"]
    for key in sorted(groups):
        rs = groups[key]
        b = rs[0]["blocks"]
        lines.append(f"| {key} | {len(rs)} | {geomean([r['cpd_ns'] for r in rs]):.4f} | "
                     f"{geomean([r['wl'] for r in rs]):.0f} | {b.get('clb','-')} | "
                     f"{b.get('complex_dsp','-')} | {b.get('spram','-')} | {b.get('io','-')} |")
    if not groups:
        lines.append("| (none succeeded yet) | | | | | | | |")

    lines += ["", f"Total verified configs: {len(groups)}", "", "## Optuna studies (journal)", ""]
    for name in ("eltwise_columns", "clma_sampler_tpe", "clma_sampler_nsga2", "clma_sampler_random"):
        s = study_summary(name)
        if s is None:
            lines.append(f"- **{name}**: (no journal)")
        elif "error" in s:
            lines.append(f"- **{name}**: load error: {s['error']} - FLAG")
        elif s["best"]:
            bb = s["best"]
            cpd_i = bb["cpd_impr_pct"]; wl_i = bb["wl_impr_pct"]
            cpd_s = f"{cpd_i:+.2f}%" if cpd_i is not None else "?"
            wl_s = f"{wl_i:+.2f}%" if wl_i is not None else "?"
            lines.append(f"- **{name}**: {s['complete']}/{s['total']} complete; best trial "
                         f"{bb['trial']}: CPD {cpd_s}, WL {wl_s} vs reference "
                         f"(baseline CPD={s['baseline_cpd']}, WL={s['baseline_wl']})")
        else:
            lines.append(f"- **{name}**: {s['complete']}/{s['total']} complete; "
                         f"NO completed trials - FLAG")

    lines += ["", "## Notes",
              "- 3D-vs-2D % (Phase 3) is in the extras job stdout (extras_<jobid>.out): grep IMPROVEMENT.",
              "- Improvements are vs the 3D-aligned reference (study user attrs), NOT vs 2D.",
              "- Any improvement outside ~0-16% => suspect contamination/degenerate; verify."]
    open(OUT, "w").write("\n".join(lines) + "\n")
    print(f"wrote {OUT}: {len(groups)} verified configs", flush=True)


if __name__ == "__main__":
    main()
