#!/bin/bash
# ============================================================================
# LaZagna turnkey launcher for PACE Phoenix (parallel campaign, v2).
# Run from a LOGIN node, in the cloned repo dir (project or scratch storage, NOT $HOME):
#
#     bash submit_campaign.sh
#
# It will:
#   1. auto-detect your charge account (override: ACCOUNT=gts-<PI> bash submit_campaign.sh)
#   2. if lazagna.sif is missing, submit the image build job (build_lazagna.sbatch)
#      NOTE: after a repo update (git pull), delete the old lazagna.sif first — the image
#      bakes in the repo code, so a stale .sif runs stale code.
#   3. submit the WORKER ARRAY (default 16 parallel jobs) — all workers contribute trials
#      to the shared optuna studies (eltwise columns + 3 clma sampler studies) through
#      JournalStorage files in the shared work dir. ~16x fewer wall-clock hours than one job.
#   4. submit the EXTRAS job (smoke test + 2D-vs-3D + conv/lstm, the 64G phases)
#   5. submit the COLLECT job (afterany) -> $WORK_ROOT/campaign_summary.md
#
# Tuning (env vars): ACCOUNT, QUEUE (inferno), N_WORKERS (16), SEEDS (3),
#   TRIALS_COLUMNS (35), TRIALS_SAMPLER (15), STUDIES ("columns tpe nsga2 random"),
#   WORK_ROOT (default ./campaign_work/<timestamp>).
# Light first run:  N_WORKERS=2 SEEDS=1 TRIALS_COLUMNS=2 TRIALS_SAMPLER=2 bash submit_campaign.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"

QUEUE="${QUEUE:-inferno}"
N_WORKERS="${N_WORKERS:-16}"

# --- 1. Charge account -------------------------------------------------------
ACCT="${ACCOUNT:-}"
if [ -z "$ACCT" ]; then
  ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | grep -im1 '^gts-' || true)"
  [ -z "$ACCT" ] && ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | awk 'NF{print;exit}')"
fi
if [ -z "$ACCT" ]; then
  echo "Could not auto-detect a charge account."
  echo "Find it with:  pace-quota    (or: sacctmgr -nP show assoc user=$USER format=account)"
  echo "Then re-run:   ACCOUNT=gts-<PI> bash submit_campaign.sh"
  exit 1
fi
echo "Charge account: $ACCT   queue: $QUEUE   workers: $N_WORKERS"

# --- 2. Sanity: required files ----------------------------------------------
for f in lazagna.def build_lazagna.sbatch worker_array.sbatch extras.sbatch collect.sbatch \
         campaign/worker.py campaign/phase_2dvs3d.py campaign/phase_hardblock.py \
         campaign/collect_results.py; do
  [ -e "$HERE/$f" ] || { echo "FATAL: missing $f in $HERE"; exit 1; }
done

# --- 3. Work dir for this campaign run ----------------------------------------
WORK_ROOT="${WORK_ROOT:-$HERE/campaign_work/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$WORK_ROOT"/{journal,bench}
echo "Work dir: $WORK_ROOT"

# --- 4. Build the image if needed -------------------------------------------
SIF="$HERE/lazagna.sif"
DEP=""
if [ ! -f "$SIF" ]; then
  echo "lazagna.sif not found -> queuing build (build_lazagna.sbatch)..."
  BID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" build_lazagna.sbatch)"
  echo "  build job: $BID"
  DEP="--dependency=afterok:$BID"
else
  echo "lazagna.sif present -> skipping build. (After a git pull: rm lazagna.sif to force rebuild.)"
fi

# --- 5. Submit workers + extras + collect -------------------------------------
EXPORTS="ALL,WORK_ROOT=$WORK_ROOT"
for v in SEEDS TRIALS_COLUMNS TRIALS_SAMPLER STUDIES CW HB_GRID HB_CW; do
  if [ -n "${!v:-}" ]; then EXPORTS="$EXPORTS,$v=${!v}"; fi
done

WID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP \
        --array=0-$((N_WORKERS-1)) --export="$EXPORTS" worker_array.sbatch)"
echo "  worker array: $WID (${N_WORKERS} jobs)"

EID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP --export="$EXPORTS" extras.sbatch)"
echo "  extras job:   $EID"

CID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" \
        --dependency="afterany:$WID:$EID" --export="$EXPORTS" collect.sbatch)"
echo "  collect job:  $CID (runs after workers + extras)"

echo
echo "Submitted. Watch with:  squeue -u $USER"
echo "Summary lands in:       $WORK_ROOT/campaign_summary.md"
echo "Study progress:         grep complete worker_${WID}_*.out | tail"
