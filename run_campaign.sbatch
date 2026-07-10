#!/bin/bash
# ============================================================================
# LaZagna campaign — one submission, runs the EXPERIMENT_PLAN.md phases in order.
# Submit:  sbatch run_campaign.sbatch
# Select phases (for split submission on short queues):
#          PHASES="0 1"   sbatch run_campaign.sbatch
#
# SLURM directives (PACE). Account is auto-detected by submit_campaign.sh (recommended entry point).
#SBATCH --job-name=lazagna_campaign
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G                 # Phase 4 (conv/lstm synthesis) is the RAM driver. (PACE examples
                                  #   often use --mem-per-cpu=4G instead; both work — 16 cpus*4G=64G)
##SBATCH -A gts-CHANGEME          # DISABLED (leading ##) on purpose: submit_campaign.sh auto-detects
                                  #   your charge account and passes `sbatch -A <acct>` (a CLI -A
                                  #   overrides this directive). To hardcode instead, drop one '#'
                                  #   and set gts-<PI>. `sbatch` directly without -A uses your SLURM
                                  #   default account.
#SBATCH -q inferno                # PACE Phoenix: 'inferno' = charged, 21-day wall (confirmed in PACE
                                  #   docs, e.g. `-qinferno`); 'embers' = free/preemptible, 8h wall.
                                  #   (-p inferno is equivalent.) VERIFY on ICE/other clusters.
#SBATCH --time=12:00:00           # inferno allows up to 21 days, so the WHOLE campaign can run in one
                                  #   job (raise this). On embers (8h) you MUST split via PHASES (below).
#SBATCH --output=campaign_%j.out
#SBATCH --error=campaign_%j.err
# ============================================================================
set -u

module load apptainer   # PACE: confirm exact module name (could be 'apptainer' or a versioned one)

# --- Paths (edit to your project storage; NOT $HOME) ---
CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
OVERLAY="${OVERLAY:-$CAMPAIGN/lazagna_overlay.img}"   # writable overlay (auto-created below)
SCRIPTS="${SCRIPTS:-$CAMPAIGN/campaign}"              # this dir with the phase_*.py + collect
SUMMARY="${SUMMARY:-$CAMPAIGN/results_summary}"       # host-visible collected results
PHASES="${PHASES:-0 1 2 3 4}"
TRIALS_SAMPLER="${TRIALS_SAMPLER:-15}"
TRIALS_COLUMNS="${TRIALS_COLUMNS:-35}"
SEEDS="${SEEDS:-3}"

mkdir -p "$SUMMARY"
[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF -- build it first: sbatch build_lazagna.sbatch"; exit 1; }
# Auto-create the writable overlay if absent (runs on a COMPUTE node, where apptainer is enabled).
if [ ! -f "$OVERLAY" ]; then
  echo "Overlay $OVERLAY missing -- creating 50 GB overlay..."
  apptainer overlay create --size 51200 "$OVERLAY" \
    || { echo "FATAL: 'apptainer overlay create' failed. If overlays are unsupported on your PACE,"; \
         echo "       bind writable host dirs over the outputs instead of --overlay, e.g. add to APP:"; \
         echo "       -B \$W/rrg_3d:/opt/LaZagna/rrg_3d -B \$W/tasks_run:/opt/LaZagna/tasks_run"; \
         echo "       -B \$W/results:/opt/LaZagna/results -B \$W/arch_files:/opt/LaZagna/arch_files"; \
         echo "       (\$W = a writable /storage dir), or ask PACE to enable overlay."; exit 1; }
fi

# Writable outputs (rrg_3d/, tasks_run/, results/, *.db) live inside /opt/LaZagna, which the
# read-only SIF cannot write. --overlay makes them persist (standard Apptainer; NOT in PACE's KB
# but verified by the phase-0 smoke run; bind fallback printed above if it fails). --no-home/--cleanenv
# keep the auto-mounted $HOME (and any ~/venv) out (PACE still auto-mounts /storage, $PWD, /tmp, so
# paths under /storage are reachable). NOTE: `module load` is done ABOVE, outside the container --
# it does not work inside `apptainer exec`.
APP=(apptainer exec --no-home --cleanenv --overlay "$OVERLAY"
     -B "$SCRIPTS":/campaign -B "$SUMMARY":/summary "$SIF")

run_phase() {   # $1 = label ; $2.. = command
  local label="$1"; shift
  echo "==================== PHASE $label START $(date -Is) ===================="
  if "$@"; then
    echo "==================== PHASE $label OK   $(date -Is) ===================="
  else
    echo "!!!!!!!!!!!!!!!!!!!! PHASE $label FAILED (rc=$?, continuing) $(date -Is) !!!!!!!!!!!!"
  fi
}

echo "CAMPAIGN START $(date -Is)  phases=[$PHASES]  seeds=$SEEDS"
for P in $PHASES; do case "$P" in
  0) run_phase "0-smoke" "${APP[@]}" python3 /opt/LaZagna/lazagna/main.py \
        -f /opt/LaZagna/setup_files/simple_test.yaml -v ;;
  1) run_phase "1-sampler" "${APP[@]}" python3 /campaign/phase_sampler.py "$TRIALS_SAMPLER" "$SEEDS" ;;
  2) run_phase "2-columns" "${APP[@]}" python3 /campaign/phase_columns.py "$SEEDS" "$TRIALS_COLUMNS" ;;
  3) run_phase "3-2dvs3d" "${APP[@]}" python3 /campaign/phase_2dvs3d.py "$SEEDS" ;;
  4) run_phase "4-hardblock" "${APP[@]}" python3 /campaign/phase_hardblock.py "$SEEDS" ;;
  *) echo "unknown phase '$P' (skipping)";;
esac; done

# Collect whatever finished into a host-visible summary (safe to run even after a partial run).
echo "==================== COLLECT $(date -Is) ===================="
"${APP[@]}" python3 /campaign/collect_results.py /summary/campaign_summary.md || echo "collect failed"
echo "CAMPAIGN DONE $(date -Is)  -> $SUMMARY/campaign_summary.md"
