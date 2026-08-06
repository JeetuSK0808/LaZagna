#!/bin/bash
# ============================================================================
# LaZagna campaign EXTRAS job — the non-optuna phases, run once while the worker
# array chews the studies in parallel:
#   smoke  : simple_test.yaml (validates container + binds before anything heavy)
#   phase3 : true 2D-vs-3D eltwise comparison (auto-probes cw 200/300/400)
#   phase4 : conv_layer + lstm reattempt (the RAM-heavy synthesis, hence 64G here)
# Continue-on-fail between phases. Submitted by submit_campaign.sh.
# ============================================================================
#SBATCH --job-name=lazagna_extras
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH -q inferno
#SBATCH --time=16:00:00
#SBATCH --output=extras_%j.out
#SBATCH --error=extras_%j.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use submit_campaign.sh)}"
[ -f "$WORK_ROOT/campaign.env" ] && . "$WORK_ROOT/campaign.env"   # tunables (SEEDS, CW, HB_*, ...)
W="$WORK_ROOT/extras"

[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }

# Stale-image guard (old .sif lacks the bind mountpoints AND bakes old code).
if ! apptainer exec --no-home --cleanenv "$SIF" test -d /opt/LaZagna/base_rrg; then
  echo "FATAL: lazagna.sif is STALE. rm lazagna.sif && bash submit_campaign.sh"; exit 1
fi

mkdir -p "$W"/{arch_files,base_rrg,rrg_3d,tasks_run,results} "$WORK_ROOT"/{journal,bench}
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

export APPTAINERENV_WORK="/work"
for v in CW HB_GRID HB_CW; do   # phase 3/4 tunables, if the user set them
  if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
done
APP=(apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF")

run_phase() {  # $1 = label ; $2.. = command
  local label="$1"; shift
  echo "==================== $label START $(date -Is) ===================="
  if "$@"; then
    echo "==================== $label OK   $(date -Is) ===================="
  else
    echo "!!!!!!!!!!!!!!!!!!!! $label FAILED (rc=$?, continuing) $(date -Is) !!!!!!!!!!!!"
  fi
}

run_phase "smoke"  "${APP[@]}" python3 /opt/LaZagna/lazagna/main.py \
                     -f /opt/LaZagna/setup_files/simple_test.yaml -v
run_phase "phase3-2dvs3d"   "${APP[@]}" python3 /campaign/phase_2dvs3d.py "${SEEDS:-3}"
run_phase "phase4-hardblock" "${APP[@]}" python3 /campaign/phase_hardblock.py "${SEEDS:-3}"
echo "EXTRAS DONE $(date -Is)"
