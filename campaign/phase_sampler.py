# Phase 1 — sampler comparison (clma, MCNC). TPE vs NSGA-II vs Random,
# identical connectivity search space + trial budget + 3 seeds. Raw (CPD, WL)
# minimize objective => measures sampler convergence (Ismael's parallel-optimizer q).
# argv: [n_trials=15] [seeds=3]
import os
import sys
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import time
import optuna
from optuna.samplers import TPESampler, NSGAIISampler, RandomSampler
from lazagna_optuna import SearchConfig, sample_connectivity, _run_one
from layout_space import NAMED_LAYOUTS

optuna.logging.set_verbosity(optuna.logging.WARNING)
N_TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 15
SEEDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
TAG = "smp" + str(int(time.time()))[-6:]

cfg = SearchConfig(
    lazagna_root=ROOT,
    benchmark_dir=os.path.join(ROOT, "benchmarks", "MCNC_benchmarks", "clma"),
    is_verilog=False,
    width=30, height=30, width_2d=42, height_2d=42,
    channel_width=100, seeds=SEEDS,
    arch_type="3d_sb", search_mode="connectivity",
    type_sb_choices=("3d_sb",),
)

SAMPLERS = {"tpe": TPESampler, "nsga2": NSGAIISampler, "random": RandomSampler}

def make_obj(name):
    def obj(trial):
        type_sb, conn, conn_type, delay = sample_connectivity(trial, cfg)
        metrics, err = _run_one(cfg, NAMED_LAYOUTS["aligned"], f"{TAG}{name}t{trial.number}",
                                type_sb, conn, delay, conn_type)
        if metrics is None:
            trial.set_user_attr("err", (err or "parse_failed")[:200])
            raise optuna.TrialPruned()
        cpd, wl = metrics
        for k, v in (("cpd", cpd), ("wl", wl), ("connectivity", conn), ("delay_ratio", delay)):
            trial.set_user_attr(k, v)
        print(f"[{name}] trial {trial.number}: cpd={cpd:.4e} wl={wl:.0f}", flush=True)
        return cpd, wl
    return obj

if __name__ == "__main__":
    print(f"TAG={TAG} n_trials={N_TRIALS} seeds={SEEDS}", flush=True)
    for name, cls in SAMPLERS.items():
        print(f"=== sampler {name} ===", flush=True)
        study = optuna.create_study(
            directions=["minimize", "minimize"], sampler=cls(),
            study_name=f"clma_sampler_{name}",
            storage=f"sqlite:///{ROOT}/clma_sampler_{name}.db", load_if_exists=True)
        study.optimize(make_obj(name), n_trials=N_TRIALS)
        done = [t for t in study.trials if t.values]
        if done:
            best = min(done, key=lambda t: t.values[0])
            print(f"  {name} BEST cpd={best.values[0]:.4e} wl={best.values[1]:.0f} "
                  f"(trial {best.number}, {len(done)}/{len(study.trials)} completed)", flush=True)
        else:
            print(f"  {name} NO completed trials (all pruned) - FLAG", flush=True)
    print("PHASE1 DONE", flush=True)
