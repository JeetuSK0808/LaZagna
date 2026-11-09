#!/bin/bash
# ============================================================================
# Multi-benchmark architecture search on PACE in one command. From a LOGIN node, in the repo
# directory that holds lazagna.sif:
#
#     git pull && bash campaign/suite_study.sh
#
# It submits N_WORKERS search jobs (suite_study.sbatch, PHASE=search) that share ONE Optuna
# study, then a report job that starts when they end (afterany): Pareto front with the
# champion, Spearman and SHAP tables, and ONE results file,
#     campaign_work/<study>_<time>/<study>_<time>_results.tar.gz
# No image rebuild: the Python comes from this checkout through the binds (campaign/binds.sh),
# so a git pull is the whole update. (lazagna.sif is only built if it is missing.)
#
# Settings (environment variables, all optional):
#   DESIGNS        "<suite>/<design>" or a whole suite, space separated
#                  (default "koios/attention_layer vtr/stereovision1 koios/tpu_like.small.os";
#                  `python3 benchmark_suites.py` lists the suites)
#   SAMPLER        tpe | nsga2 | nsga3 | random | qmc              (default tpe)
#   SEARCH_MODE    structured | layout | connectivity              (default structured)
#   TRIALS         completed trials over all workers               (default 40)
#   N_WORKERS      search jobs = trials in flight                  (default 8)
#   SEEDS (3), FIDELITY (route; "place" is faster), CW (300), TALL (1), TARGET_UTIL (0.8)
#   CONN_CHOICES   connectivity values to sample, e.g. "0.25 0.5 1.0" (default: fixed at 1.0)
#   VCONN_CHOICES  vertical connectivity (share of each 3D switch block's channels that cross)
#                  to sample, e.g. "0.05 0.1 0.25 0.5 1.0"         (default: fixed at 1.0;
#                  structured and layout modes). Both take numbers in (0, 1]. The vertical
#                  links of a trial are connectivity x vertical connectivity (1 = full 3D).
#   DELAY          delay ratio, one value or "lo,hi"               (default 0.739)
#   WEIGHTS        "w_cpd,w_wl" = one weighted objective           (default: Pareto front)
#   LINK_PENALTY   % points per unit of vertical links             (default 0)
#   LINKS_OBJECTIVE  1 = vertical links are a third objective: a 3D Pareto front (CPD gain, WL
#                  gain, links) with two champions, "best" (highest CPD + WL gain) and "lean"
#                  (the same among front points with links <= CHAMPION_MAX_LINKS, default 0.1).
#                  Not with WEIGHTS or LINK_PENALTY.               (default 0)
#   ANCHORS        1 = the known layouts are the first trials, queued once per study: even_split,
#                  split_types, split_rev, hb_top, hb_one_layer, and "recommended" (split_types at
#                  vertical connectivity 0.1, when 0.1 is a VCONN_CHOICES value). Structured mode;
#                  they count toward TRIALS. See lazagna_optuna.ANCHORS. (default 0)
#   NSGA_POP       population of the nsga2 / nsga3 samplers       (default: Optuna's, 50).
#                  NSGA draws its first generation at random: when TRIALS < population, an
#                  nsga2 / nsga3 study is just random sampling.
#   STUDY          study name                                      (default suite_<mode>_<sampler>)
#   WORK_ROOT      (default campaign_work/<study>_<time>)
#   ACCOUNT (auto-detected), QUEUE (inferno), WALL (search job wall time, default 16:00:00)
#   INSTALL_EXTRAS 1 (default): if scikit-learn/shap are missing from the image, the report job
#                  pip-installs them once into campaign_work/pyextras; 0: report without SHAP
#   DRY_RUN=1      print the sbatch commands instead of submitting
#
# Examples:
#   DESIGNS="koios/eltwise_layer vtr/stereovision1 mcnc/clma" SAMPLER=nsga2 TRIALS=60 bash campaign/suite_study.sh
#   WEIGHTS=0.7,0.3 LINK_PENALTY=2 CONN_CHOICES="0.25 0.5 1.0" bash campaign/suite_study.sh
#   # routed search for layout and vertical links on designs with layout headroom, seeded with
#   # the known layouts:
#   DESIGNS="koios/tpu_like.small.ws vtr/mkDelayWorker32B vtr/stereovision2" TRIALS=64 ANCHORS=1 \
#     LINKS_OBJECTIVE=1 CONN_CHOICES="0.25 0.5 1.0" VCONN_CHOICES="0.05 0.1 0.25 0.5 1.0" \
#     bash campaign/suite_study.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
HERE="$PWD"

SAMPLER="${SAMPLER:-tpe}"
SEARCH_MODE="${SEARCH_MODE:-structured}"
N_WORKERS="${N_WORKERS:-8}"
QUEUE="${QUEUE:-inferno}"
case "$SAMPLER" in tpe|nsga2|nsga3|random|qmc) ;; *)
  echo "SAMPLER must be one of: tpe nsga2 nsga3 random qmc (got '$SAMPLER')"; exit 1;; esac
case "$SEARCH_MODE" in structured|layout|connectivity) ;; *)
  echo "SEARCH_MODE must be one of: structured layout connectivity (got '$SEARCH_MODE')"; exit 1;; esac
case "${FIDELITY:-route}" in route|place) ;; *)
  echo "FIDELITY must be route or place (got '$FIDELITY')"; exit 1;; esac
if [ -n "${WEIGHTS:-}" ] && ! [[ "$WEIGHTS" =~ ^[0-9.eE+-]+,[0-9.eE+-]+$ ]]; then
  echo "WEIGHTS must look like 0.7,0.3 (got '$WEIGHTS')"; exit 1
fi
[[ "$N_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "N_WORKERS must be a positive integer"; exit 1; }
[[ "${TRIALS:-40}" =~ ^[1-9][0-9]*$ ]] || { echo "TRIALS must be a positive integer (got '$TRIALS')"; exit 1; }
is_num() { [[ "$1" =~ ^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$ ]]; }
nonzero() { awk -v x="$1" 'BEGIN { exit !(x + 0 != 0) }'; }
for v in CONN_CHOICES VCONN_CHOICES; do
  vals="${!v:-}"
  for x in ${vals//,/ }; do
    if ! is_num "$x" || ! awk -v x="$x" 'BEGIN { exit !(x + 0 > 0 && x + 0 <= 1) }'; then
      echo "$v must be numbers in (0, 1], e.g. \"0.25 0.5 1.0\" (got '${!v}')"; exit 1
    fi
  done
done
for v in LINKS_OBJECTIVE ANCHORS; do
  case "${!v:-0}" in 0|1) ;; *) echo "$v must be 0 or 1 (got '${!v}')"; exit 1;; esac
done
for v in LINK_PENALTY CHAMPION_MAX_LINKS; do
  if [ -n "${!v:-}" ] && ! is_num "${!v}"; then echo "$v must be a number (got '${!v}')"; exit 1; fi
done
if [ -n "${CHAMPION_MAX_LINKS:-}" ] && ! awk -v x="$CHAMPION_MAX_LINKS" 'BEGIN { exit !(x + 0 >= 0) }'; then
  echo "CHAMPION_MAX_LINKS must be >= 0 (got '$CHAMPION_MAX_LINKS')"; exit 1
fi
if [ "${LINKS_OBJECTIVE:-0}" = 1 ] && { [ -n "${WEIGHTS:-}" ] || nonzero "${LINK_PENALTY:-0}"; }; then
  echo "LINKS_OBJECTIVE=1 makes vertical links a third objective, so it cannot be combined with WEIGHTS"
  echo "(one weighted objective) or a non-zero LINK_PENALTY (links would be charged twice). Unset those, or LINKS_OBJECTIVE."
  exit 1
fi
if [ "${ANCHORS:-0}" = 1 ] && [ "$SEARCH_MODE" != structured ]; then
  echo "ANCHORS=1 needs SEARCH_MODE=structured (got '$SEARCH_MODE')"; exit 1
fi
if [ -n "${VCONN_CHOICES:-}" ] && [ "$SEARCH_MODE" = connectivity ]; then
  echo "VCONN_CHOICES applies to SEARCH_MODE=structured and layout, not connectivity"; exit 1
fi
if [ -n "${NSGA_POP:-}" ] && ! [[ "$NSGA_POP" =~ ^[1-9][0-9]*$ && "$NSGA_POP" -ge 2 ]]; then
  echo "NSGA_POP must be an integer >= 2 (got '$NSGA_POP')"; exit 1
fi
case "$SAMPLER" in nsga2|nsga3)
  if [ "${TRIALS:-40}" -lt "${NSGA_POP:-50}" ]; then
    echo "note: TRIALS=${TRIALS:-40} is below the NSGA population (${NSGA_POP:-50}), so $SAMPLER samples at random throughout"
  fi;;
esac
nwords() { echo $#; }
c="${CONN_CHOICES:-}"; vc="${VCONN_CHOICES:-}"
if [ "${LINKS_OBJECTIVE:-0}" = 1 ] && [ "$SEARCH_MODE" != connectivity ] \
   && [ "$(nwords ${c//,/ })" -le 1 ] && [ "$(nwords ${vc//,/ })" -le 1 ]; then
  echo "note: LINKS_OBJECTIVE=1 with fixed CONN_CHOICES and VCONN_CHOICES: every trial has the same links"
fi
for f in suite_study.sbatch campaign/suite_study.py campaign/analyze_optuna.py campaign/binds.sh \
         lazagna.def build_lazagna.sbatch; do
  [ -e "$f" ] || { echo "FATAL: missing $f in $HERE"; exit 1; }
done

if [ -n "${DRY_RUN:-}" ]; then
  sbatch() { echo "sbatch $*" >&2; echo "$((RANDOM + 1000))"; }
fi

# --- Charge account (same detection as submit_campaign.sh) ---------------------------
ACCT="${ACCOUNT:-}"
if [ -z "$ACCT" ] && [ -n "${DRY_RUN:-}" ]; then ACCT="gts-DRYRUN"; fi
if [ -z "$ACCT" ]; then
  ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | grep -im1 '^gts-' || true)"
  [ -z "$ACCT" ] && ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | awk 'NF{print;exit}')"
fi
if [ -z "$ACCT" ]; then
  echo "Could not auto-detect a charge account. Find it with: pace-quota"
  echo "Then re-run: ACCOUNT=gts-<PI> bash campaign/suite_study.sh"
  exit 1
fi

# --- Work dir and settings (an env file, not sbatch --export, which splits on commas) --
STUDY="${STUDY:-suite_${SEARCH_MODE}_${SAMPLER}}"
WORK_ROOT="${WORK_ROOT:-$HERE/campaign_work/${STUDY}_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$WORK_ROOT" logs/suite
ENVF="$WORK_ROOT/suite_study.env"
: > "$ENVF"
for v in DESIGNS SEARCH_MODE SAMPLER TRIALS STUDY SEEDS FIDELITY CW TALL TARGET_UTIL CONN_CHOICES \
         DELAY WEIGHTS LINK_PENALTY KEEP_RRG INSTALL_EXTRAS EXTRAS_DIR \
         VCONN_CHOICES LINKS_OBJECTIVE ANCHORS NSGA_POP CHAMPION_MAX_LINKS; do
  if [ -n "${!v:-}" ]; then printf '%s=%q\n' "$v" "${!v}" >> "$ENVF"; fi
done
printf 'CODE_COMMIT=%q\n' "$(git rev-parse HEAD 2>/dev/null || echo unknown)" >> "$ENVF"
echo "Study $STUDY   account $ACCT   queue $QUEUE   workers $N_WORKERS"
echo "Work dir: $WORK_ROOT"
echo "Settings ($ENVF):"; sed 's/^/  /' "$ENVF"

# --- Image: build only if missing ------------------------------------------------------
SIF="$HERE/lazagna.sif"
DEP=""
if [ ! -f "$SIF" ]; then
  echo "lazagna.sif not found -> queuing the image build first (build_lazagna.sbatch)"
  BID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" build_lazagna.sbatch)"
  DEP="--dependency=afterok:$BID"
fi

# --- Search array, then the report ------------------------------------------------------
SID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP ${WALL:+--time=$WALL} \
        --array=0-$((N_WORKERS - 1)) --export="ALL,WORK_ROOT=$WORK_ROOT,PHASE=search" suite_study.sbatch)"
RID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" --dependency="afterany:$SID" \
        --cpus-per-task=2 --mem=16G --time=02:00:00 \
        --output=logs/suite/report_%j.out --error=logs/suite/report_%j.err \
        --export="ALL,WORK_ROOT=$WORK_ROOT,PHASE=report,SEARCH_JOB=$SID" suite_study.sbatch)"
NAME="$(basename "$WORK_ROOT")"
echo "  search array: $SID ($N_WORKERS jobs)    logs: logs/suite/suite_${SID}_*.out"
echo "  report job:   $RID (after the search)   log:  logs/suite/report_${RID}.out"
echo
echo "Watch:    squeue -u \$USER;   grep complete logs/suite/suite_${SID}_*.out | tail"
echo "Results:  $WORK_ROOT/${NAME}_results.tar.gz   (report: $WORK_ROOT/analysis/$STUDY/report.md)"
