# Collect verified campaign results into one markdown summary. Enforces the gate: only
# counts runs whose vpr_stdout.log says "VPR succeeded" with real CPD/WL. Dedups symlinked
# logs, groups a config's seed runs and reports the geomean, reads per-study sqlite DBs.
# Safe to run after a partial campaign.
# argv: [out=/summary/campaign_summary.md]
import os
import re
import sys
import glob
import math
import sqlite3

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/summary/campaign_summary.md"

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
    groups = {}          # config key -> list of per-seed results
    seen = set()         # realpaths, to drop symlink duplicates
    for lp in glob.glob(os.path.join(ROOT, "tasks_run", "**", "vpr_stdout.log"), recursive=True):
        rp = os.path.realpath(lp)
        if rp in seen:
            continue
        seen.add(rp)
        r = parse_vpr(lp)
        if not r:
            continue
        # folder: 3d_<type>_cw_<cw>_<WxH>_..._<cur_loop_identifier>_vp_<delay>_run<N>_<ts>
        folder = os.path.basename(lp.split("/task_")[0])
        key = folder.split("_vp_")[0]        # config (drops delay/seed/timestamp)
        groups.setdefault(key, []).append(r)
    return groups

def study_summary(db):
    if not os.path.exists(db):
        return None
    c = sqlite3.connect(db)
    trials = c.execute("select number,state from trials").fetchall()
    done = sum(1 for _, s in trials if s == "COMPLETE")
    by_trial = {}
    for tid, obj, val in c.execute("select trial_id,objective,value from trial_values").fetchall():
        by_trial.setdefault(tid, {})[obj] = val
    best = None
    for ov in by_trial.values():
        if 0 in ov and (best is None or ov[0] < best[0]):
            best = (ov[0], ov.get(1))
    return {"total": len(trials), "complete": done, "best": best}

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

    lines += ["", f"Total verified configs: {len(groups)}", "", "## Study DBs (Optuna)", ""]
    for name, db in [("eltwise_columns", "eltwise_columns.db"),
                     ("clma_sampler_tpe", "clma_sampler_tpe.db"),
                     ("clma_sampler_nsga2", "clma_sampler_nsga2.db"),
                     ("clma_sampler_random", "clma_sampler_random.db")]:
        s = study_summary(os.path.join(ROOT, db))
        if s is None:
            lines.append(f"- **{name}**: (no DB)")
        elif s["best"]:
            lines.append(f"- **{name}**: {s['complete']}/{s['total']} complete; "
                         f"best CPD-obj={s['best'][0]:.4e}, WL-obj={s['best'][1]}")
        else:
            lines.append(f"- **{name}**: {s['complete']}/{s['total']} complete; NO completed trials - FLAG")

    lines += ["", "## Notes",
              "- 3D-vs-2D % (Phase 3) and sampler bests are in the SLURM stdout (campaign_<jobid>.out):",
              "  grep IMPROVEMENT / BEST / FLAG.",
              "- Any CPD/WL improvement outside ~0-16% => suspect contamination/degenerate; verify."]
    open(OUT, "w").write("\n".join(lines) + "\n")
    print(f"wrote {OUT}: {len(groups)} verified configs", flush=True)

if __name__ == "__main__":
    main()
