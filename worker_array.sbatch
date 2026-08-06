#!/bin/bash
# ============================================================================
# LaZagna campaign WORKER ARRAY — N parallel SLURM jobs, each contributing optuna
# trials to the shared studies (columns + 3 samplers) via JournalStorage on the
# shared work dir. This is the parallelism: 16 workers = 16 trials in flight.
# Submitted by submit_campaign.sh (which passes -A, --array, and WORK_ROOT).
#
# No overlay: the flow's writable dirs (arch_files, base_rrg, rrg_3d, tasks_run,
# results) are per-worker host dirs bind-mounted over the read-only image paths.
# (Run 11659291 post-mortem: the 50 GB overlay filled -> ENOSPC; sqlite on
# Lustre -> 'disk I/O error'. Both eliminated.)
# ============================================================================
#SBATCH --job-name=lazagna_worker
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH -q inferno
#SBATCH --time=16:00:00
#SBATCH --output=worker_%A_%a.out
#SBATCH --error=worker_%A_%a.err
set -u

module load apptainer 2>/dev/null || true   # PACE: apptainer may already be on PATH
                                            # (run 11659291: Lmod 'unknown module' yet apptainer worked)
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use submit_campaign.sh)}"
ID="${SLURM_ARRAY_TASK_ID:-0}"
W="$WORK_ROOT/worker_$ID"

[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }

# Per-worker writable dirs for everything the flow writes inside /opt/LaZagna.
mkdir -p "$W"/{arch_files,base_rrg,rrg_3d,tasks_run,results} "$WORK_ROOT"/{journal,bench}

# arch_files must start as a copy of the image's (templates live there); the bind shadows it.
if [ ! -e "$W/arch_files/.seeded" ]; then
  apptainer exec --no-home --cleanenv "$SIF" cp -a /opt/LaZagna/arch_files/. "$W/arch_files/"
  touch "$W/arch_files/.seeded"
fi

BINDS=(-B "$W/arch_files:/opt/LaZagna/arch_files"
       -B "$W/base_rrg:/opt/LaZagna/base_rrg"
       -B "$W/rrg_3d:/opt/LaZagna/rrg_3d"
       -B "$W/tasks_run:/opt/LaZagna/tasks_run"
       -B "$W/results:/opt/LaZagna/results"
       -B "$WORK_ROOT:/work"
       -B "$CAMPAIGN/campaign:/campaign")

echo "WORKER $ID START $(date -Is)  work=$W"
apptainer exec --no-home --cleanenv "${BINDS[@]}" \
  --env "WORKER_ID=$ID,WORK=/work,SEEDS=${SEEDS:-3},TRIALS_COLUMNS=${TRIALS_COLUMNS:-35},TRIALS_SAMPLER=${TRIALS_SAMPLER:-15},STUDIES=${STUDIES:-columns tpe nsga2 random}" \
  "$SIF" python3 /campaign/worker.py
rc=$?
echo "WORKER $ID DONE rc=$rc $(date -Is)"
exit $rc
