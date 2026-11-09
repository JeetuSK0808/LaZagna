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


# sha1[:16] of the outputs for suite_study() without SHAP, computed with the code of origin/main
# (361e9b0) on optuna 4.9 and 5.0: the 2-objective report must not change.
GOLDEN_2OBJ = {"report.md": "534d3bfa30582147", "pareto.csv": "ba7a1da7e494ae14", "pareto.md": "81b88f3b1fac6f0a",
               "pareto.json": "d5543731315f8edd", "trials.csv": "c4064d4591006e19",
               "tasks_champion.jsonl": "b683219b9acf5bcf"}


def test_two_objective_report_unchanged(fake_root, tmp_path):
    pytest.importorskip("matplotlib")        # the golden report embeds pareto.png
    import hashlib
    work = str(tmp_path / "work")
    suite_study(work)
    run_analysis(work, fake_root, no_shap=True)
    d = os.path.join(work, "analysis", "suite_structured_tpe")
    got = {f: hashlib.sha1(open(os.path.join(d, f), "rb").read()).hexdigest()[:16] for f in GOLDEN_2OBJ}
    assert got == GOLDEN_2OBJ


def links_suite_study(work, name="suite_links", n=16, designs=("vtr/sha", "mcnc/clma"), place=1.0, noise=1.0):
    """A study with vertical links as the third objective, like LINKS_OBJECTIVE=1 ANCHORS=1 runs:
    sampled connectivity / vertical connectivity, the "recommended" anchor first, and (place set)
    placement gains = routed gains + place + noise."""
    rng = random.Random(5)
    st = _journal(work, name, directions=3)
    for k, v in {"designs": list(designs), "search_mode": "structured", "sampler": "tpe", "seeds": 3,
                 "fidelity": "route", "arch_type": "combined", "objective_weights": [], "link_penalty": 0.0,
                 "connectivity_choices": [0.25, 0.5, 1.0], "vertical_connectivity_choices": [0.05, 0.1, 1.0],
                 "links_objective": True, "anchors": True}.items():
        st.set_user_attr(k, v)
    st.enqueue_trial({"dsp_frac_l0": 1.0, "bram_frac_l0": 0.0, "cluster": 0.0, "stagger": 0.501, "band_pos": 0.5,
                      "connectivity": 1.0, "delay_ratio": 0.739, "vertical_connectivity": 0.1},
                     user_attrs={"seeded_from": "recommended"})

    def obj(t):
        p = {k: t.suggest_float(k, 0, 1) for k in SUITE}
        conn = t.suggest_categorical("connectivity", [0.25, 0.5, 1.0])
        t.suggest_float("delay_ratio", 0.739, 0.739)
        links = conn * t.suggest_categorical("vertical_connectivity", [0.05, 0.1, 1.0])
        per = {}
        for i, d in enumerate(designs):
            c, w = 3 * p["dsp_frac_l0"] - i + 2 * links + rng.gauss(0, .2), -6 * p["cluster"] + 3 * links + rng.gauss(0, .2)
            per[d] = {"cpd": 1e-8, "wl": 1e3, "baseline_cpd": 1e-8 * (1 + i), "baseline_wl": 1e3 * (1 + i),
                      "cpd_impr_pct": c, "wl_impr_pct": w}
            if place is not None:
                per[d].update(place_cpd_impr_pct=c + place + rng.gauss(0, noise) * (noise > 0),
                              place_wl_impr_pct=w + 2 * place + rng.gauss(0, noise) * (noise > 0))
        mean = lambda k: sum(v[k] for v in per.values()) / len(per)
        for k, v in (("cpd_impr_pct", mean("cpd_impr_pct")), ("wl_impr_pct", mean("wl_impr_pct")),
                     ("link_fraction", links), ("designs", list(designs)), ("per_design", per)):
            t.set_user_attr(k, v)
        if place is not None:
            t.set_user_attr("place_cpd_impr_pct", mean("place_cpd_impr_pct"))
            t.set_user_attr("place_wl_impr_pct", mean("place_wl_impr_pct"))
        return -mean("cpd_impr_pct"), -mean("wl_impr_pct"), links
    st.optimize(obj, n_trials=n)
    return st


def test_three_objective_report(fake_root, tmp_path):
    work = str(tmp_path / "work")
    st = links_suite_study(work)
    out = run_analysis(work, fake_root, no_shap=True)
    d = os.path.join(work, "analysis", "suite_links")
    rep = open(os.path.join(d, "report.md")).read()
    meta = json.load(open(os.path.join(d, "pareto.json")))
    best, lean = meta["champion_id"], meta["lean_id"]
    assert best is not None and lean is not None and best != lean
    assert f"lean champion trial {lean}" in out
    for s in ("objective: three objectives (CPD gain, WL gain, vertical links), Pareto front",
              "## Pareto front: CPD gain, WL gain and vertical links", "| trial | links | CPD gain % | WL gain % |",
              f'## Champion "best": trial {best}', f'## Champion "lean": trial {lean}', "links <= 0.1",
              "| trial | CPD gain % | WL gain % | links | vtr/sha | mcnc/clma |", "Anchors (known layouts queued first): "
              "recommended = trial 0", "## Placement vs routing", "both champions"):
        assert s in rep, s
    assert st.trials[lean].user_attrs["link_fraction"] <= 0.1
    tasks = [json.loads(l) for l in open(os.path.join(d, "tasks_champion.jsonl"))]
    assert [t["id"] for t in tasks] == [f"{p}__{x}" for x in ("sha", "clma")
                                        for p in ("rq1", "champ__suite_links", "lean__suite_links")]
    for t in tasks:
        if t["kind"] == "custom":
            tr = st.trials[best if t["id"].startswith("champ") else lean]
            assert (t["conn"], t["vconn"], t["delay"]) == (tr.params["connectivity"],
                                                           tr.params["vertical_connectivity"], 0.739)
            assert t["structured_frac"] == {k: tr.params[k] for k in SUITE} and t["seeds"] == 5
    import csv
    rows = list(csv.DictReader(open(os.path.join(d, "trials.csv"))))
    assert sum(int(r["lean"]) for r in rows) == 1 and int(rows[lean]["lean"]) == 1
    assert "place_cpd_impr_pct" in rows[0] and "place_wl_impr_pct_mcnc/clma" in rows[0]
    if __import__("importlib").util.find_spec("matplotlib"):
        assert "![Pareto front: WL and CPD gain against vertical links](pareto.png)" in rep


def test_lean_champion_missing_or_same(fake_root, tmp_path):
    work = str(tmp_path / "work")
    links_suite_study(work)
    env_out = subprocess.run([sys.executable, "-c", NO_SHAP, os.path.join(REPO, "campaign", "analyze_optuna.py")],
                             env=dict(os.environ, WORK=work, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO,
                                      MPLBACKEND="Agg", CHAMPION_MAX_LINKS="0.001"),
                             capture_output=True, text=True, cwd=REPO)
    assert env_out.returncode == 0, env_out.stderr[-2000:]
    d = os.path.join(work, "analysis", "suite_links")
    rep = open(os.path.join(d, "report.md")).read()
    assert "No front point has links <= 0.001" in rep and json.load(open(os.path.join(d, "pareto.json")))["lean_id"] is None
    assert [t["id"].split("__")[0] for t in map(json.loads, open(os.path.join(d, "tasks_champion.jsonl")))] == \
        ["rq1", "champ", "rq1", "champ"]
    subprocess.run([sys.executable, "-c", NO_SHAP, os.path.join(REPO, "campaign", "analyze_optuna.py")],
                   env=dict(os.environ, WORK=work, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO, MPLBACKEND="Agg",
                            CHAMPION_MAX_LINKS="1"), capture_output=True, text=True, cwd=REPO, check=True)
    assert "the best champion" in open(os.path.join(d, "report.md")).read()


def test_placement_vs_routing_section(fake_root, tmp_path):
    """Placement gains = routed gains + 1 (CPD) / + 2 (WL) points: rho 1, the offsets exact, the
    same ranking. Without placement data there is no such section."""
    work = str(tmp_path / "exact")
    links_suite_study(work, place=1.0, noise=0.0)
    run_analysis(work, fake_root, no_shap=True)
    rep = open(os.path.join(work, "analysis", "suite_links", "report.md")).read()
    sec = rep.split("## Placement vs routing", 1)[1]
    assert "| geomean over the designs | 16 | +1.00 | +1.00 | +1.00 | +2.00 |" in sec
    assert "| trial × design pairs | 32 | +1.00 | +1.00 | +1.00 | +2.00 |" in sec
    assert "| vtr/sha | 16 |" in sec and "| mcnc/clma | 16 |" in sec
    assert "Placement and routing rank the trials the same way." in sec
    noisy = str(tmp_path / "noisy")
    links_suite_study(noisy, place=0.0, noise=6.0)
    run_analysis(noisy, fake_root, no_shap=True)
    sec = open(os.path.join(noisy, "analysis", "suite_links", "report.md")).read().split("## Placement vs routing", 1)[1]
    assert "Largest rank disagreements" in sec and "| rank by placement | rank by routing |" in sec
    none = str(tmp_path / "none")
    links_suite_study(none, place=None)
    run_analysis(none, fake_root, no_shap=True)
    d = os.path.join(none, "analysis", "suite_links")
    assert "Placement vs routing" not in open(os.path.join(d, "report.md")).read()
    assert "place_cpd_impr_pct" not in open(os.path.join(d, "trials.csv")).readline()


def test_journal_with_only_multi_benchmark_studies(fake_root, tmp_path):
    work = str(tmp_path / "work")
    suite_study(work)
    links_suite_study(work)
    run_analysis(work, fake_root, no_shap=True)
    assert open(os.path.join(work, "optuna_summary.md")).read() == (
        "# Structured layout search (Optuna, routed, 3 seeds)\n\nNo single-design studies in this journal; see "
        "analysis/suite_links/report.md, analysis/suite_structured_tpe/report.md\n")
    assert json.load(open(os.path.join(work, "optuna_summary.json"))) == {}
    single = str(tmp_path / "single")
    structured_study(single, "columns_eltwise_layer_tall_route_structured")
    run_analysis(single, fake_root, no_shap=True)
    assert "No single-design studies" not in open(os.path.join(single, "optuna_summary.md")).read()
