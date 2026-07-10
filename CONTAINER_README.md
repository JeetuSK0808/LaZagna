# LaZagna on PACE — Container Build + Campaign Runbook

## Quick start (one command)

From a **login node**, in your project-storage dir holding this repo's PACE files
(`lazagna.def`, `run_campaign.sbatch`, `build_lazagna.sbatch`, `submit_campaign.sh`, `campaign/`):

```bash
bash submit_campaign.sh
```

That auto-detects your charge account, builds `lazagna.sif` if it is missing (compute-node build
job), auto-creates the writable overlay inside the campaign job, and submits the campaign. Tune
with env vars, e.g. a fast light run first: `PHASES="0 1" SEEDS=1 bash submit_campaign.sh`.
Override the account if auto-detect picks the wrong one: `ACCOUNT=gts-<PI> bash submit_campaign.sh`.

The sections below are the manual, step-by-step version (and the smoke test, which is still worth
running once to confirm `--overlay` works on your PACE before the full campaign).

> **PACE conventions are verified** from the public PACE docs (see "Known caveats"). The only
> user-specific value is your charge account, which `submit_campaign.sh` auto-detects; project
> path defaults to the submit dir and `module load apptainer` uses the default module. The one
> thing to confirm live is that `--overlay` works on your PACE (the smoke test checks it; bind
> fallback documented below).

---

## 0. Prerequisite — update the fork FIRST
`lazagna.def` clones `github.com/IY2002/LaZagna`. The Bug #3 fix and the columns/sampler/2D
edits are NOT on the fork yet — upload the 6 files in **UPLOAD_MANIFEST.md** to the fork before
building, or the image will lack them. (Alternative: uncomment the `%files` overlay block in
`lazagna.def` to bake local copies in at build time — requires those files beside the `.def`.)

## 1. Build the image (on a compute node, not the login node)
Apptainer build compiles OpenFPGA/VTR9 (C++, submodule-heavy) — needs RAM and time (~1 h; the
parallel build is the RAM driver).
```bash
# Find your charge account first (looks like gts-<PI>):
pace-quota            # (or: sacctmgr show assoc user=$USER format=account)

# Apptainer is DISABLED on login nodes at PACE — you MUST build (and run) on a compute node.
# grab an interactive compute node (PACE example uses these flags):
salloc -A gts-<PI> -q inferno -N1 --ntasks=1 --cpus-per-task=8 --mem=32G --time=2:00:00
module avail apptainer     # confirm the exact module (name/version), then:
module load apptainer      # e.g. apptainer/1.3.x

# Store the .sif in PERSISTENT project storage, NOT $HOME (10 GB quota) and NOT scratch
# (scratch auto-purges files >60 days, which would delete your image):
#   /storage/coda1/<project>/...        <- project storage (persistent) -- recommended for the .sif
#   ~/scratch/lazagna                    <- alternative, but purged >60 days
cd /storage/coda1/<project>/lazagna      # your project storage path (see `pace-quota`)
apptainer build lazagna.sif lazagna.def
# The %post apt-install + OpenFPGA compile need build-time root. PACE's guide shows unprivileged
# builds on compute nodes (no sudo/fakeroot mentioned), so this should just work. If it errors
# with a permissions/root problem, retry with fakeroot:
#   apptainer build --fakeroot lazagna.sif lazagna.def
```
If the build OOMs, lower `BUILD_JOBS` in `lazagna.def` (`%post`) or raise `--mem`.
Store `lazagna.sif` in project/scratch storage (`<PROJECT_STORAGE>`), **not `$HOME`** (quota).

## 2. Create the writable overlay (required)
The SIF is read-only, but LaZagna writes `rrg_3d/`, `base_rrg/`, `tasks_run/`, `results/`,
`arch_files/*.xml`, and the sqlite DBs *inside* `/opt/LaZagna`. A persistent overlay holds those.
```bash
apptainer overlay create --size 51200 lazagna_overlay.img   # ~50 GB; grow if RR graphs pile up
```
(50 GB is a starting estimate — high-cw 3D RR graphs are ~0.5-1 GB each. CONFIRM against quota.)

## 3. Smoke test (do this before the campaign)
Known-good light config — confirms Yosys/VPR/optimizer + overlay + binds work.
```bash
module load apptainer
apptainer exec --no-home --cleanenv --overlay lazagna_overlay.img lazagna.sif \
    python3 /opt/LaZagna/lazagna/main.py -f /opt/LaZagna/setup_files/simple_test.yaml -v
```
- `--no-home`: drops the auto-mounted `$HOME` (and any `~/venv`/`~/.local`) so the container venv
  `/opt/venv` is used. PACE still auto-mounts `/storage`, `$PWD`, `/tmp` — `--no-home` only drops
  `$HOME` — so your project paths and binds stay available.
- `--cleanenv`: don't leak host env vars (PACE-recommended for Python-env clashes).
- `--overlay`: makes the read-only SIF's `/opt/LaZagna` writable (the flow writes `rrg_3d/`,
  `tasks_run/`, `results/`, `arch_files/*.xml`, `*.db` there).
- **This smoke test ALSO verifies `--overlay` works on your PACE** — it is standard Apptainer but
  is NOT in PACE's KB article, so confirm it here before the campaign. If `--overlay` errors, see
  the caveat below.
- **Success = the run finishes and the VPR log shows `VPR succeeded` with real (non-zero) CPD/WL.**
- Optional stronger smoke: the light clma config (cw100, 30x30) — one connectivity trial. This is
  the config that never crashed on the laptop (CPD ~8.7 ns / WL ~24662).

## 4. Run the campaign
Put `run_campaign.sbatch` and the `campaign/` dir in `<PROJECT_STORAGE>/lazagna` next to the
`.sif` and overlay. Edit `run_campaign.sbatch`: fill `-A <ACCOUNT_PLACEHOLDER>`, confirm
`--time`, `module load` name, and the path vars at the top.

The campaign runs the phases in **EXPERIMENT_PLAN.md** in cheap-first order, continues past a
failed phase, and checkpoints (sqlite + logs per phase) so a wall-time death keeps finished work.

Total likely exceeds one queue's wall-time, so **submit in three sequential jobs** (light ->
medium -> heavy) using the `PHASES` selector; chain with `--dependency` so each starts when the
prior finishes:
```bash
A=$(sbatch --parsable --export=ALL,PHASES="0 1"  run_campaign.sbatch)   # smoke + sampler (light)
B=$(sbatch --parsable --dependency=afterany:$A --export=ALL,PHASES="2" run_campaign.sbatch)  # eltwise columns
C=$(sbatch          --dependency=afterany:$B --export=ALL,PHASES="3 4" run_campaign.sbatch)  # 2D-vs-3D + conv/lstm (heavy)
```
Or submit all phases in one job if your queue's wall-time allows: `sbatch run_campaign.sbatch`.

Tunable env vars: `SEEDS` (default 3), `TRIALS_SAMPLER` (15), `TRIALS_COLUMNS` (35),
`CW` (Phase 3 channel width; auto-tries 200/300/400 if unset), `HB_GRID`/`HB_CW` (Phase 4).

## 5. Results
`collect_results.py` runs at the end and writes `results_summary/campaign_summary.md`
(host-visible) — per-run verified CPD/WL + block counts, per-study best, gate-enforced. Detailed
numbers (% improvements, sampler bests) are in the SLURM stdout `campaign_<jobid>.out`
(grep `IMPROVEMENT`, `BEST`, `FLAG`). Full logs/DBs persist in the overlay.

## Known caveats to confirm
- **PACE Phoenix conventions are VERIFIED from the public PACE docs** (docs.pace.gatech.edu):
  `-q inferno` (charged, 21-day wall) / `-q embers` (free, 8h), `-A gts-<PI>`, project storage
  `/storage/coda1/...`, `module load apptainer`. Only YOUR specifics remain: the exact account
  string (`pace-quota`), the exact apptainer module version (`module avail apptainer`), and your
  project path. If you use ICE/Hive instead of Phoenix, re-check — QOS/partitions differ.
- Because inferno allows up to a 21-day wall-time, the whole campaign can run in ONE submission;
  the 3-job split above is only required on embers (8h).
- **Apptainer runs on COMPUTE NODES ONLY** (PACE disabled it on login nodes) — always `salloc`/
  `sbatch`. The campaign sbatch already runs on a compute node; the build must too (via `salloc`).
- **`/storage` is auto-bind-mounted by PACE** (along with `$PWD`, `/tmp`, `/dev`, `/proc`, `/sys`).
  So the `.sif`, overlay, `campaign/`, and outputs under `/storage` are reachable; the explicit
  `-B` binds in the sbatch remap them to fixed container paths and remain valid.
- **`--overlay` is NOT in PACE's KB article** (it is standard Apptainer). The smoke test verifies
  it. If it fails on your PACE: the flow writes inside `/opt/LaZagna` (read-only in the SIF), so
  the fallback is to bind writable `/storage` dirs over the output subdirs
  (`-B $W/rrg_3d:/opt/LaZagna/rrg_3d -B $W/tasks_run:/opt/LaZagna/tasks_run -B
  $W/results:/opt/LaZagna/results ...`). Caveat: `arch_files/*.xml` and `*.db` are written to
  paths that mix with read-only content, so a clean bind-only setup needs a small tweak to
  redirect those (or ask PACE to enable overlay). Overlay is far simpler — prefer it.
- **Build is unprivileged** on PACE compute nodes (their guide shows no sudo/fakeroot); if the
  apt-heavy `%post` errors, retry `apptainer build --fakeroot ...`.
- Phase 3 channel width for the 2D arch is auto-searched (200/300/400); confirm the chosen value
  is sensible for the paper (it prints which cw it used).
- Phase 4 (conv_layer/lstm) grids are guesses; lstm may not fit due to a memory-mapping limit
  (not RAM) — treat as exploratory.
- eltwise single-design dir (`benchmarks/koios_elt/`) is auto-created from
  `benchmarks/koios/eltwise_layer.v` by the phase scripts if absent.
