# Campaign worker — one instance per SLURM array task. All workers share the optuna studies
# through JournalStorage files on the host work dir (/work/journal), so N workers = N trials
# in flight with no sqlite and no shared-writable overlay (both failed on PACE run 11659291:
# 'sqlite3.OperationalError: disk I/O error' + 50 GB overlay filled -> ENOSPC).
#
# Each worker loops over the study queue in order and contributes single trials until a study
# reaches its target trial count, then moves on. TPE runs with constant_liar=True so parallel
# workers do not pile onto the same point. The reference-baseline run is computed once per
# study (first worker claims it via study user attrs; the rest poll — see make_objective).
#
# env: WORKER_ID, WORK (default /work), LAZAGNA_ROOT (default /opt/LaZagna),
#      SEEDS (3), TRIALS_COLUMNS (35), TRIALS_SAMPLER (15), STUDIES (default "columns tpe nsga2 random"),
#      KEEP_RRG (unset -> per-trial RRG cleanup on)
import os
import shutil
import sys
import time

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
WORK = os.environ.get("WORK", "/work")
WORKER_ID = int(os.environ.get("WORKER_ID", os.environ.get("SLURM_ARRAY_TASK_ID", "0")))
SEEDS = int(os.environ.get("SEEDS", "3"))
TRIALS_COLUMNS = int(os.environ.get("TRIALS_COLUMNS", "35"))
TRIALS_SAMPLER = int(os.environ.get("TRIALS_SAMPLER", "15"))
STUDIES = os.environ.get("STUDIES", "columns tpe nsga2 random").split()
KEEP_RRG = bool(os.environ.get("KEEP_RRG"))

os.chdir(ROOT)
sys.path.insert(0, ROOT)

import optuna
from lazagna_optuna import SearchConfig, make_objective, _make_sampler, journal_storage

# Stale-image guard: these features live inside the image (/opt/LaZagna). If Ismael reuses an
# old lazagna.sif, fail loud instead of crashing cryptically mid-run.
import inspect
if "study" not in inspect.signature(make_objective).parameters:
    sys.exit("IMAGE STALE: /opt/LaZagna in this .sif predates the parallel-campaign update. "
             "Delete lazagna.sif and resubmit (submit_campaign.sh rebuilds it).")

optuna.logging.set_verbosity(optuna.logging.WARNING)


def ensure_bench(name: str, src_rel: str) -> str:
    """Single-design benchmark dir on the HOST work dir (container benchmarks/ is read-only)."""
    bdir = os.path.join(WORK, "bench", name)
    dst = os.path.join(bdir, os.path.basename(src_rel))
    if not os.path.exists(dst):
        os.makedirs(bdir, exist_ok=True)
        src = os.path.join(ROOT, src_rel)
        if not os.path.exists(src):
            sys.exit(f"FATAL: benchmark source missing: {src}")
        tmp = dst + f".w{WORKER_ID}.tmp"
        shutil.copy(src, tmp)
        os.replace(tmp, dst)  # atomic vs racing workers
    return bdir


def columns_cfg() -> SearchConfig:
    return SearchConfig(
        lazagna_root=ROOT,
        benchmark_dir=ensure_bench("koios_elt", "benchmarks/koios/eltwise_layer.v"),
        is_verilog=True,
        width=36, height=36, width_2d=44, height_2d=44,
        channel_width=150, seeds=SEEDS,
        arch_type="combined", search_mode="columns",
        template_path="arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml",
        connectivity_choices=(1.0,),
        delay_ratio_range=(0.739, 0.739),
        parallel=True,
        run_tag="cols",
    )


def sampler_cfg(sampler: str) -> SearchConfig:
    return SearchConfig(
        lazagna_root=ROOT,
        benchmark_dir=os.path.join(ROOT, "benchmarks", "MCNC_benchmarks", "clma"),
        is_verilog=False,
        width=30, height=30, width_2d=42, height_2d=42,
        channel_width=100, seeds=SEEDS,
        arch_type="3d_sb", search_mode="connectivity",
        type_sb_choices=("3d_sb",),
        sampler=sampler, parallel=True,
        run_tag=f"smp{sampler}",
    )


STUDY_DEFS = {
    "columns": dict(cfg=columns_cfg, target=TRIALS_COLUMNS, study="eltwise_columns"),
    "tpe":     dict(cfg=lambda: sampler_cfg("tpe"),    target=TRIALS_SAMPLER, study="clma_sampler_tpe"),
    "nsga2":   dict(cfg=lambda: sampler_cfg("nsga2"),  target=TRIALS_SAMPLER, study="clma_sampler_nsga2"),
    "random":  dict(cfg=lambda: sampler_cfg("random"), target=TRIALS_SAMPLER, study="clma_sampler_random"),
}

COUNTED = (optuna.trial.TrialState.RUNNING, optuna.trial.TrialState.COMPLETE,
           optuna.trial.TrialState.PRUNED, optuna.trial.TrialState.FAIL)


def n_started(study) -> int:
    return sum(1 for t in study.get_trials(deepcopy=False) if t.state in COUNTED)


def clean_rrg():
    if KEEP_RRG:
        return
    # RRG cache only pays off WITHIN one flow invocation (3 seeds reuse it); across trials the
    # content-hashed arch name changes, so old RRGs are dead weight (~1-3 GB per trial — this is
    # what filled the 50 GB overlay). The dirs are per-worker binds, nothing else reads them.
    for d in ("rrg_3d", "base_rrg"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            for f in os.listdir(p):
                try:
                    os.remove(os.path.join(p, f))
                except OSError:
                    pass


def contribute(key: str) -> None:
    sd = STUDY_DEFS[key]
    cfg = sd["cfg"]()
    storage = journal_storage(os.path.join(WORK, "journal", f"{sd['study']}.log"))
    study = optuna.create_study(directions=["minimize", "minimize"], study_name=sd["study"],
                                storage=storage, load_if_exists=True, sampler=_make_sampler(cfg))
    objective = make_objective(cfg, study=study)
    while n_started(study) < sd["target"]:
        try:
            study.optimize(objective, n_trials=1)
        except Exception as e:  # one bad trial must not kill the worker
            print(f"[w{WORKER_ID}] {key}: trial errored: {e}", flush=True)
        clean_rrg()
        done = [t for t in study.get_trials(deepcopy=False)
                if t.state == optuna.trial.TrialState.COMPLETE]
        print(f"[w{WORKER_ID}] {key}: {n_started(study)}/{sd['target']} started, "
              f"{len(done)} complete", flush=True)
    print(f"[w{WORKER_ID}] {key}: target reached, moving on", flush=True)


if __name__ == "__main__":
    os.makedirs(os.path.join(WORK, "journal"), exist_ok=True)
    time.sleep(WORKER_ID * 3)  # stagger startup so 16 workers don't hammer the lock at once
    print(f"[w{WORKER_ID}] start: studies={STUDIES} seeds={SEEDS} "
          f"targets: columns={TRIALS_COLUMNS} sampler={TRIALS_SAMPLER}", flush=True)
    for key in STUDIES:
        if key not in STUDY_DEFS:
            print(f"[w{WORKER_ID}] unknown study '{key}' (skipping)", flush=True)
            continue
        contribute(key)
    print(f"[w{WORKER_ID}] ALL DONE", flush=True)
