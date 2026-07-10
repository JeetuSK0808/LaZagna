#!/bin/bash
# ============================================================================
# LaZagna turnkey launcher for PACE Phoenix. Run from a LOGIN node, in the dir
# holding lazagna.def / campaign/ (project storage, NOT $HOME):
#
#     bash submit_campaign.sh
#
# It will:
#   1. auto-detect your charge account (override: ACCOUNT=gts-<PI> bash submit_campaign.sh)
#   2. if lazagna.sif is missing, submit the build job (build_lazagna.sbatch)
#   3. submit the campaign (run_campaign.sbatch), waiting for the build if one was queued
# The overlay is auto-created inside the campaign job (needs a compute node).
#
# Options (env vars): ACCOUNT, QUEUE (default inferno), PHASES, SEEDS, TRIALS_SAMPLER,
#   TRIALS_COLUMNS. Example:  PHASES="0 1" SEEDS=1 bash submit_campaign.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"

QUEUE="${QUEUE:-inferno}"

# --- 1. Charge account -------------------------------------------------------
ACCT="${ACCOUNT:-}"
if [ -z "$ACCT" ]; then
  # Prefer a gts-* association; fall back to the first association SLURM lists.
  ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | grep -im1 '^gts-' || true)"
  [ -z "$ACCT" ] && ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | awk 'NF{print;exit}')"
fi
if [ -z "$ACCT" ]; then
  echo "Could not auto-detect a charge account."
  echo "Find it with:  pace-quota    (or: sacctmgr -nP show assoc user=$USER format=account)"
  echo "Then re-run:   ACCOUNT=gts-<PI> bash submit_campaign.sh"
  exit 1
fi
echo "Charge account: $ACCT   queue: $QUEUE"

# --- 2. Sanity: required files ----------------------------------------------
for f in lazagna.def run_campaign.sbatch build_lazagna.sbatch campaign/collect_results.py; do
  [ -e "$HERE/$f" ] || { echo "FATAL: missing $f in $HERE"; exit 1; }
done

# --- 3. Build the image if needed -------------------------------------------
SIF="$HERE/lazagna.sif"
DEP=""
if [ ! -f "$SIF" ]; then
  echo "lazagna.sif not found -> queuing build (build_lazagna.sbatch)..."
  BID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" build_lazagna.sbatch)"
  echo "  build job: $BID"
  DEP="--dependency=afterok:$BID"
else
  echo "lazagna.sif present -> skipping build."
fi

# --- 4. Submit the campaign --------------------------------------------------
# Pass through any tuning env vars the user set.
EXPORTS="ALL"
for v in PHASES SEEDS TRIALS_SAMPLER TRIALS_COLUMNS CW HB_GRID HB_CW; do
  if [ -n "${!v:-}" ]; then EXPORTS="$EXPORTS,$v=${!v}"; fi
done

CID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP --export="$EXPORTS" run_campaign.sbatch)"
echo "  campaign job: $CID  ${DEP:+(starts after build $BID)}"
echo
echo "Submitted. Watch with:  squeue -u $USER"
echo "Results land in:        $HERE/results_summary/campaign_summary.md"
echo "Live log:               $HERE/campaign_${CID}.out"
