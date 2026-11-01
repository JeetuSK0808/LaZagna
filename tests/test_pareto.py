import csv
import json
import os
import random

import pytest

import lazagna_pareto as lp


def test_front_maximizes_both_and_keeps_ties():
    xs = [1, 2, 3, 2, 0, 3]
    ys = [5, 4, 1, 2, 5, 1]
    # (2,2) is beaten by (2,4); (0,5) by (1,5); the two (3,1) points tie and both stay
    assert lp.pareto_front(xs, ys) == [0, 1, 2, 5]
    assert lp.pareto_front([], []) == []


def test_front_matches_brute_force():
    rng = random.Random(0)
    pts = [(rng.gauss(0, 1), rng.gauss(0, 1)) for _ in range(200)]
    front = set(lp.pareto_front([p[0] for p in pts], [p[1] for p in pts]))
    for i, (x, y) in enumerate(pts):
        beaten = any(a >= x and b >= y and (a, b) != (x, y) for a, b in pts)
        assert (i in front) == (not beaten)


def _pts(xy, links=None):
    return [{"id": i, "x": x, "y": y, "link_fraction": (links or [None] * len(xy))[i], "params": {}}
            for i, (x, y) in enumerate(xy)]


def test_champion_by_weights_and_link_penalty():
    pts = _pts([(10, 0), (6, 6), (0, 10)], links=[1.0, 1.0, 0.1])
    front = lp.pareto_front([p["x"] for p in pts], [p["y"] for p in pts])
    assert lp.choose_champion(pts, front) == 1                       # 12 beats 10 and 10
    assert lp.choose_champion(pts, front, weights=(1, 0)) == 0       # CPD only
    assert lp.choose_champion(pts, front, link_penalty=4) == 2       # 12-8=4 < 10-0.8
    assert lp.choose_champion(pts, front, best_id=0) == 0            # a weighted study's best trial
    assert lp.choose_champion([], []) is None


def _study(directions, n=25, seed=1):
    optuna = pytest.importorskip("optuna")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rng = random.Random(seed)

    def obj(t):
        a = t.suggest_float("a", 0, 1)
        cpd, wl = 10 * a + rng.gauss(0, 1), 10 * (1 - a) + rng.gauss(0, 1)
        t.set_user_attr("cpd_impr_pct", cpd)
        t.set_user_attr("wl_impr_pct", wl)
        t.set_user_attr("link_fraction", 1.0)
        return (-cpd, -wl) if len(directions) == 2 else -(cpd + 3 * wl)
    st = optuna.create_study(directions=directions, sampler=optuna.samplers.RandomSampler(seed=seed))
    st.optimize(obj, n_trials=n)
    return st


def test_study_analysis_pareto_and_weighted():
    st = _study(["minimize", "minimize"])
    pts, res = lp.study_analysis(st)
    assert len(pts) == 25 and res["champion"] in res["front"]
    best_sum = max(res["front"], key=lambda i: pts[i]["x"] + pts[i]["y"])
    assert res["champion"] == best_sum
    st1 = _study(["minimize"])
    pts1, res1 = lp.study_analysis(st1)
    assert pts1[res1["champion"]]["id"] == st1.best_trial.number
    assert "best trial" in res1["champion_rule"]


def test_study_weights_come_from_user_attrs():
    st = _study(["minimize", "minimize"])
    st.set_user_attr("objective_weights", [1.0, 0.0])
    pts, res = lp.study_analysis(st)
    assert res["weights"] == [1.0, 0.0]
    assert pts[res["champion"]]["x"] == max(pts[i]["x"] for i in res["front"])


def test_outputs(tmp_path):
    st = _study(["minimize", "minimize"])
    pts, res = lp.study_analysis(st)
    paths = lp.write_outputs(pts, res, str(tmp_path), title="s", plot_png=False)
    assert sorted(os.path.basename(p) for p in paths) == ["pareto.csv", "pareto.json", "pareto.md"]
    rows = list(csv.DictReader(open(tmp_path / "pareto.csv")))
    assert len(rows) == 25 and sum(int(r["on_front"]) for r in rows) == len(res["front"])
    assert sum(int(r["champion"]) for r in rows) == 1 and "a" in rows[0]
    meta = json.load(open(tmp_path / "pareto.json"))
    assert meta["champion_id"] == pts[res["champion"]]["id"]
    assert "(champion)" in open(tmp_path / "pareto.md").read()


def test_plot(tmp_path):
    pytest.importorskip("matplotlib")
    st = _study(["minimize", "minimize"])
    pts, res = lp.study_analysis(st)
    assert lp.plot(pts, res, str(tmp_path / "p.png"), title="t")
    assert os.path.getsize(tmp_path / "p.png") > 1000


def test_cli_on_sqlite_and_csv(tmp_path):
    optuna = pytest.importorskip("optuna")
    url = f"sqlite:///{tmp_path / 's.db'}"
    st = optuna.create_study(study_name="s", storage=url, directions=["minimize", "minimize"])
    for a in (0.1, 0.5, 0.9):
        t = st.ask()
        t.suggest_float("a", 0, 1)
        t.set_user_attr("cpd_impr_pct", 10 * a)
        t.set_user_attr("wl_impr_pct", 10 * (1 - a))
        st.tell(t, (-10 * a, -10 * (1 - a)))
    assert lp.main(["--storage", url, "--study", "s", "--out", str(tmp_path / "o"), "--no-plot"]) == 0
    assert os.path.exists(tmp_path / "o" / "pareto.md")
    p = tmp_path / "runs.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "cpd_gain", "wl_gain"])
        w.writerows([["r1", 1, 5], ["r2", 4, 4], ["r3", 0, 0]])
    assert lp.main(["--csv", str(p), "--x", "cpd_gain", "--y", "wl_gain", "--id-col", "run",
                    "--out", str(tmp_path / "c"), "--no-plot"]) == 0
    meta = json.load(open(tmp_path / "c" / "pareto.json"))
    assert meta["front_ids"] == ["r1", "r2"] and meta["champion_id"] == "r2"
