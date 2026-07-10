# Phase 2 — eltwise per-column Optuna search (search_mode="columns"), 36x36, cw150,
# dsp_bram+combined, constrained CLB-majority sampling, scored vs 3D-aligned reference.
# This is "% vs 3D-aligned reference", NOT "% over 2D" (that is phase_2dvs3d.py).
# argv: [seeds=3] [n_trials=35]
import os
import sys
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from lazagna_optuna import SearchConfig, run_study, report

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
N_TRIALS = int(sys.argv[2]) if len(sys.argv) > 2 else 35

cfg = SearchConfig(
    lazagna_root=ROOT,
    benchmark_dir=os.path.join(ROOT, "benchmarks", "koios_elt"),   # single-design eltwise dir
    is_verilog=True,
    width=36, height=36, width_2d=44, height_2d=44,
    channel_width=150, seeds=SEEDS,
    arch_type="combined", search_mode="columns",
    template_path="arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml",
    connectivity_choices=(1.0,),
    delay_ratio_range=(0.739, 0.739),
)

if __name__ == "__main__":
    # NOTE: needs benchmarks/koios_elt/eltwise_layer.v to exist in the image. It is a
    # single-design copy of benchmarks/koios/eltwise_layer.v; if absent, create it first
    # (cp). Flagged in EXPERIMENT_PLAN.md.
    elt = os.path.join(cfg.benchmark_dir, "eltwise_layer.v")
    if not os.path.exists(elt):
        os.makedirs(cfg.benchmark_dir, exist_ok=True)
        src = os.path.join(ROOT, "benchmarks", "koios", "eltwise_layer.v")
        if os.path.exists(src):
            import shutil
            shutil.copy(src, elt)
            print(f"created {elt} from {src}", flush=True)
        else:
            print(f"FATAL: eltwise_layer.v not found ({src}) - FLAG", flush=True)
            sys.exit(1)
    print(f"run_tag={cfg.run_tag} seeds={SEEDS} n_trials={N_TRIALS}", flush=True)
    study = run_study(cfg, n_trials=N_TRIALS, seed_named=False,
                      study_name="eltwise_columns",
                      storage=f"sqlite:///{ROOT}/eltwise_columns.db")
    report(study)
    print("PHASE2 DONE", flush=True)
