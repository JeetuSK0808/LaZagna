# Multi-benchmark Optuna study, one instance per SLURM array task (suite_study.sbatch, started
# by campaign/suite_study.sh). Every trial evaluates ONE architecture on every design, each on
# its own autosized device and against its own aligned 3D reference, and scores the geometric
# mean of the per-design CPD / WL ratios (lazagna_optuna.make_suite_objective). All workers
# share the study through a JournalStorage file in /work/journal, as in worker.py, so N
# workers = N trials in flight. The analysis (Pareto front, Spearman, SHAP) is
# campaign/analyze_optuna.py, which the report job runs afterwards.
#
# env: DESIGNS       "<suite>/<design>" entries or whole suites, space/comma separated
#                    (default: koios/attention_layer vtr/stereovision1 koios/tpu_like.small.os,
#                    the designs of the single-design structured searches)
#      SEARCH_MODE   structured (default) | layout | connectivity
#      SAMPLER       tpe (default) | nsga2 | nsga3 | random | qmc
#      TRIALS        completed trials to collect, over all workers (default 40)
#      STUDY         study name (default suite_<mode>_<sampler>)
#      SEEDS (3), FIDELITY (route; place = VPR's placement estimate, faster), CW (300),
#      TALL (1), TARGET_UTIL (0.8)
#      CONN_CHOICES  3D switch-block connectivity values to sample, e.g. "0.25 0.5 1.0"
#                    (default: "1.0", i.e. fixed; in connectivity mode 0.1 ... 1.0)
#      VCONN_CHOICES share of each 3D switch block's channels that cross, e.g. "0.1 0.5 1.0"
#                    (default "1.0", fixed; structured and layout modes)
#      DELAY         inter-layer delay ratio: one value (default 0.739, fixed) or "lo,hi"
#      WEIGHTS       "" (default: two objectives, a Pareto front) or "w_cpd,w_wl" (one
#                    weighted objective); LINK_PENALTY: % points per unit of vertical links (0)
#      LINKS_OBJECTIVE  1: vertical links (link_fraction) as a third objective (default 0)
#      ANCHORS       1: the known layouts (lazagna_optuna.ANCHORS) as the first trials,
#                    queued once per study (structured mode; default 0)
#      NSGA_POP      population of the nsga2 / nsga3 samplers (default: Optuna's, 50)
#      WORKER_ID, WORK (/work), LAZAGNA_ROOT (/opt/LaZagna), LAZAGNA_CODE, KEEP_RRG
import json
import os
import re
import sys
import time

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
CODE = os.environ.get("LAZAGNA_CODE", ROOT)
WORK = os.environ.get("WORK", "/work")
WORKER_ID = int(os.environ.get("WORKER_ID", os.environ.get("SLURM_ARRAY_TASK_ID", "0")))


def _list(name, default):
    return [v for v in re.split(r"[,\s]+", os.environ.get(name, default)) if v]


def _flag(name):
    v = os.environ.get(name, "").strip()
    if v not in ("", "0", "1"):
        sys.exit(f"FATAL: {name} must be 0 or 1, not '{v}'")
    return v == "1"


DESIGNS = _list("DESIGNS", "koios/attention_layer vtr/stereovision1 koios/tpu_like.small.os")
SEARCH_MODE = os.environ.get("SEARCH_MODE", "structured")
SAMPLER = os.environ.get("SAMPLER", "tpe")
TRIALS = int(os.environ.get("TRIALS", "40"))
STUDY = os.environ.get("STUDY") or f"suite_{SEARCH_MODE}_{SAMPLER}"
SEEDS = int(os.environ.get("SEEDS", "3"))
FIDELITY = os.environ.get("FIDELITY", "route")
CW = int(os.environ.get("CW", "300"))
TALL = os.environ.get("TALL", "1") != "0"
TARGET_UTIL = float(os.environ.get("TARGET_UTIL", "0.8"))
CONN_CHOICES = tuple(float(v) for v in _list("CONN_CHOICES", ""))
_delay = [float(v) for v in _list("DELAY", "0.739")]
DELAY_RANGE = (_delay[0], _delay[-1])
WEIGHTS = tuple(float(v) for v in _list("WEIGHTS", ""))
LINK_PENALTY = float(os.environ.get("LINK_PENALTY", "0") or 0)
VCONN_CHOICES = tuple(float(v) for v in _list("VCONN_CHOICES", ""))
LINKS_OBJECTIVE = _flag("LINKS_OBJECTIVE")
ANCHORS = _flag("ANCHORS")
NSGA_POP = int(os.environ["NSGA_POP"]) if os.environ.get("NSGA_POP", "").strip() else None
KEEP_RRG = bool(os.environ.get("KEEP_RRG"))

os.chdir(ROOT)
sys.path[:0] = [CODE, ROOT]   # host code first (see campaign/binds.sh)

import optuna
from lazagna_optuna import (SearchConfig, make_suite_objective, design_configs, _make_sampler,
                            journal_storage, n_objectives, enqueue_named_layouts, prepare,
                            column_counts, enqueue_anchors)

optuna.logging.set_verbosity(optuna.logging.WARNING)

COUNTED = (optuna.trial.TrialState.RUNNING, optuna.trial.TrialState.COMPLETE,
           optuna.trial.TrialState.PRUNED, optuna.trial.TrialState.FAIL)


def config() -> SearchConfig:
    """The study's settings: the lab's standard architecture (combined 3D switch blocks, cw 300,
    75/12.5/12.5 columns, tall DSP/BRAM templates), as in worker.py and experiment.py."""
    tdir = "dsp_bram_tall" if TALL else "dsp_bram"
    return SearchConfig(
        lazagna_root=ROOT, benchmark_dir="", benchmarks=tuple(DESIGNS),
        channel_width=CW, seeds=SEEDS, seed_list=tuple(range(1, SEEDS + 1)),
        arch_type="combined", search_mode=SEARCH_MODE, sampler=SAMPLER, parallel=True,
        type_sb_choices=("combined",),
        connectivity_choices=CONN_CHOICES or (1.0,), delay_ratio_range=DELAY_RANGE,
        fine_connectivity_choices=CONN_CHOICES or SearchConfig.fine_connectivity_choices,
        objective_weights=WEIGHTS, link_penalty=LINK_PENALTY,
        vertical_connectivity_choices=VCONN_CHOICES or (1.0,), links_objective=LINKS_OBJECTIVE,
        anchors=ANCHORS, nsga_population=NSGA_POP,
        template_path=f"arch_files/templates/{tdir}/vtr_arch_dsp_bram.xml",
        template_2d_path=f"arch_files/templates/{tdir}/vtr_2d_arch_dsp_bram.xml",
        fidelity=FIDELITY, prep_dir="/prep", stage_dir=WORK, target_util=TARGET_UTIL,
        run_tag="s",
    )


def settings(cfg: SearchConfig, designs) -> dict:
    s = {"designs": [e for e, _ in designs], "search_mode": cfg.search_mode, "sampler": cfg.sampler,
         "seeds": len(cfg.seed_list), "fidelity": cfg.fidelity, "channel_width": cfg.channel_width,
         "tall": TALL, "target_util": cfg.target_util, "arch_type": cfg.arch_type,
         "connectivity_choices": list(cfg.fine_connectivity_choices if cfg.search_mode == "connectivity"
                                      else cfg.connectivity_choices),
         "delay_ratio_range": list(cfg.delay_ratio_range),
         "objective_weights": list(cfg.objective_weights), "link_penalty": cfg.link_penalty}
    # Newer options are recorded only when set, so a default study's attrs are as before.
    if tuple(cfg.vertical_connectivity_choices) != (1.0,):
        s["vertical_connectivity_choices"] = list(cfg.vertical_connectivity_choices)
    if cfg.links_objective:
        s["links_objective"] = True
    if cfg.anchors:
        s["anchors"] = True
    if cfg.nsga_population is not None:
        s["nsga_population"] = cfg.nsga_population
    return s


def open_study(cfg: SearchConfig, designs) -> optuna.Study:
    storage = journal_storage(os.path.join(WORK, "journal", f"{STUDY}.log"))
    study = optuna.create_study(directions=["minimize"] * n_objectives(cfg), study_name=STUDY,
                                storage=storage, load_if_exists=True, sampler=_make_sampler(cfg))
    if "designs" not in study.user_attrs:
        for k, v in settings(cfg, designs).items():
            study.set_user_attr(k, v)
    elif study.user_attrs["designs"] != [e for e, _ in designs]:
        sys.exit(f"FATAL: study {STUDY} in {WORK} was started with designs {study.user_attrs['designs']}; "
                 f"use another STUDY or WORK_ROOT for {[e for e, _ in designs]}")
    return study


def write_designs(designs) -> None:
    """designs.json: each design's staged copy, devices and measured block demand."""
    rows = []
    for e, sub in designs:
        rows.append({"design": e, "bench_dir": sub.benchmark_dir, "demand": prepare(sub).get("demand"),
                     "device_2d": [sub.width_2d, sub.height_2d], "device_3d": [2, sub.width, sub.height],
                     "cols_per_layer_3d": list(column_counts(sub))})
    path = os.path.join(WORK, "designs.json")
    with open(path + ".tmp", "w") as f:
        json.dump(rows, f, indent=1)
    os.replace(path + ".tmp", path)


def clean_rrg() -> None:
    """RRGs only pay off within a trial; across trials they are dead weight (GBs per trial).
    The dirs are per-worker binds, nothing else reads them (same as worker.py)."""
    if KEEP_RRG:
        return
    for d in ("rrg_3d", "base_rrg"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            for f in os.listdir(p):
                try:
                    os.remove(os.path.join(p, f))
                except OSError:
                    pass


def queue_anchors_once(study: optuna.Study, cfg: SearchConfig) -> None:
    """The anchors go in exactly once per study, however many workers share it and in whatever
    order SLURM starts them: the first worker to create journal/<study>.anchors (O_EXCL, atomic
    on the shared filesystem, as for the reference lock files) queues them before it runs a
    trial; every other worker, and any later restart, finds the file and queues nothing.
    enqueue_anchors() itself also skips a study that already has seeded trials."""
    lock = os.path.join(WORK, "journal", f"{STUDY}.anchors")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return
    try:
        names = enqueue_anchors(study, cfg)
    except BaseException:       # e.g. a setting the anchors refuse: the next worker gets the same error
        os.close(fd)
        os.remove(lock)
        raise
    with os.fdopen(fd, "w") as f:
        f.write(" ".join(names) + "\n")
    print(f"[w{WORKER_ID}] queued anchors: {', '.join(names) or 'none (no anchor fits the search space)'}",
          flush=True)


def contribute(study: optuna.Study, objective, target: int) -> None:
    """Trials until `target` are complete (or running) over all workers. Pruned and failed
    trials don't use up the budget, but attempts are capped at 3x target."""
    def count(states):
        return sum(1 for t in study.get_trials(deepcopy=False) if t.state in states)
    useful = (optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.RUNNING)
    while count(useful) < target and count(COUNTED) < 3 * target:
        try:
            study.optimize(objective, n_trials=1)
        except Exception as e:  # one bad trial must not kill the worker
            print(f"[w{WORKER_ID}] trial errored: {type(e).__name__}: {e}", flush=True)
        clean_rrg()
        print(f"[w{WORKER_ID}] {count(COUNTED)} started, "
              f"{count((optuna.trial.TrialState.COMPLETE,))}/{target} complete", flush=True)


def main() -> None:
    os.makedirs(os.path.join(WORK, "journal"), exist_ok=True)
    time.sleep(WORKER_ID * 3)   # stagger startup so the workers don't hit the locks at once
    cfg = config()
    extra = [(k, v) for k, v in (("vconn_choices", VCONN_CHOICES), ("links_objective", LINKS_OBJECTIVE),
                                 ("anchors", ANCHORS), ("nsga_pop", NSGA_POP)) if v]
    print(f"[w{WORKER_ID}] study {STUDY}: designs={DESIGNS} mode={SEARCH_MODE} sampler={SAMPLER} "
          f"trials={TRIALS} seeds={SEEDS} fidelity={FIDELITY} weights={WEIGHTS or 'pareto'} "
          f"link_penalty={LINK_PENALTY}" + "".join(f" {k}={v}" for k, v in extra), flush=True)
    # Stages, synthesizes + packs (once, shared /prep cache) and sizes every design.
    designs = design_configs(cfg)
    for e, sub in designs:
        print(f"[w{WORKER_ID}] {e}: 2D {sub.width_2d}x{sub.height_2d}, 3D 2x{sub.width}x{sub.height}, "
              f"cols/layer CLB/DSP/BRAM={column_counts(sub)}", flush=True)
    study = open_study(cfg, designs)
    if WORKER_ID == 0:
        write_designs(designs)
        # The paper's named layouts first (they use connectivity 1.0 and delay 0.739).
        if (SEARCH_MODE == "layout" and not study.get_trials(deepcopy=False)
                and 1.0 in cfg.connectivity_choices and DELAY_RANGE[0] <= 0.739 <= DELAY_RANGE[1]):
            enqueue_named_layouts(study, cfg)
    if ANCHORS:
        queue_anchors_once(study, cfg)
    objective = make_suite_objective(cfg, designs=designs,
                                     baseline_dir=os.path.join(WORK, "journal", "baselines"))
    contribute(study, objective, TRIALS)
    print(f"[w{WORKER_ID}] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
