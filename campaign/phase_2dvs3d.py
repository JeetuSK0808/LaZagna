# Phase 3 — eltwise TRUE 2D-vs-3D at the channel width the 2D arch needs (paper headline:
# % improvement of 3D over a real 1-layer 2D baseline). Cluster priority (laptop OOM'd here).
#
# Approach: instead of a fragile standalone min-W probe, auto-find a routable cw by trying an
# ascending list; the first cw at which the 1-layer 2D arch routes eltwise is used for BOTH the
# 2D baseline and the 3D run (same cw = fair comparison). cw list overridable via CW env
# (e.g. CW=300). The chosen cw is a REASONED value (2D was unroutable at cw150 on the laptop);
# CONFIRM it is sensible for the paper.
# argv: [seeds=3]
import os
import sys
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from lazagna_optuna import SearchConfig, _run_one
from layout_space import NAMED_LAYOUTS

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CW_ENV = os.environ.get("CW")
CW_CANDIDATES = [int(CW_ENV)] if CW_ENV else [200, 300, 400]
TAG = "e2d3d"

cfg = SearchConfig(
    lazagna_root=ROOT,
    benchmark_dir=os.path.join(ROOT, "benchmarks", "koios_elt"),
    is_verilog=True,
    width=36, height=36, width_2d=44, height_2d=44,
    channel_width=200, seeds=SEEDS,
    arch_type="combined", search_mode="columns",
    template_path="arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml",
    template_2d_path="arch_files/templates/dsp_bram/vtr_2d_arch_dsp_bram.xml",
    connectivity_choices=(1.0,),
)

def ensure_eltwise():
    elt = os.path.join(cfg.benchmark_dir, "eltwise_layer.v")
    if not os.path.exists(elt):
        os.makedirs(cfg.benchmark_dir, exist_ok=True)
        src = os.path.join(ROOT, "benchmarks", "koios", "eltwise_layer.v")
        if not os.path.exists(src):
            print(f"FATAL: {src} missing - FLAG", flush=True); sys.exit(1)
        import shutil; shutil.copy(src, elt)

if __name__ == "__main__":
    ensure_eltwise()
    aligned = NAMED_LAYOUTS["aligned"]

    # --- find a cw at which the real 1-layer 2D arch routes eltwise ---
    base = None
    chosen_cw = None
    for cw in CW_CANDIDATES:
        cfg.channel_width = cw
        print(f"[2D baseline] trying cw={cw} ...", flush=True)
        m, err = _run_one(cfg, aligned, f"{TAG}base{cw}", "2d", 1.0, 0.739)
        if m is not None:
            base = m; chosen_cw = cw
            print(f"[2D baseline] routed at cw={cw}: CPD={m[0]:.4e} WL={m[1]:.0f}", flush=True)
            break
        print(f"[2D baseline] cw={cw} did not route/parse: {(err or '')[:120]}", flush=True)
    if base is None:
        print("FATAL: 2D baseline unroutable at all candidate cw - FLAG, needs higher cw", flush=True)
        sys.exit(1)

    # --- 3D run at the SAME cw (fair comparison), aligned 3D layout ---
    cfg.channel_width = chosen_cw
    print(f"[3D] running aligned 3D at cw={chosen_cw} ...", flush=True)
    m3, err3 = _run_one(cfg, aligned, f"{TAG}threed{chosen_cw}", "combined", 1.0, 0.739)
    if m3 is None:
        print(f"FATAL: 3D run failed at cw={chosen_cw}: {(err3 or '')[:120]} - FLAG", flush=True)
        sys.exit(1)

    bcpd, bwl = base; cpd, wl = m3
    cpd_impr = 100.0 * (bcpd - cpd) / bcpd
    wl_impr = 100.0 * (bwl - wl) / bwl
    print("==== PHASE 3 RESULT (3D vs true 2D) ====", flush=True)
    print(f"cw={chosen_cw} seeds={SEEDS}", flush=True)
    print(f"2D baseline: CPD={bcpd:.4e} s  WL={bwl:.0f}", flush=True)
    print(f"3D aligned : CPD={cpd:.4e} s  WL={wl:.0f}", flush=True)
    print(f"IMPROVEMENT: CPD {cpd_impr:+.2f}%   WL {wl_impr:+.2f}%", flush=True)
    if not (-2 <= cpd_impr <= 20 and -2 <= wl_impr <= 20):
        print("FLAG: improvement outside believable ~0-16% band; check for contamination/degenerate run", flush=True)
    print("PHASE3 DONE", flush=True)
