import csv
import os
import random

import pytest

pytest.importorskip("shap")
pytest.importorskip("sklearn")
optuna = pytest.importorskip("optuna")
import lazagna_shap as ls

optuna.logging.set_verbosity(optuna.logging.WARNING)


def _study(n=60, seed=3):
    rng = random.Random(0)

    def obj(trial):
        x1 = trial.suggest_float("x1", 0, 1)
        trial.suggest_float("x2", 0, 1)                      # no effect
        fam = trial.suggest_categorical("family", ["a", "b"])
        if fam == "a":
            trial.suggest_int("hb", 1, 4)                    # conditional, no effect
        gain = 3 * x1 + (2 if fam == "b" else 0) + rng.gauss(0, 0.1)
        trial.set_user_attr("cpd_impr_pct", gain)
        trial.set_user_attr("wl_impr_pct", -1.5 * x1 + rng.gauss(0, 0.05))
        return -gain, 0.0
    st = optuna.create_study(directions=["minimize", "minimize"], sampler=optuna.samplers.RandomSampler(seed=seed))
    st.optimize(obj, n_trials=n)
    return st


def test_recovers_known_effects():
    cpd, wl = ls.explain_study(_study(), n_repeats=3)
    rank = [e["param"] for e in cpd["importance"]]
    assert set(rank[:2]) == {"x1", "family"}
    assert cpd["cv_r2"] > 0.8
    by = {e["param"]: e for e in cpd["importance"]}
    assert by["x1"]["direction"] > 0.9
    assert by["family"]["by_category"]["b"] > by["family"]["by_category"]["a"]
    assert by["x2"]["share"] < 0.05
    assert wl["importance"][0]["param"] == "x1"
    assert {e["param"]: e for e in wl["importance"]}["x1"]["direction"] < -0.9


def test_conditional_parameter_does_not_steal_credit():
    """hb only exists when family == a. Filling it with a marker would let it carry the
    family effect; it must stay at noise level."""
    cpd, _ = ls.explain_study(_study(), n_repeats=3)
    hb = {e["param"]: e for e in cpd["importance"]}["hb"]
    assert hb["share"] < 0.05


def test_too_few_samples():
    with pytest.raises(ValueError, match="at least"):
        ls.explain_study(_study(n=5))


def test_csv_and_outputs(tmp_path):
    rng = random.Random(1)
    p = tmp_path / "runs.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "cluster", "layout", "gain"])
        for i in range(40):
            c = rng.random()
            lay = rng.choice(["split", "aligned"])
            w.writerow([f"r{i}", c, lay, -2 * c + (1 if lay == "split" else 0) + rng.gauss(0, 0.05)])
    table = ls.table_from_csv(str(p), ["gain"], id_col="run")
    assert table.params == ["cluster", "layout"]
    res = ls.shap_importance(table, "gain", n_repeats=2)
    assert {e["param"] for e in res["importance"]} == {"cluster", "layout"}
    paths = ls.write_outputs([res], str(tmp_path / "out"), plot=False, title="csv")
    names = sorted(os.path.basename(x) for x in paths)
    assert names == ["shap.json", "shap.md", "shap_gain.csv"]
    md = open(tmp_path / "out" / "shap.md").read()
    assert "surrogate CV R²" in md and "| cluster |" in md


def test_cli_on_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path / 's.db'}"
    st = optuna.create_study(study_name="s", storage=url, directions=["minimize", "minimize"],
                             sampler=optuna.samplers.RandomSampler(seed=0))
    rng = random.Random(2)

    def obj(t):
        a = t.suggest_float("a", 0, 1)
        t.set_user_attr("cpd_impr_pct", a + rng.gauss(0, 0.01))
        t.set_user_attr("wl_impr_pct", -a)
        return -a, a
    st.optimize(obj, n_trials=20)
    assert ls.main(["--storage", url, "--study", "s", "--out", str(tmp_path / "o"), "--no-plot", "--repeats", "2"]) == 0
    assert os.path.exists(tmp_path / "o" / "shap.md")
