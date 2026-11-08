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


# ---- vertical links as a third objective ------------------------------------------------------

def test_front_with_links_matches_brute_force():
    rng = random.Random(2)
    pts = [(rng.gauss(0, 1), rng.gauss(0, 1), rng.choice([0.05, 0.1, 0.25, 0.5, 1.0])) for _ in range(150)]
    front = set(lp.pareto_front_links(*zip(*pts)))
    for i, (x, y, l) in enumerate(pts):
        beaten = any(a >= x and b >= y and c <= l and (a, b, c) != (x, y, l) for a, b, c in pts)
        assert (i in front) == (not beaten)
    # fewer links keeps a point that the 2D front would drop
    assert lp.pareto_front_links([1, 2], [1, 2], [0.1, 1.0]) == [0, 1]
    assert lp.pareto_front([1, 2], [1, 2]) == [1]


def test_best_and_lean_champions():
    pts = _pts([(6, 6), (5, 5), (4, 3), (1, 1), (6, 6)], links=[1.0, 0.5, 0.1, 0.05, 0.5])
    res = lp.analyze_links(pts)
    assert res["front"] == [2, 3, 4]                     # 0 is beaten by 4 (same gains, fewer links)
    assert res["champion"] == 4 and res["lean"] == 2     # lean: best of the points with links <= 0.1
    assert lp.analyze_links(pts, max_links=0.01)["lean"] is None
    assert lp.analyze_links(pts, max_links=1.0)["lean"] == 4       # the best champion is also lean
    assert lp.analyze_links(pts, weights=(0, 1))["champion"] == 4
    assert lp.analyze_links([], max_links=0.1)["champion"] is None


def _links_study(n=24, seed=4):
    optuna = pytest.importorskip("optuna")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rng = random.Random(seed)

    def obj(t):
        a = t.suggest_float("a", 0, 1)
        links = t.suggest_categorical("connectivity", [0.25, 0.5, 1.0]) * t.suggest_categorical(
            "vertical_connectivity", [0.05, 0.1, 1.0])
        cpd, wl = 10 * a + 3 * links + rng.gauss(0, 1), 10 * (1 - a) + 4 * links + rng.gauss(0, 1)
        t.set_user_attr("cpd_impr_pct", cpd)
        t.set_user_attr("wl_impr_pct", wl)
        t.set_user_attr("link_fraction", links)
        return -cpd, -wl, links
    st = optuna.create_study(directions=["minimize"] * 3, sampler=optuna.samplers.RandomSampler(seed=seed))
    st.optimize(obj, n_trials=n)
    return st


def test_study_with_links_objective(tmp_path):
    st = _links_study()
    pts, res = lp.study_analysis(st)
    assert res["objectives"] == 3 and res["max_links"] == 0.1 and len(pts) == 24
    front = set(lp.pareto_front_links([p["x"] for p in pts], [p["y"] for p in pts],
                                      [p["link_fraction"] for p in pts]))
    assert set(res["front"]) == front
    best = max(front, key=lambda i: pts[i]["x"] + pts[i]["y"])
    assert res["champion"] == best
    lean_pool = [i for i in front if pts[i]["link_fraction"] <= 0.1]
    assert res["lean"] == max(lean_pool, key=lambda i: pts[i]["x"] + pts[i]["y"])
    assert lp.study_analysis(st, max_links=0.25)[1]["max_links"] == 0.25
    paths = lp.write_outputs(pts, res, str(tmp_path), title="s", plot_png=False)
    assert sorted(os.path.basename(p) for p in paths) == ["pareto.csv", "pareto.json", "pareto.md"]
    rows = list(csv.DictReader(open(tmp_path / "pareto.csv")))
    assert list(rows[0])[:7] == ["id", "cpd_gain_pct", "wl_gain_pct", "link_fraction", "on_front", "champion", "lean"]
    assert sum(int(r["lean"]) for r in rows) == 1 and sum(int(r["champion"]) for r in rows) == 1
    meta = json.load(open(tmp_path / "pareto.json"))
    assert meta["lean_id"] == pts[res["lean"]]["id"] and meta["champion_id"] == pts[best]["id"]
    md = open(tmp_path / "pareto.md").read()
    assert "| trial | links | CPD gain % | WL gain % | params |" in md
    assert "**(best)**" in md and "**(lean)**" in md and "links <= 0.1" in md
    shown = [float(l.split("|")[2]) for l in md.splitlines() if l.startswith("| ") and l[2].isdigit()]
    assert len(shown) == len(front) and shown == sorted(shown)          # sorted by links


def test_links_from_the_objective_value_when_the_attr_is_missing():
    optuna = pytest.importorskip("optuna")
    st = optuna.create_study(directions=["minimize"] * 3)
    for x, y, l in ((1, 2, 0.5), (2, 1, 0.05)):
        t = st.ask()
        t.set_user_attr("cpd_impr_pct", x)
        t.set_user_attr("wl_impr_pct", y)
        st.tell(t, (-x, -y, l))
    pts, res = lp.study_analysis(st)
    assert [p["link_fraction"] for p in pts] == [0.5, 0.05] and res["lean"] == 1


def test_plot_links(tmp_path):
    pytest.importorskip("matplotlib")
    st = _links_study()
    pts, res = lp.study_analysis(st)
    assert lp.plot(pts, res, str(tmp_path / "p.png"), title="t")
    assert os.path.getsize(tmp_path / "p.png") > 1000


def test_cli_links_objective(tmp_path):
    p = tmp_path / "runs.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "cpd_gain", "wl_gain", "link_fraction"])
        w.writerows([["r1", 5, 5, 1.0], ["r2", 4, 4, 0.1], ["r3", 1, 1, 0.05], ["r4", 0, 0, ""]])
    assert lp.main(["--csv", str(p), "--x", "cpd_gain", "--y", "wl_gain", "--id-col", "run", "--links-objective",
                    "--out", str(tmp_path / "o"), "--no-plot"]) == 0
    meta = json.load(open(tmp_path / "o" / "pareto.json"))
    assert meta["front_ids"] == ["r1", "r2", "r3"] and meta["champion_id"] == "r1" and meta["lean_id"] == "r2"
    assert lp.main(["--csv", str(p), "--x", "cpd_gain", "--y", "wl_gain", "--id-col", "run", "--links-objective",
                    "--max-links", "0.05", "--out", str(tmp_path / "o2"), "--no-plot"]) == 0
    assert json.load(open(tmp_path / "o2" / "pareto.json"))["lean_id"] == "r3"
