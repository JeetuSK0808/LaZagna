#!/bin/bash
# ============================================================================
# LaZagna campaign COLLECT job — runs after the worker array + extras finish
# (afterany, so a partial campaign still gets summarized). Walks every job's
# tasks_run under WORK_ROOT + the optuna journals, writes campaign_summary.md.
# ============================================================================
#SBATCH --job-name=lazagna_collect
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH -q inferno
#SBATCH --time=01:00:00
#SBATCH --output=collect_%j.out
#SBATCH --error=collect_%j.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use submit_campaign.sh)}"

apptainer exec --no-home --cleanenv \
  -B "$WORK_ROOT:/work" -B "$CAMPAIGN/campaign:/campaign" --env "WORK=/work" \
  "$SIF" python3 /campaign/collect_results.py /work/campaign_summary.md /work
echo "SUMMARY: $WORK_ROOT/campaign_summary.md"
