#!/bin/bash
# ============================================================================
# Multi-benchmark Optuna study, both phases in one job script. Normally submitted by
# campaign/suite_study.sh, which writes the settings to $WORK_ROOT/suite_study.env.
#   PHASE=search (array)   each task runs campaign/suite_study.py; all tasks share one
#                          Optuna study through $WORK_ROOT/journal (N tasks = N trials in flight)
#   PHASE=report (single)  campaign/analyze_optuna.py (Pareto front, Spearman, SHAP), then
#                          ONE results file: $WORK_ROOT/<name>_results.tar.gz
# By hand, from the repo root:
#   sbatch -A gts-<PI> --array=0-7 --export=ALL,WORK_ROOT=<dir>,PHASE=search suite_study.sbatch
#   sbatch -A gts-<PI> --dependency=afterany:<search job> --export=ALL,WORK_ROOT=<dir>,PHASE=report \
#          --output=logs/suite/report_%j.out --error=logs/suite/report_%j.err suite_study.sbatch
# The report phase needs scikit-learn + shap (+ matplotlib for the plots) for the SHAP tables.
# If the image lacks them, they are pip-installed once into campaign_work/pyextras (outside the
# image; INSTALL_EXTRAS=0 skips that). Without them the report is written without SHAP.
# ============================================================================
#SBATCH --job-name=lazagna_suite
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G   # as worker_array.sbatch: 3D RRG generation peaks ~19 GB
#SBATCH -q inferno
#SBATCH --time=16:00:00
#SBATCH --output=logs/suite/suite_%A_%a.out
#SBATCH --error=logs/suite/suite_%A_%a.err
set -u

module load apptainer 2>/dev/null || true
command -v apptainer >/dev/null || { echo "FATAL: apptainer not found"; exit 1; }

CAMPAIGN="${CAMPAIGN:-$SLURM_SUBMIT_DIR}"
SIF="${SIF:-$CAMPAIGN/lazagna.sif}"
WORK_ROOT="${WORK_ROOT:?WORK_ROOT not set (use campaign/suite_study.sh)}"
PHASE="${PHASE:-search}"
[ -f "$WORK_ROOT/suite_study.env" ] && . "$WORK_ROOT/suite_study.env"
[ -f "$SIF" ] || { echo "FATAL: missing SIF $SIF"; exit 1; }
# Stale-image guard: the bind mountpoints only exist in images built from the parallel .def.
if ! apptainer exec --no-home --cleanenv "$SIF" test -d /opt/LaZagna/base_rrg; then
  echo "FATAL: lazagna.sif is STALE. rm lazagna.sif && bash campaign/suite_study.sh (it rebuilds it)"; exit 1
fi

. "$CAMPAIGN/campaign/binds.sh"

if [ "$PHASE" = search ]; then
  ID="${SLURM_ARRAY_TASK_ID:-0}"
  W="$WORK_ROOT/worker_$ID"
  lazagna_binds "$W"
  export APPTAINERENV_WORKER_ID="$ID"
  # APPTAINERENV_* survives --cleanenv (values with spaces/commas, e.g. DESIGNS, stay intact).
  for v in DESIGNS SEARCH_MODE SAMPLER TRIALS STUDY SEEDS FIDELITY CW TALL TARGET_UTIL \
           CONN_CHOICES DELAY WEIGHTS LINK_PENALTY KEEP_RRG \
           VCONN_CHOICES LINKS_OBJECTIVE ANCHORS NSGA_POP; do
    if [ -n "${!v:-}" ]; then export "APPTAINERENV_$v=${!v}"; fi
  done
  # The qmc sampler draws its Sobol sequence with scipy, which the image does not ship.
  # Install it for this worker, outside the image (--no-deps: numpy comes from the image).
  if [ "${SAMPLER:-tpe}" = qmc ] && ! apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" \
       python3 -c "import scipy.stats" 2>/dev/null; then
    mkdir -p "$W/pyscipy"
    BINDS+=(-B "$W/pyscipy:/pyscipy")
    apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 -m pip install --quiet --no-cache-dir \
        --disable-pip-version-check --no-deps --target /pyscipy scipy \
      || echo "WARNING: could not install scipy; the qmc sampler will fail"
    export APPTAINERENV_PYTHONPATH="/code:/pyscipy"
  fi
  echo "SUITE WORKER $ID START $(date -Is)  work=$W"
  apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF" python3 /campaign/suite_study.py
  rc=$?
  rm -rf "$W"/{base_rrg,rrg_3d}   # multi-GB, only useful inside a trial
  echo "SUITE WORKER $ID DONE rc=$rc $(date -Is)"
  exit $rc
fi

[ "$PHASE" = report ] || { echo "FATAL: PHASE must be search or report, not '$PHASE'"; exit 1; }
lazagna_binds "$WORK_ROOT/report"
EXTRAS="${EXTRAS_DIR:-$CAMPAIGN/campaign_work/pyextras}"
mkdir -p "$EXTRAS"
BINDS+=(-B "$EXTRAS:/pyextras")
export APPTAINERENV_PYTHONPATH="/code:/pyextras"
# the "lean" champion's link budget (studies with LINKS_OBJECTIVE=1)
if [ -n "${CHAMPION_MAX_LINKS:-}" ]; then export APPTAINERENV_CHAMPION_MAX_LINKS="$CHAMPION_MAX_LINKS"; fi
APP=(apptainer exec --no-home --cleanenv "${BINDS[@]}" "$SIF")
echo "SUITE REPORT START $(date -Is)  work=$WORK_ROOT"
if ! "${APP[@]}" python3 -c "import sklearn, shap, matplotlib" 2>/dev/null; then
  if [ "${INSTALL_EXTRAS:-1}" != 0 ]; then
    echo "scikit-learn / shap / matplotlib are not in the image: installing them into $EXTRAS"
    "${APP[@]}" python3 -m pip install --quiet --no-cache-dir --disable-pip-version-check --upgrade \
        --target /pyextras -r /code/requirements-analysis.txt \
      || echo "WARNING: could not install the analysis extras; the report skips SHAP (and the plots)"
  else
    echo "INSTALL_EXTRAS=0: the report skips SHAP (and the plots)"
  fi
fi
"${APP[@]}" python3 /campaign/analyze_optuna.py || echo "WARNING: analyze_optuna.py failed (rc=$?)"

# One file with everything: the Optuna journal (every trial, all per-design numbers), the
# references, the analysis, the settings, the designs' devices, and this study's SLURM logs.
# Left out: per-worker VPR dirs and the staged design copies (the sources are in benchmarks/).
mkdir -p "$WORK_ROOT/logs"
for f in "$CAMPAIGN"/logs/suite/suite_"${SEARCH_JOB:-none}"_* "$CAMPAIGN"/logs/suite/report_"${SLURM_JOB_ID:-none}".*; do
  [ -f "$f" ] && cp -p "$f" "$WORK_ROOT/logs/"
done
NAME="$(basename "$WORK_ROOT")"
OUT="$WORK_ROOT/${NAME}_results.tar.gz"
tar -czf "$OUT.tmp" -C "$(dirname "$WORK_ROOT")" \
    --exclude="$NAME/worker_*" --exclude="$NAME/report" --exclude="$NAME/bench" \
    --exclude="$NAME/${NAME}_results.tar.gz*" "$NAME"
rc=$?
if [ "$rc" -le 1 ] && [ -s "$OUT.tmp" ]; then   # 1 = a file changed while being read; still usable
  mv "$OUT.tmp" "$OUT"
  echo "RESULTS: $OUT"
else
  echo "WARNING: bundling failed (tar rc=$rc); the outputs are still in $WORK_ROOT"
fi
echo "SUITE REPORT DONE $(date -Is)"
