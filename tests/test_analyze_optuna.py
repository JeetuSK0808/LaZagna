"""campaign/analyze_optuna.py on synthetic journals: the structured-study summary (now also for
designs outside its built-in koios/vtr list, and for 1x1 study names) and the report for a
multi-benchmark study. The script runs at import, so each run is a subprocess."""
import json
import os
import random
import subprocess
import sys

import pytest

from conftest import REPO

optuna = pytest.importorskip("optuna")
optuna.logging.set_verbosity(optuna.logging.WARNING)
STRUCT = ["dsp_on_l0", "bram_on_l0", "cluster", "stagger", "band_pos"]
SUITE = ["dsp_frac_l0", "bram_frac_l0", "cluster", "stagger", "band_pos"]
NO_SHAP = "import runpy, sys; sys.modules['shap'] = None; runpy.run_path(sys.argv[1], run_name='__main__')"


def _journal(work, name, directions=2):
    from lazagna_optuna import journal_storage
    os.makedirs(os.path.join(work, "journal"), exist_ok=True)
    return optuna.create_study(study_name=name, directions=["minimize"] * directions,
                               storage=journal_storage(os.path.join(work, "journal", f"{name}.log")),
                               sampler=optuna.samplers.RandomSampler(seed=0))


def structured_study(work, name, n=12, seed=0):
    rng = random.Random(seed)
    st = _journal(work, name)

    def obj(t):
        p = {"dsp_on_l0": t.suggest_int("dsp_on_l0", 0, 8), "bram_on_l0": t.suggest_int("bram_on_l0", 0, 8),
             "cluster": t.suggest_float("cluster", 0, 1), "stagger": t.suggest_float("stagger", 0, 1),
             "band_pos": t.suggest_float("band_pos", 0.15, 0.85)}
        cpd, wl = -5 * p["cluster"] + rng.gauss(0, 0.3), -8 * p["cluster"] + rng.gauss(0, 0.3)
        t.set_user_attr("cpd_impr_pct", cpd)
        t.set_user_attr("wl_impr_pct", wl)
        return -cpd, -wl
    st.optimize(obj, n_trials=n)


def suite_study(work, name="suite_structured_tpe", n=14, designs=("vtr/sha", "mcnc/clma")):
    rng = random.Random(1)
    st = _journal(work, name)
    for k, v in {"designs": list(designs), "search_mode": "structured", "sampler": "tpe", "seeds": 3,
                 "fidelity": "route", "arch_type": "combined", "objective_weights": [],
                 "link_penalty": 0.0}.items():
        st.set_user_attr(k, v)

    def obj(t):
        p = {k: t.suggest_float(k, 0, 1) for k in SUITE}
        t.suggest_categorical("connectivity", [1.0])
        t.suggest_float("delay_ratio", 0.739, 0.739)
        per = {}
        for i, d in enumerate(designs):
            c, w = 3 * p["dsp_frac_l0"] - i + rng.gauss(0, .2), -6 * p["cluster"] + rng.gauss(0, .2)
            per[d] = {"cpd": 1e-8, "wl": 1e3, "baseline_cpd": 1e-8 * (1 + i), "baseline_wl": 1e3 * (1 + i),
                      "cpd_impr_pct": c, "wl_impr_pct": w}
        cpd = sum(v["cpd_impr_pct"] for v in per.values()) / len(per)
        wl = sum(v["wl_impr_pct"] for v in per.values()) / len(per)
        for k, v in (("cpd_impr_pct", cpd), ("wl_impr_pct", wl), ("link_fraction", 1.0),
                     ("designs", list(designs)), ("per_design", per)):
            t.set_user_attr(k, v)
        return -cpd, -wl
    st.optimize(obj, n_trials=n)
    return st


def run_analysis(work, root, no_shap=False):
    env = dict(os.environ, WORK=work, LAZAGNA_ROOT=root, LAZAGNA_CODE=REPO, MPLBACKEND="Agg")
    script = os.path.join(REPO, "campaign", "analyze_optuna.py")
    cmd = [sys.executable, "-c", NO_SHAP, script] if no_shap else [sys.executable, script]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-3000:]
    return res.stdout


@pytest.mark.parametrize("no_shap", [True, False])
def test_structured_studies_for_any_suite(fake_root, tmp_path, no_shap):
    if not no_shap:
        pytest.importorskip("shap")
    work = str(tmp_path / "work")
    structured_study(work, "columns_eltwise_layer_tall_route_structured")
    structured_study(work, "columns_clma_tall_route_structured")             # mcnc: not in the old list
    structured_study(work, "columns_tpu_like_small_os_1x1_place_structured")  # TALL=0 study name
    structured_study(work, "columns_nosuch_tall_route_structured")           # in no suite
    out = run_analysis(work, fake_root, no_shap)
    assert ("SHAP tables skipped" in out) == no_shap
    tasks = [json.loads(l) for l in open(os.path.join(work, "tasks_validate.jsonl")) if l.strip()]
    assert {t["design"] for t in tasks} == {"koios/eltwise_layer", "mcnc/clma", "koios/tpu_like.small.os"}
    assert all(t["kind"] == "custom" and set(t["structured"]) == set(STRUCT) for t in tasks)
    md = open(os.path.join(work, "optuna_summary.md")).read()
    assert "## clma (12 trials)" in md and "## tpu_like_small_os (12 trials)" in md
    assert "(No validation tasks: design 'nosuch'" in md
    assert ("SHAP importance" in md) != no_shap
    assert not os.path.exists(os.path.join(work, "analysis"))      # no multi-benchmark study here


def test_multi_benchmark_report(fake_root, tmp_path):
    work = str(tmp_path / "work")
    suite_study(work)
    structured_study(work, "columns_eltwise_layer_tall_route_structured")
    out = run_analysis(work, fake_root)
    d = os.path.join(work, "analysis", "suite_structured_tpe")
    rep = open(os.path.join(d, "report.md")).read()
    assert "suite_structured_tpe: 14 complete trials" in out
    for s in ("# Multi-benchmark study: suite_structured_tpe", "Designs: vtr/sha, mcnc/clma",
              "## Pareto front", "## Champion: trial", "| vtr/sha |", "| mcnc/clma |", "**geomean**",
              "## Spearman correlation", "| dsp_frac_l0 |", "## Top trials", "tasks_champion.jsonl"):
        assert s in rep, s
    for f in ("pareto.csv", "pareto.md", "pareto.json", "trials.csv", "tasks_champion.jsonl"):
        assert os.path.exists(os.path.join(d, f)), f
    tasks = [json.loads(l) for l in open(os.path.join(d, "tasks_champion.jsonl"))]
    assert [t["kind"] for t in tasks] == ["rq1", "custom", "rq1", "custom"]
    assert [t["id"] for t in tasks if t["kind"] == "rq1"] == ["rq1__sha", "rq1__clma"]
    champ = json.load(open(os.path.join(d, "pareto.json")))["champion_id"]
    assert all(t["id"] == f"champ__suite_structured_tpe__{t['design'].split('/')[1]}" and
               set(t["structured_frac"]) == set(SUITE) and t["conn"] == 1.0 for t in tasks if t["kind"] == "custom")
    st = optuna.load_study(study_name="suite_structured_tpe",
                           storage=__import__("lazagna_optuna").journal_storage(
                               os.path.join(work, "journal", "suite_structured_tpe.log")))
    assert tasks[1]["structured_frac"]["dsp_frac_l0"] == st.trials[champ].params["dsp_frac_l0"]
    if __import__("importlib").util.find_spec("shap"):
        assert "SHAP importance" in rep and os.path.exists(os.path.join(d, "shap.md"))
    # the structured study next to it is summarized as before
    assert "## eltwise_layer (12 trials)" in open(os.path.join(work, "optuna_summary.md")).read()


def test_multi_benchmark_report_without_shap(fake_root, tmp_path):
    work = str(tmp_path / "work")
    suite_study(work)
    run_analysis(work, fake_root, no_shap=True)
    rep = open(os.path.join(work, "analysis", "suite_structured_tpe", "report.md")).read()
    assert "SHAP importance skipped" in rep and "## Pareto front" in rep
