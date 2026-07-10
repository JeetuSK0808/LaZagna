# Phase 4 — reattempt conv_layer + lstm (OOM-killed Yosys at ~7 GB on the 6.8 GB laptop;
# cluster RAM should let synthesis complete). Runs each through the real flow at a grid; the
# run's yosys log gives cell counts (DSP/BRAM/CLB) and the VPR log the fit/route outcome, which
# collect_results.py picks up. Continue-on-failure so one bad design doesn't stop the phase.
#
# CONFIRM: conv_layer/lstm post-synthesis sizes are unknown, so GRID/CW are conservative guesses.
# conv_layer has 32-bit (BRAM-mappable) memories + multipliers -> promising. lstm has 1600-bit
# memories that did NOT map to the 40-bit spram on the laptop (soft explosion) -> may not fit
# even with cluster RAM (a mapping limit, not a RAM limit). Treat lstm as exploratory.
# argv: [seeds=1]  (synth/fit check; multi-seed studies come later if a design proves viable)
import os
import sys
import subprocess
import shutil
ROOT = os.environ.get("LAZAGNA_ROOT", "/opt/LaZagna")
os.chdir(ROOT)
sys.path.insert(0, ROOT)

SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 1
GRID = int(os.environ.get("HB_GRID", "44"))     # CONFIRM
CW = int(os.environ.get("HB_CW", "150"))        # CONFIRM
W2D = GRID + 8
DESIGNS = ["conv_layer", "lstm"]

# v2 nested schema (yaml_file_processing_v2). See setup_files/defaults.yaml.
CONFIG_TMPL = """experiment_name: "hb_{name}"
grid:
  width_3d: {g}
  height_3d: {g}
  width_2d: {w2d}
  height_2d: {w2d}
  channel_width: {cw}
architectures:
  - type: "combined"
    arch_file: "{{lazagna_root}}/arch_files/templates/dsp_bram/vtr_arch_dsp_bram.xml"
benchmarks:
  directory: "{{lazagna_root}}/benchmarks/hb_{name}"
  is_verilog: true
placement:
  algorithm: ["cube_bb"]
seeds:
  mode: fixed
  value: 1
switch_block_3d:
  connectivity: [1]
  connection_type: ["subset"]
  switch_name: "3D_SB_switch"
  segment_name: "3D_SB_connection"
  location_pattern: ["repeated_interval"]
interlayer_delay:
  vertical_connectivity: 1
  delay_ratio: [0.739]
  base_delay_switch: "L4_driver"
  update_arch_delay: true
  switch_pairs:
    L4_driver: "L4_inter_layer_driver"
    L16_driver: "L16_inter_layer_driver"
    ipin_cblock: "ipin_inter_layer_cblock"
advanced:
  additional_vpr_options: ""
"""

if __name__ == "__main__":
    print(f"GRID={GRID} CW={CW} seeds={SEEDS}", flush=True)
    for d in DESIGNS:
        src = os.path.join(ROOT, "benchmarks", "koios", f"{d}.v")
        if not os.path.exists(src):
            print(f"[{d}] source missing ({src}) - FLAG, skipping", flush=True); continue
        bdir = os.path.join(ROOT, "benchmarks", f"hb_{d}")
        os.makedirs(bdir, exist_ok=True)
        shutil.copy(src, os.path.join(bdir, f"{d}.v"))
        cfgp = os.path.join(ROOT, "setup_files", f"hb_{d}.yaml")
        with open(cfgp, "w") as f:
            f.write(CONFIG_TMPL.format(g=GRID, w2d=W2D, cw=CW, seeds=SEEDS, name=d))
        print(f"=== {d}: flow at {GRID}x{GRID} cw{CW} (synth may be RAM-heavy) ===", flush=True)
        r = subprocess.run(["python3", os.path.join(ROOT, "lazagna", "main.py"), "-f", cfgp, "-v"],
                           capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()[-4:]
        print(f"[{d}] rc={r.returncode}; tail: {' | '.join(tail)}", flush=True)
        print(f"[{d}] check run folder yosys_output.log for cell counts, vpr_stdout.log for fit/route.", flush=True)
    print("PHASE4 DONE (see collect_results for parsed outcomes)", flush=True)
