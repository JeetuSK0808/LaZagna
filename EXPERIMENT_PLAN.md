# LaZagna Cluster Campaign — Experiment Plan

Proposed campaign that `run_campaign.sbatch` executes end-to-end in the container. Purposeful,
not a brute-force sweep: every phase advances the paper (% over 2D, placement effects, sampler
efficiency, wider hard-block benchmark set). Ordered cheap-validation-first so breakage surfaces
in minutes. Each phase confidence-tagged; **CONFIRM** = Ismael should check before submitting.

Verification gate (all phases): a result counts only if its `vpr_stdout.log` shows
`VPR succeeded` with non-zero CPD/WL and sane block counts. `collect_results.py` enforces this
and flags anything outside a believable 0-16% improvement band.

Standing choices: 3 seeds everywhere (seed noise is real; the laptop work showed single-seed
numbers inflate). BLIF benchmarks (clma) skip synthesis; Verilog (eltwise/conv/lstm) synthesize
(the RAM-heavy step the laptop died on).

---

## Phase 0 — Smoke test (fail-fast) — CONFIDENT
- **What:** clma, BLIF, cw100, 30x30, 1 config, 1 seed (`main.py -f setup_files/simple_test.yaml`
  or a clma connectivity single-trial).
- **Why:** proves the container flow (Yosys/VPR/optimizer + writable overlay + binds) works
  before spending accounted hours. If this fails, the job dies in ~10 min, not after hours.
- **Resources:** ~10-20 min, 4 cores, 8 GB.
- **Success:** `VPR succeeded`, CPD/WL parse to real numbers.

## Phase 1 — Sampler comparison (light, MCNC) — CONFIDENT (one caveat)
- **What:** clma connectivity search, **TPE vs NSGA-II vs Random**, identical search space +
  15-trial budget each, 3 seeds, raw geomean (CPD, WL) objective (no 2D baseline needed — this
  measures sampler *convergence*, Ismael's parallel-optimizer question).
- **Why:** answers "which sampler searches most efficiently" — directly the parallel-batch
  optimizer question. clma's absolute spread is small/noisy (MCNC, no hard blocks) but the
  *convergence* comparison is valid regardless.
- **Resources:** ~2-4 h, 8 cores, 16 GB.
- **CAVEAT (flag):** on the laptop, TPE completed 6/15 trials but NSGA-II and Random pruned ALL
  trials. Cause not root-caused locally (possibly a resource/interference issue under the
  concurrent laptop run). The cluster rerun in isolation should clarify; if NSGA-II/Random still
  prune every trial, that itself needs investigating before reporting a verdict.

## Phase 2 — eltwise per-column Optuna search (medium) — CONFIDENT
- **What:** eltwise_layer, `search_mode="columns"`, 36x36, cw150, dsp_bram+combined, constrained
  per-column sampling (CLB-majority so trials stay viable), scored vs a fixed **3D-aligned
  reference** layout. 3 seeds. **30-40 trials** (real budget; laptop only managed ~4 completions).
- **Why:** the per-column DSP/BRAM/CLB placement search Ismael asked for — does clustering vs
  spreading the 11 DSPs / 116 BRAMs across columns/layers move CPD/WL. Validated end-to-end on
  the laptop (reference baseline CPD 5.82 ns / WL 166587); the cluster just gives it a real
  trial budget.
- **Resources:** ~4-8 h, 8-16 cores, 24 GB.
- **Note:** this is "% vs 3D-aligned reference," NOT "% over 2D" (that is Phase 3).

## Phase 3 — eltwise TRUE 2D-vs-3D at the channel width the 2D arch needs (HEAVY, cluster priority) — CONFIRM cw
- **What:** eltwise on the real 1-layer 2D dsp_bram arch (baseline) vs the 3D dsp_bram arch,
  same channel width for both, 3 seeds, geomean CPD/WL, report **% improvement of 3D over 2D**.
- **Why this needs the cluster:** the laptop could not do it — the 1-layer 2D arch is unroutable
  at cw150 (the 3D arch routes there only because inter-layer routing relieves congestion), and
  matching a higher cw for the 3D trials blew past 6.8 GB during RR-graph generation. This is the
  paper's headline metric, so it is the priority cluster job.
- **Channel width (REASONED, CONFIRM):** the 3D arch routes eltwise at cw150; the 2D arch was
  still unroutable at cw150 and did not finish routing at cw250 in a 9-min laptop probe. The 2D
  routing is congestion-bound (spram-dense), so it needs materially more than the 3D. **Proposed:
  cw=300 for both** (2x the 3D minimum, generous headroom). The sbatch runs a VPR minimum-channel-
  width probe on the 2D arch FIRST and prints the true min-W, so cw can be set from data rather
  than guessed — Ismael should confirm/adjust from that probe before the full 3-seed runs.
- **Grid:** 3D 36x36; 2D width_2d ~44-50 (must fit ~1331 CLB on one layer). **CONFIRM** grid.
- **Resources:** ~6-12 h, 8-16 cores, 32 GB (2D routing at high cw + large RR graphs).

## Phase 4 — conv_layer + lstm reattempt (HEAVY, synthesis-RAM-bound) — PARTIAL CONFIDENCE
- **What:** re-synthesize conv_layer and lstm (they OOM-killed Yosys at ~7 GB on the 6.8 GB
  laptop). With cluster RAM (32-64 GB) synthesis should fit. Step 1: synth-only check + block
  counts. Step 2, only if they synthesize and map to DSP/BRAM and fit a runnable grid: a columns
  run each vs 3D-aligned reference (like Phase 2).
- **Why:** widen the hard-block benchmark set beyond eltwise. conv_layer has 32-bit-wide
  (BRAM-mappable) memories + multipliers — promising. lstm has 1600-bit-wide memories that did
  NOT map to the 40-bit spram on the laptop and exploded to soft logic — **it may still not fit
  even with cluster RAM** (that is a mapping limit, not a RAM limit). Treat lstm as exploratory.
- **Resources:** synth check ~1 h, 16 cores, **64 GB** (the RAM this whole phase is about).
  Full runs (if viable) similar to Phase 2/3.
- **CONFIRM:** grids/channel widths for conv/lstm are unknown until synthesis reveals their
  size; the script sizes conservatively and flags if a design does not fit.

---

## Ordering, checkpointing, wall-time
- Order: 0 -> 1 -> 2 -> 3 -> 4 (cheap/validation first, heaviest last).
- Each phase writes its own sqlite DB + logs to the overlay as it completes; a wall-time death
  loses only the in-progress phase, not finished ones. `collect_results.py` summarizes whatever
  finished.
- Wall-time: PACE **inferno allows up to 21 days**, so the full campaign fits in ONE submission
  (`sbatch run_campaign.sbatch`) — set `--time` generously. Only on **embers** (free, 8h cap) must
  you split. The script's `PHASES=` env var enables a 3-job split when needed: Job A = Phases 0-1
  (light), Job B = Phase 2 (medium), Job C = Phases 3-4 (heavy). Submission order in
  CONTAINER_README.md.
- All time/mem numbers are estimates from laptop behavior scaled to cluster; **tune to the
  account's queue limits** (`-A` account, partition wall-time caps).
