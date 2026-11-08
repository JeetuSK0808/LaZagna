"""Vertical links in the multi-benchmark search: sampled vertical connectivity, links as a third
objective, anchors (the known layouts as the first trials), placement estimates kept from
routed runs, the NSGA population, and the defaults unchanged. The flow is mocked out."""
import dataclasses
import glob
import hashlib
import json
import math
import os

import pytest

from conftest import REPO

optuna = pytest.importorskip("optuna")
import lazagna_optuna as lo

optuna.logging.set_verbosity(optuna.logging.WARNING)
TRIO = ("koios/tpu_like.small.ws", "vtr/mkDelayWorker32B", "vtr/stereovision2")
TRIO_FILES = ("koios/tpu_like.small.ws.v", "VTR_benchmarks/mkDelayWorker32B.v", "VTR_benchmarks/stereovision2.v")
STUDY_RESULTS = os.path.join(REPO, "docs", "study", "results")


@pytest.fixture
def cfg(fake_root, tmp_path):
    return lo.SearchConfig(lazagna_root=fake_root, benchmark_dir="", benchmarks=("vtr/sha", "mcnc/clma"),
                           search_mode="structured", autosize_designs=False, width=26, height=26,
                           stage_dir=str(tmp_path / "stage"), run_tag="t", fidelity="place")


def fake_factory(log, place=True):
    """A stand-in for _run_one: deterministic CPD / WL per (design, layout, links, delay); the
    reference is (10, 1000) / (5, 400). Routed runs fill `info` like evaluate(): per-seed
    placement estimates (90% / 80% of the routed values, plus a layout-dependent wobble)."""
    base = {"suite_sha": (10.0, 1000.0), "suite_clma": (5.0, 400.0)}

    def fake(cfg, spec, name, arch_type, conn, delay, connection_type="subset", **kw):
        d = os.path.basename(cfg.benchmark_dir)
        vconn = kw.get("vertical_connectivity", 1)
        log.append({"design": d, "name": name, "conn": conn, "vconn": vconn, "kw": sorted(kw), "spec": spec})
        b = base[d]
        if name.endswith("ref"):
            cpd, wl = b
        else:
            h = int(hashlib.sha1(repr((d, getattr(spec, "columns", spec), conn, vconn, delay)).encode()).hexdigest(), 16)
            f = 1 + ((h % 100) / 100 - 0.5) * 0.1 + 0.05 * (1 - conn) + 0.02 * (1 - vconn)
            cpd, wl = b[0] * f, b[1] * f
        if "info" in kw and place:
            w = (1 + ((int(hashlib.sha1(name.encode()).hexdigest(), 16) % 7) - 3) * 0.004
                 if not name.endswith("ref") else 1.0)
            kw["info"]["per_seed"] = [{"seed": s, "rc": 0, "place_cpd": 0.9 * cpd * w, "place_wl": 0.8 * wl * w,
                                       "route_cpd": cpd, "route_wl": wl} for s in (1, 2, 3)]
        return (cpd, wl), None
    return fake


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(lo, "_run_one", fake_factory(log))
    return log


def run(c, n=6, sampler=None, designs=None, baseline_dir=None):
    st = optuna.create_study(directions=["minimize"] * lo.n_objectives(c),
                             sampler=sampler or optuna.samplers.RandomSampler(seed=3))
    st.optimize(lo.make_suite_objective(c, designs=designs or lo.design_configs(c), baseline_dir=baseline_dir),
                n_trials=n)
    return st


# ---- A. vertical connectivity ----------------------------------------------------------------

def test_default_vertical_connectivity_is_not_sampled(cfg, calls):
    st = run(cfg)
    assert all("vertical_connectivity" not in t.params for t in st.trials)
    # _run_one is called exactly as before the option (no vertical_connectivity argument)
    assert all("vertical_connectivity" not in c["kw"] for c in calls)
    assert all(t.user_attrs["link_fraction"] == t.params["connectivity"] for t in st.trials)


@pytest.mark.parametrize("mode", ["structured", "layout"])
def test_vertical_connectivity_sampled(cfg, calls, mode):
    c = dataclasses.replace(cfg, search_mode=mode, connectivity_choices=(0.5, 1.0),
                            vertical_connectivity_choices=(0.1, 0.5, 1.0))
    st = run(c, n=8)
    for t in st.trials:
        v, p = t.params["vertical_connectivity"], t.params["connectivity"]
        assert v in (0.1, 0.5, 1.0)
        assert t.user_attrs["link_fraction"] == pytest.approx(p * v)
        mine = [x for x in calls if x["name"].startswith(f"tt{t.number}d")]
        assert len(mine) == 2 and all(x["vconn"] == v and x["conn"] == p for x in mine)
    assert len({t.params["vertical_connectivity"] for t in st.trials}) > 1
    # the reference stays at full connectivity
    assert all(x["vconn"] == 1 and x["conn"] == 1.0 for x in calls if x["name"].endswith("ref"))


def test_fixed_vertical_connectivity(cfg, calls):
    st = run(dataclasses.replace(cfg, vertical_connectivity_choices=(0.25,)), n=3)
    for t in st.trials:
        assert "vertical_connectivity" not in t.params
        assert t.user_attrs["link_fraction"] == pytest.approx(0.25 * t.params["connectivity"])
    assert all(x["vconn"] == 0.25 for x in calls if not x["name"].endswith("ref"))


@pytest.mark.parametrize("bad", [(), (0.0,), (0.5, 1.5), (0.5, 0.5), (float("nan"),)])
def test_bad_vertical_connectivity_refused(cfg, bad):
    with pytest.raises(ValueError, match="vertical_connectivity_choices"):
        lo.check_priorities(dataclasses.replace(cfg, vertical_connectivity_choices=bad))


def test_vertical_connectivity_refused_where_it_does_nothing(cfg):
    c = dataclasses.replace(cfg, vertical_connectivity_choices=(0.1, 1.0))
    with pytest.raises(ValueError, match="connectivity mode"):
        lo.make_suite_objective(dataclasses.replace(c, search_mode="connectivity"), designs=[])
    single = lo.SearchConfig(lazagna_root="/r", benchmark_dir="/r/b/x", vertical_connectivity_choices=(0.1, 1.0))
    with pytest.raises(ValueError, match="multi-benchmark"):
        lo.make_objective(single)


# ---- B. links as an objective ---------------------------------------------------------------

def test_links_objective_values(cfg):
    c = dataclasses.replace(cfg, links_objective=True)
    assert lo.n_objectives(c) == 3
    assert lo.objective_values(c, 3.0, -1.0, 0.25) == (-3.0, 1.0, 0.25)
    lo.check_priorities(dataclasses.replace(c, link_penalty=0.0))     # a zero penalty is fine


@pytest.mark.parametrize("bad", [dict(objective_weights=(0.7, 0.3)), dict(link_penalty=2.0)])
def test_links_objective_refused_with_priorities(cfg, bad):
    with pytest.raises(ValueError, match="links_objective"):
        lo.check_priorities(dataclasses.replace(cfg, links_objective=True, **bad))


@pytest.mark.filterwarnings("ignore::optuna.exceptions.ExperimentalWarning")
@pytest.mark.parametrize("sampler", lo.SAMPLERS)
def test_links_objective_with_every_sampler(cfg, calls, sampler):
    if sampler == "qmc":
        pytest.importorskip("scipy")
    c = dataclasses.replace(cfg, sampler=sampler, links_objective=True, nsga_population=4,
                            connectivity_choices=(0.25, 0.5, 1.0), vertical_connectivity_choices=(0.05, 0.1, 1.0))
    st = run(c, n=10, sampler=lo._make_sampler(c))
    assert len(st.directions) == 3
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
    assert len(done) == 10
    for t in done:
        u = t.user_attrs
        assert t.values == pytest.approx([-u["cpd_impr_pct"], -u["wl_impr_pct"], u["link_fraction"]])
    assert st.best_trials


def test_links_objective_single_design(monkeypatch):
    monkeypatch.setattr(lo, "_run_one", lambda c, s, name, *a, **k:
                        ((10.0, 100.0), None) if name.endswith("ref") else ((9.0, 95.0), None))
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="/r/b/x", search_mode="connectivity",
                        fine_connectivity_choices=(0.5,), run_tag="t", links_objective=True)
    st = optuna.create_study(directions=["minimize"] * 3)
    st.optimize(lo.make_objective(c), n_trials=1)
    assert st.trials[0].values == pytest.approx([-10.0, -5.0, 0.5])


def test_run_study_three_objectives(cfg, calls):
    st = lo.run_study(dataclasses.replace(cfg, sampler="random", links_objective=True,
                                          connectivity_choices=(0.5, 1.0)), n_trials=3, study_name="l")
    assert len(st.directions) == 3 and all(len(t.values) == 3 for t in st.trials)


# ---- D. anchors -----------------------------------------------------------------------------

RECOMMENDED = dict(connectivity_choices=(0.25, 0.5, 1.0), vertical_connectivity_choices=(0.05, 0.1, 0.25, 0.5, 1.0))
NAMES = ["even_split", "split_types", "split_rev", "hb_top", "hb_one_layer"]


def test_anchor_trials_fit_the_search_space(cfg):
    got = lo.anchor_trials(dataclasses.replace(cfg, **RECOMMENDED))
    assert [n for n, _ in got] == NAMES + ["recommended"]
    p = dict(got)
    assert (p["split_types"]["dsp_frac_l0"], p["split_types"]["bram_frac_l0"]) == (1.0, 0.0)
    assert (p["split_rev"]["dsp_frac_l0"], p["split_rev"]["bram_frac_l0"]) == (0.0, 1.0)
    assert (p["hb_top"]["dsp_frac_l0"], p["hb_one_layer"]["dsp_frac_l0"]) == (0.0, 1.0)
    assert p["recommended"]["vertical_connectivity"] == 0.1
    assert {k: v for k, v in p["recommended"].items() if k != "vertical_connectivity"} == \
        {k: v for k, v in p["split_types"].items() if k != "vertical_connectivity"}
    for _, q in got:
        assert q["connectivity"] == 1.0 and q["delay_ratio"] == 0.739 and q["cluster"] == 0.0
        assert q["band_pos"] == 0.5 and all(lo_ <= q[k] <= hi for k, lo_, hi in lo.STRUCTURED_FRACTIONS)
    # vertical connectivity fixed at 1.0 (default): no parameter, no "recommended"
    assert [(n, "vertical_connectivity" in q) for n, q in lo.anchor_trials(cfg)] == [(n, False) for n in NAMES]
    # 0.1 not among the choices -> no "recommended"
    c = dataclasses.replace(cfg, vertical_connectivity_choices=(0.5, 1.0))
    assert [n for n, _ in lo.anchor_trials(c)] == NAMES
    # vertical connectivity fixed at 0.1: only "recommended" fits
    assert [n for n, _ in lo.anchor_trials(dataclasses.replace(cfg, vertical_connectivity_choices=(0.1,)))] == \
        ["recommended"]
    # connectivity 1.0 not a choice, or 0.739 outside the delay range: nothing fits
    assert lo.anchor_trials(dataclasses.replace(cfg, connectivity_choices=(0.5,))) == []
    assert lo.anchor_trials(dataclasses.replace(cfg, delay_ratio_range=(0.8, 1.2))) == []


def test_anchors_only_for_the_structured_suite_search(cfg):
    for c in (dataclasses.replace(cfg, search_mode="layout"), dataclasses.replace(cfg, benchmarks=())):
        with pytest.raises(ValueError, match="structured multi-benchmark"):
            lo.anchor_trials(c)
    with pytest.raises(ValueError, match="multi-benchmark"):
        lo.make_objective(lo.SearchConfig(lazagna_root="/r", benchmark_dir="/r/b/x", anchors=True))


def _device(design):
    r = json.load(open(os.path.join(STUDY_RESULTS, f"rq1__{design}.json")))
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="", width=r["sizing"]["width"], height=r["sizing"]["height"])
    assert list(lo.column_counts(c)) == r["cols_per_layer"]
    return c


@pytest.mark.skipif(not os.path.isdir(STUDY_RESULTS), reason="needs docs/study/results")
def test_split_anchors_are_the_study_layouts():
    """split_types and recommended give the columns the study ran (split_types and its rec runs),
    on every study device; the other anchors keep the study layouts' per-layer column counts."""
    p = {n: {k: q[k] for k, _, _ in lo.STRUCTURED_FRACTIONS} for n, q in
         lo.anchor_trials(lo.SearchConfig(lazagna_root="/r", benchmark_dir="", benchmarks=("x/y",),
                                          search_mode="structured", **RECOMMENDED))}
    runs = sorted(glob.glob(os.path.join(STUDY_RESULTS, "layout__*__split_types.json")))
    recs = sorted(glob.glob(os.path.join(STUDY_RESULTS, "rec__*.json")))
    assert len(runs) == 22 and len(recs) == 22
    for f in runs + recs:
        r = json.load(open(f))
        design = r["task"]["design"].split("/", 1)[1]
        assert r["task"]["layout"] == "split_types"
        name = "recommended" if r["task"].get("tag") == "rec" else "split_types"
        if name == "recommended":
            assert (r["task"]["conn"], r["task"]["vconn"]) == (1.0, 0.1)
        assert lo.structured_from_fractions(_device(design), p[name]).columns == r["3d"]["columns"], f
    # the others: same per-layer counts as the study's runs, but not the same columns
    for name, layout in (("split_rev", "split_rev"), ("hb_top", "hb_top"), ("hb_one_layer", "hb_one_layer"),
                         ("even_split", "aligned")):
        for f in glob.glob(os.path.join(STUDY_RESULTS, f"s10__layout__*__{layout}.json")):
            r = json.load(open(f))
            got = lo.structured_from_fractions(_device(r["task"]["design"].split("/", 1)[1]), p[name]).columns
            want = r["3d"]["columns"]
            assert got != want
            assert [sorted(layer) for layer in got] == [sorted(layer) for layer in want]


@pytest.mark.skipif(not os.path.isdir(STUDY_RESULTS), reason="needs docs/study/results")
def test_even_split_is_not_the_reference():
    for f in glob.glob(os.path.join(STUDY_RESULTS, "rq1__*.json")):
        c = _device(os.path.basename(f)[len("rq1__"):-len(".json")])
        even = lo.structured_from_fractions(c, {"dsp_frac_l0": 0.5, "bram_frac_l0": 0.5, "cluster": 0.0,
                                                "stagger": 0.0, "band_pos": 0.5})
        assert even.columns != lo.reference_columns(c).columns
        assert even.columns[0] == even.columns[1]                      # but aligned, like the reference
        assert sorted(even.columns[0]) == sorted(lo.reference_columns(c).columns[0])


def test_enqueue_anchors_once_and_first(cfg, calls):
    c = dataclasses.replace(cfg, anchors=True, **RECOMMENDED)
    st = optuna.create_study(directions=["minimize"] * 2, sampler=optuna.samplers.RandomSampler(seed=0))
    assert lo.enqueue_anchors(st, c) == NAMES + ["recommended"]
    assert lo.enqueue_anchors(st, c) == []                               # already queued: nothing
    st.optimize(lo.make_suite_objective(c, designs=lo.design_configs(c)), n_trials=8)
    seeded = [t.user_attrs.get("seeded_from") for t in st.trials]
    assert seeded[:6] == NAMES + ["recommended"] and seeded[6:] == [None, None]
    rec = st.trials[5]
    assert rec.params["vertical_connectivity"] == 0.1 and rec.user_attrs["link_fraction"] == pytest.approx(0.1)
    assert lo.enqueue_anchors(st, c) == []                               # nor after they ran


def test_run_study_queues_the_anchors(cfg, calls):
    st = lo.run_study(dataclasses.replace(cfg, sampler="random", anchors=True), n_trials=6, study_name="a")
    assert [t.user_attrs.get("seeded_from") for t in st.trials] == NAMES + [None]


# ---- E. placement estimates of routed runs ----------------------------------------------------

def test_place_estimates_kept_for_routed_runs(cfg, calls, tmp_path):
    c = dataclasses.replace(cfg, fidelity="route")
    bdir = str(tmp_path / "baselines")
    st = run(c, n=3, baseline_dir=bdir)
    files = sorted(glob.glob(os.path.join(bdir, "*.json")))
    assert len(files) == 2
    refs = [json.load(open(f)) for f in files]
    assert all(set(r) == {"cpd", "wl", "place_cpd", "place_wl"} for r in refs)
    for t in st.trials:
        u, ratios = t.user_attrs, {"cpd": [], "wl": []}
        for e, r in u["per_design"].items():
            for k in ("cpd", "wl"):
                assert r[f"place_{k}_impr_pct"] == pytest.approx(
                    100 * (r[f"baseline_place_{k}"] - r[f"place_{k}"]) / r[f"baseline_place_{k}"])
                ratios[k].append(r[f"place_{k}"] / r[f"baseline_place_{k}"])
        for k in ("cpd", "wl"):
            assert u[f"place_{k}_impr_pct"] == pytest.approx(100 * (1 - math.sqrt(ratios[k][0] * ratios[k][1])))
        # the objective is still the routed gain
        assert t.values == pytest.approx([-u["cpd_impr_pct"], -u["wl_impr_pct"]])
    # a second worker loads the references, place estimates included
    st2 = run(c, n=1, baseline_dir=bdir)
    assert "place_cpd_impr_pct" in st2.trials[0].user_attrs
    assert sum(1 for x in calls if x["name"].endswith("ref")) == 2


def test_no_place_estimates_for_placement_runs(cfg, calls, tmp_path):
    st = run(cfg, n=2, baseline_dir=str(tmp_path / "b"))                # fidelity "place"
    assert all("place_cpd_impr_pct" not in t.user_attrs for t in st.trials)
    assert all("place_cpd" not in r for t in st.trials for r in t.user_attrs["per_design"].values())
    assert all("info" not in x["kw"] for x in calls)
    assert all(set(json.load(open(f))) == {"cpd", "wl"} for f in glob.glob(str(tmp_path / "b" / "*.json")))


def test_old_reference_files_still_load(cfg, calls, tmp_path):
    """Reference files written before the place keys existed: loaded as they are (no re-run), and
    the trials simply have no placement gains for those designs."""
    c = dataclasses.replace(cfg, fidelity="route")
    bdir = tmp_path / "baselines"
    bdir.mkdir()
    for e, sub in lo.design_configs(c):
        cpd, wl = (10.0, 1000.0) if e == "vtr/sha" else (5.0, 400.0)
        (bdir / f"{lo.baseline_signature(sub)}.json").write_text(json.dumps({"cpd": cpd, "wl": wl}))
        assert lo._read_baseline(str(bdir / f"{lo.baseline_signature(sub)}.json")) == (cpd, wl)
        assert lo._read_baseline_place(str(bdir / f"{lo.baseline_signature(sub)}.json")) is None
    st = run(c, n=2, baseline_dir=str(bdir))
    assert not [x for x in calls if x["name"].endswith("ref")]
    assert all(t.state == optuna.trial.TrialState.COMPLETE and "place_cpd_impr_pct" not in t.user_attrs
               for t in st.trials)


def test_place_estimates_need_every_seed():
    full = {"per_seed": [{"place_cpd": 2e-9, "place_wl": 10.0}, {"place_cpd": 8e-9, "place_wl": 40.0}]}
    assert lo._place_estimates(full) == pytest.approx((4e-9, 20.0))
    assert lo._place_estimates({"per_seed": [{"place_cpd": 2e-9, "place_wl": 10.0}, {"place_cpd": None}]}) is None
    assert lo._place_estimates({}) is None and lo._place_estimates(None) is None


def test_baseline_file_bytes_unchanged(tmp_path):
    p = str(tmp_path / "b.json")
    lo._write_baseline(p, 1.25e-08, 12345.0)
    assert open(p).read() == '{"cpd": 1.25e-08, "wl": 12345.0}'
    lo._write_baseline(p, 1.25e-08, 12345.0, {"place_cpd": 1e-08, "place_wl": 9000.0})
    assert lo._read_baseline(p) == (1.25e-08, 12345.0) and lo._read_baseline_place(p) == (1e-08, 9000.0)


# ---- F. NSGA population ----------------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::optuna.exceptions.ExperimentalWarning")
def test_nsga_population(cfg):
    mk = lambda **k: lo._make_sampler(dataclasses.replace(cfg, **k))
    assert mk(sampler="nsga2", nsga_population=12)._population_size == 12
    assert mk(sampler="nsga3", nsga_population=6)._population_size == 6
    assert mk(sampler="nsga2")._population_size == 50                    # Optuna's default
    for bad in (1, 0, 2.5, True, "8"):
        with pytest.raises(ValueError, match="nsga_population"):
            mk(sampler="nsga2", nsga_population=bad)


# ---- H. the designs of the recommended run -----------------------------------------------------

def test_recommended_designs_resolve(fake_root, tmp_path):
    for rel in TRIO_FILES:
        p = os.path.join(fake_root, "benchmarks", rel)
        open(p, "w").write(f"// {rel}\n")
    from benchmark_suites import expand
    assert expand(TRIO, fake_root) == list(TRIO)
    c = lo.SearchConfig(lazagna_root=fake_root, benchmark_dir="", benchmarks=TRIO, search_mode="structured",
                        autosize_designs=False, stage_dir=str(tmp_path / "stage"))
    ds = lo.design_configs(c)                              # no duplicate-name error
    assert [(e, os.path.basename(s.benchmark_dir), s.is_verilog) for e, s in ds] == [
        ("koios/tpu_like.small.ws", "suite_tpu_like.small.ws", True),
        ("vtr/mkDelayWorker32B", "suite_mkDelayWorker32B", True),
        ("vtr/stereovision2", "suite_stereovision2", True)]


# ---- the defaults leave the search exactly as it was ------------------------------------------

def _golden_fake(cfg, spec, name, arch_type, conn, delay, connection_type="subset", **kw):
    cols = spec.columns if hasattr(spec, "columns") else repr(spec)
    h = int(hashlib.sha1(repr((os.path.basename(cfg.benchmark_dir), cols, arch_type, conn, delay,
                               name.endswith("ref"))).encode()).hexdigest(), 16)
    f = 1 + ((h % 1000) / 1000 - 0.5) * 0.2
    return ((1e-8, 1e4) if name.endswith("ref") else (1e-8 * f, 1e4 / f)), None


# sha1[:16] of every trial's params, values and user attrs, computed with the code of
# origin/main (361e9b0) before these options existed; identical on optuna 4.9 and 5.0.
GOLDEN = {"structured": "804125b0c346a7df", "layout": "c9c357d828ff52dd", "connectivity": "ce5b5f613e9d3de0"}


@pytest.mark.parametrize("mode", sorted(GOLDEN))
def test_default_suite_search_matches_main(monkeypatch, mode):
    monkeypatch.setattr(lo, "_run_one", _golden_fake)
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="", benchmarks=("vtr/a", "vtr/b"), search_mode=mode,
                        autosize_designs=False, run_tag="g", connectivity_choices=(0.5, 1.0))
    designs = [(f"vtr/{d}", dataclasses.replace(c, benchmark_dir=f"/s/bench/suite_{d}", benchmarks=(),
                                                 run_tag=f"gd{i}", width=w, height=w))
               for i, (d, w) in enumerate((("a", 22), ("b", 30)))]
    st = optuna.create_study(directions=["minimize"] * 2, sampler=optuna.samplers.RandomSampler(seed=7))
    st.optimize(lo.make_suite_objective(c, designs=designs), n_trials=6)
    canon = json.dumps([[t.number, t.params, t.values, t.user_attrs] for t in st.trials], sort_keys=True)
    assert hashlib.sha1(canon.encode()).hexdigest()[:16] == GOLDEN[mode]
