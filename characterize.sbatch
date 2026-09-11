#!/bin/bash
# ============================================================================
# One-off benchmark characterization: synthesis + pack only, no place or route.
# Reports how much of a FIXED 12.5 / 12.5 / 75 architecture each Koios design
# actually uses, so the placement study can be pointed at designs where hard-block
# placement is contended rather than at ones with 4% DSP utilization.
#
#   sbatch -A gts-<PI> characterize.sbatch
#
# Yosys is the memory driver, hence 64G. Much cheaper than a full campaign since
# nothing is placed or routed.
# ============================================================================
#SBATCH --job-name=lazagna_char
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH -q inferno
#SBATCH --time=08:00:00
#SBATCH --output=characterize_%j.out
#SBATCH --error=characterize_%j.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:-$CAMPAIGN/campaign_work/characterize}"
W="$WORK_ROOT/char"

[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }

mkdir -p "$W"/{arch_files,base_rrg,rrg_3d,tasks_run,results} "$WORK_ROOT"/bench
if [ ! -e "$W/arch_files/.seeded" ]; then
  apptainer exec --no-home --cleanenv "$SIF" cp -a /opt/LaZagna/arch_files/. "$W/arch_files/"
  touch "$W/arch_files/.seeded"
fi

export APPTAINERENV_WORK="/work"
for v in CHAR_GRID CHAR_CW CHAR_DESIGNS; do
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done

apptainer exec --no-home --cleanenv \
  -B "$W/arch_files:/opt/LaZagna/arch_files" \
  -B "$W/base_rrg:/opt/LaZagna/base_rrg" \
  -B "$W/rrg_3d:/opt/LaZagna/rrg_3d" \
  -B "$W/tasks_run:/opt/LaZagna/tasks_run" \
  -B "$W/results:/opt/LaZagna/results" \
  -B "$WORK_ROOT:/work" -B "$CAMPAIGN/campaign:/campaign" \
  "$SIF" python3 /campaign/characterize.py
echo "CHARACTERIZE DONE $(date -Is)"
