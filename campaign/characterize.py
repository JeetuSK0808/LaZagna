# Cheap benchmark characterization: synthesis + pack only (no place, no route), to find which
# Koios designs actually exercise a FIXED 12.5 / 12.5 / 75 architecture.
#
# Why this exists. The 14 Aug placement study came back null on eltwise because eltwise uses
# 11 DSPs against 272 available slots, so hard-block placement had nothing to push against.
# The ratio is held constant by design (tuning it per benchmark is not a useful architecture),
# so the lever is benchmark CHOICE: run the placement study on designs whose hard-block demand
# actually fills the standard ratio. This measures that instead of guessing from design names.
#
# Runs VPR with --pack, which stops after packing and still reports block usage, so it costs
# synthesis plus packing rather than a full flow. Yosys is the RAM driver here, so give it the
# same memory as the hardblock phase.
#
# env: LAZAGNA_ROOT, WORK (default /work), CHAR_GRID (36), CHAR_CW (300),
#      CHAR_DESIGNS (space/comma separated; default a DSP- and BRAM-heavy shortlist)
import os
import re
import shutil
import sys

ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
WORK = os.environ.get("WORK", "/work")
GRID = int(os.environ.get("CHAR_GRID", "36"))
CW = int(os.environ.get("CHAR_CW", "300"))

os.chdir(ROOT)
sys.path.insert(0, ROOT)

from lazagna_arch_model import (ExperimentOptions, GridOptions, BenchmarkOptions,
                                PlacementOptions, SeedOptions, SwitchBlock3DOptions,
                                InterlayerDelayOptions, AdvancedOptions, run_lazagna)
from lazagna_optuna import SearchConfig, reference_columns, column_counts, build_architecture

DEFAULT_DESIGNS = [
    "eltwise_layer",      # the current subject, as the known-null reference point
    "conv_layer", "gemm_layer", "attention_layer", "reduction_layer",
    "dla_like.small", "tpu_like.small.os", "bwave_like.fixed.small",
    "clstm_like.small", "dnnweaver", "lenet", "bnn", "softmax", "spmv", "robot_rl",
]
_raw = os.environ.get("CHAR_DESIGNS", "")
DESIGNS = [d for d in re.split(r"[,\s]+", _raw) if d] or DEFAULT_DESIGNS

PB = re.compile(r"^\s*(io|clb|complex_dsp|spram|dsp)\s*:\s*(\d+)", re.M)


def bench_dir(design):
    """Single-design dir on the writable host work dir."""
    d = os.path.join(WORK, "bench", "char_" + design)
    dst = os.path.join(d, design + ".v")
    if not os.path.exists(dst):
        os.makedirs(d, exist_ok=True)
        src = os.path.join(ROOT, "benchmarks", "koios", design + ".v")
        if not os.path.exists(src):
            return None
        tmp = dst + ".tmp"
        shutil.copy(src, tmp)
        os.replace(tmp, dst)
    return d


def pack_counts(design):
    """Run synthesis + pack and pull the block usage out of VPR's log."""
    bdir = bench_dir(design)
    if bdir is None:
        return None, "source .v not found"

    cfg = SearchConfig(lazagna_root=ROOT, benchmark_dir=bdir, is_verilog=True,
                       width=GRID, height=GRID, width_2d=GRID + 8, height_2d=GRID + 8,
                       channel_width=CW, seeds=1, arch_type="combined",
                       search_mode="columns",
                       template_path="arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml")
    arch = build_architecture(reference_columns(cfg), GRID, GRID,
                              os.path.join(ROOT, cfg.template_path))
    opts = ExperimentOptions(
        experiment_name="char" + design.replace(".", ""),
        grid=GridOptions(width_3d=GRID, height_3d=GRID, width_2d=GRID + 8,
                         height_2d=GRID + 8, channel_width=CW),
        benchmarks=BenchmarkOptions(directory=bdir, is_verilog=True),
        placement=PlacementOptions(algorithm=["cube_bb"]),
        seeds=SeedOptions(mode="fixed", value=1),
        switch_block_3d=SwitchBlock3DOptions(connectivity=[1.0], connection_type=["subset"]),
        interlayer_delay=InterlayerDelayOptions(delay_ratio=[0.739]),
        advanced=AdvancedOptions(additional_vpr_options="--pack"),
    )
    opts.architectures[0].type = "combined"

    res = run_lazagna(arch, opts, lazagna_root=ROOT, timeout_s=cfg.trial_timeout_s)
    text = (res.get("stdout") or "") + (res.get("stderr") or "")
    counts = {k: int(v) for k, v in PB.findall(text)}
    if not counts:
        # fall back to the run's own log, since the task runner may swallow VPR stdout
        import glob
        logs = glob.glob(os.path.join(ROOT, "tasks_run", "**", "vpr_stdout.log"), recursive=True)
        logs = [l for l in logs if "char" + design.replace(".", "") in l]
        for l in sorted(logs, key=os.path.getmtime, reverse=True)[:1]:
            counts = {k: int(v) for k, v in PB.findall(open(l, errors="ignore").read())}
    if not counts:
        return None, (res.get("stderr") or "")[-300:]
    return counts, None


def main():
    n_clb, n_dsp, n_bram = column_counts(
        SearchConfig(lazagna_root=ROOT, benchmark_dir=".", width=GRID, height=GRID))
    rows_per_col, layers = GRID - 2, 2
    slots = {"clb": n_clb * rows_per_col * layers,
             "complex_dsp": n_dsp * rows_per_col * layers,
             "spram": n_bram * rows_per_col * layers}
    print(f"grid {GRID}x{GRID} cw{CW}, columns/layer CLB/DSP/BRAM = "
          f"{n_clb}/{n_dsp}/{n_bram}, slots {slots}", flush=True)
    print(f"{'design':28} {'CLB':>6} {'DSP':>5} {'BRAM':>6}   "
          f"{'CLB%':>6} {'DSP%':>6} {'BRAM%':>6}   note", flush=True)

    results = []
    for d in DESIGNS:
        counts, err = pack_counts(d)
        if counts is None:
            print(f"{d:28} {'-':>6} {'-':>5} {'-':>6}   failed: {err}", flush=True)
            continue
        c = counts.get("clb", 0)
        dsp = counts.get("complex_dsp", 0)
        br = counts.get("spram", 0)
        u = {k: 100.0 * v / slots[k] if slots[k] else 0.0
             for k, v in (("clb", c), ("complex_dsp", dsp), ("spram", br))}
        # A design is useful for the placement study when the hard blocks are actually
        # contended. Below roughly 20% the placer has too much slack for position to matter.
        worst_hb = min(u["complex_dsp"], u["spram"])
        note = "good" if worst_hb >= 20 else ("marginal" if worst_hb >= 10 else "too sparse")
        print(f"{d:28} {c:6d} {dsp:5d} {br:6d}   {u['clb']:5.1f}% "
              f"{u['complex_dsp']:5.1f}% {u['spram']:5.1f}%   {note}", flush=True)
        results.append((worst_hb, d, c, dsp, br, u))

    results.sort(reverse=True)
    print("\nRanked by hard-block contention (best candidates for the placement study):", flush=True)
    for worst_hb, d, c, dsp, br, u in results:
        print(f"  {d:28} min hard-block utilization {worst_hb:5.1f}%", flush=True)


if __name__ == "__main__":
    main()
