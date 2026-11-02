"""Multi-benchmark search (SearchConfig.benchmarks) with the flow mocked out."""
import math
import os

import pytest

optuna = pytest.importorskip("optuna")
import lazagna_optuna as lo

optuna.logging.set_verbosity(optuna.logging.WARNING)
BASE = {"suite_sha": (10.0, 1000.0), "suite_clma": (5.0, 400.0)}


@pytest.fixture
def cfg(fake_root, tmp_path):
    return lo.SearchConfig(lazagna_root=fake_root, benchmark_dir="", benchmarks=("vtr/sha", "mcnc/clma"),
                           search_mode="structured", autosize_designs=False, width=20, height=20,
                           stage_dir=str(tmp_path / "stage"), run_tag="t")


@pytest.fixture
def calls(monkeypatch):
    log = []

    def fake_run_one(cfg, spec, exp_name, arch_type, connectivity, delay_ratio, connection_type="subset", **kw):
        d = os.path.basename(cfg.benchmark_dir)
        log.append((d, exp_name))
        base = BASE[d]
        if exp_name.endswith("ref"):
            return base, None
        f = 1 - (0.1 if d == "suite_sha" else -0.05) * delay_ratio
        return (base[0] * f, base[1] * f), None
    monkeypatch.setattr(lo, "_run_one", fake_run_one)
    return log


def test_design_configs(cfg):
    ds = lo.design_configs(cfg)
    assert [(e, os.path.basename(s.benchmark_dir), s.is_verilog, s.run_tag) for e, s in ds] == [
        ("vtr/sha", "suite_sha", True, "td0"), ("mcnc/clma", "suite_clma", False, "td1")]
    assert all(s.benchmarks == () for _, s in ds)


def test_objective_is_geomean_of_ratios(cfg, calls):
    st = optuna.create_study(directions=["minimize", "minimize"], sampler=optuna.samplers.RandomSampler(seed=1))
    st.optimize(lo.make_suite_objective(cfg, designs=lo.design_configs(cfg)), n_trials=4)
    for t in st.trials:
        dr = t.params["delay_ratio"]
        want = 100 * (1 - math.sqrt((1 - 0.1 * dr) * (1 + 0.05 * dr)))
        assert t.user_attrs["cpd_impr_pct"] == pytest.approx(want)
        assert t.values[0] == pytest.approx(-want)
        assert set(t.user_attrs["per_design"]) == {"vtr/sha", "mcnc/clma"}
        assert {"dsp_frac_l0", "bram_frac_l0", "cluster", "stagger", "band_pos"} <= set(t.params)
    # each design's reference is run once, then reused
    assert sum(1 for _, n in calls if n.endswith("ref")) == 2
    assert len({n for _, n in calls}) == len(calls)          # run names never repeat


def test_reference_shared_through_files(cfg, calls, tmp_path):
    ds = lo.design_configs(cfg)
    bdir = str(tmp_path / "baselines")
    for _ in range(2):   # two "workers"
        obj = lo.make_suite_objective(cfg, designs=ds, baseline_dir=bdir)
        optuna.create_study(directions=["minimize", "minimize"]).optimize(obj, n_trials=1)
    assert sum(1 for _, n in calls if n.endswith("ref")) == 2
    assert len([f for f in os.listdir(bdir) if f.endswith(".json")]) == 2


def test_failed_design_prunes_the_trial(cfg, monkeypatch):
    monkeypatch.setattr(lo, "_run_one", lambda c, s, name, *a, **k:
                        ((1.0, 1.0), None) if name.endswith("ref") else (None, "boom"))
    st = optuna.create_study(directions=["minimize", "minimize"])
    st.optimize(lo.make_suite_objective(cfg, designs=lo.design_configs(cfg)), n_trials=1)
    t = st.trials[0]
    assert t.state == optuna.trial.TrialState.PRUNED and t.user_attrs["failed_design"] == "vtr/sha"


def test_columns_mode_refused(cfg):
    import dataclasses
    with pytest.raises(ValueError, match="search_mode"):
        lo.design_configs(dataclasses.replace(cfg, search_mode="columns"))


def test_structured_fractions_cover_the_range():
    c = lo.SearchConfig(lazagna_root="/x", benchmark_dir="", width=26, height=26)
    _, nd, nb = lo.column_counts(c)
    lo_spec = lo.structured_from_fractions(c, {"dsp_frac_l0": 0, "bram_frac_l0": 0, "cluster": 0, "stagger": 0, "band_pos": .5})
    hi_spec = lo.structured_from_fractions(c, {"dsp_frac_l0": 1, "bram_frac_l0": 1, "cluster": 0, "stagger": 0, "band_pos": .5})
    count = lambda spec, layer, t: spec.columns[layer].count(t)
    assert count(lo_spec, 0, lo.DSP) == 0 and count(lo_spec, 1, lo.DSP) == 2 * nd
    assert count(hi_spec, 0, lo.DSP) == 2 * nd and count(hi_spec, 0, lo.BRAM) == 2 * nb


def test_single_design_path_untouched():
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="/r/bench/x", is_verilog=True, seeds=3)
    assert lo.baseline_signature(c) == "981dccf36fad"   # value from before the change


def test_same_design_name_from_two_suites_is_refused(fake_root, tmp_path):
    """Staging dirs, the synthesis cache and the reference files are keyed by design name, so
    koios/eltwise_layer + itd_quick/eltwise_layer would silently run one file twice."""
    c = lo.SearchConfig(lazagna_root=fake_root, benchmark_dir="", search_mode="structured",
                        benchmarks=("koios/eltwise_layer", "itd_quick"), autosize_designs=False,
                        stage_dir=str(tmp_path / "stage"))
    with pytest.raises(ValueError, match="koios/eltwise_layer and itd_quick/eltwise_layer"):
        lo.design_configs(c)


def test_connectivity_mode_uses_the_reference_columns(cfg, calls, monkeypatch):
    """In connectivity mode a trial differs from its design's reference only in connectivity,
    type and delay: at full connectivity it is the reference."""
    import dataclasses
    seen = []
    orig = lo._run_one

    def spy(c, spec, name, *a, **k):
        seen.append((name, spec, lo.reference_columns(c)))
        return orig(c, spec, name, *a, **k)
    monkeypatch.setattr(lo, "_run_one", spy)
    c = dataclasses.replace(cfg, search_mode="connectivity")
    st = optuna.create_study(directions=["minimize", "minimize"])
    st.optimize(lo.make_suite_objective(c, designs=lo.design_configs(c)), n_trials=2)
    trials = [(spec, ref) for name, spec, ref in seen if not name.endswith("ref")]
    assert trials and all(spec == ref for spec, ref in trials)
    assert {"type_sb", "connectivity", "delay_ratio"} <= set(st.trials[0].params)


@pytest.mark.filterwarnings("ignore::optuna.exceptions.ExperimentalWarning")
@pytest.mark.parametrize("sampler", lo.SAMPLERS)
def test_every_sampler_runs_the_multi_benchmark_search(cfg, calls, sampler):
    import dataclasses
    if sampler == "qmc":
        pytest.importorskip("scipy")
    c = dataclasses.replace(cfg, sampler=sampler)
    st = optuna.create_study(directions=["minimize", "minimize"], sampler=lo._make_sampler(c))
    st.optimize(lo.make_suite_objective(c, designs=lo.design_configs(c)), n_trials=6)
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
    assert len(done) == 6 and all(set(t.user_attrs["per_design"]) == {"vtr/sha", "mcnc/clma"} for t in done)


def test_run_study_with_suite_and_weights(cfg, calls):
    """run_study: a weighted search is a one-objective study whose value is the weighted gain."""
    import dataclasses
    st = lo.run_study(dataclasses.replace(cfg, sampler="random", objective_weights=(1.0, 0.0)),
                      n_trials=3, study_name="w")
    assert len(st.directions) == 1 and len(st.trials) == 3
    for t in st.trials:
        assert t.value == pytest.approx(-t.user_attrs["cpd_impr_pct"])


def test_unknown_sampler_is_an_error(cfg):
    import dataclasses
    with pytest.raises(ValueError, match="unknown sampler 'cmaes'"):
        lo._make_sampler(dataclasses.replace(cfg, sampler="cmaes"))


def test_existing_sampler_names_unchanged(cfg):
    import dataclasses
    mk = lambda s, par=False: lo._make_sampler(dataclasses.replace(cfg, sampler=s, parallel=par))
    assert isinstance(mk("tpe"), optuna.samplers.TPESampler)
    assert isinstance(mk("nsga2"), optuna.samplers.NSGAIISampler)
    assert isinstance(mk("random"), optuna.samplers.RandomSampler)


def test_qmc_without_scipy_says_so(cfg, monkeypatch):
    import dataclasses
    import sys
    monkeypatch.setitem(sys.modules, "scipy.stats", None)
    with pytest.raises(ImportError, match="needs scipy"):
        lo._make_sampler(dataclasses.replace(cfg, sampler="qmc"))


# ---- priorities (objective_weights, link_penalty) -------------------------------------------

def test_objective_values_defaults_are_the_plain_gains():
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="")
    assert lo.objective_values(c, 3.5, -1.25, 1.0) == (-3.5, 1.25)
    assert lo.n_objectives(c) == 2


def test_objective_values_weights_and_link_penalty():
    import dataclasses
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="")
    w = dataclasses.replace(c, objective_weights=(0.7, 0.3))
    assert lo.n_objectives(w) == 1
    assert lo.objective_values(w, 10.0, 20.0) == pytest.approx(-(7.0 + 6.0))
    p = dataclasses.replace(c, link_penalty=2.0)
    assert lo.objective_values(p, 10.0, 20.0, links=0.5) == pytest.approx((-9.0, -19.0))
    wp = dataclasses.replace(w, link_penalty=2.0)
    assert lo.objective_values(wp, 10.0, 20.0, links=1.0) == pytest.approx(-(0.7 * 8 + 0.3 * 18))
    assert lo.link_fraction("2d", 1.0) == 0.0 and lo.link_fraction("3d_sb", 0.25) == 0.25


@pytest.mark.parametrize("bad", [dict(objective_weights=(1.0,)), dict(objective_weights=(0, 0)),
                                 dict(objective_weights=(1, float("nan"))), dict(link_penalty=float("inf"))])
def test_bad_priorities_are_refused(bad):
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="", **bad)
    with pytest.raises(ValueError):
        lo.check_priorities(c)


def test_suite_objective_with_link_penalty(cfg, calls):
    import dataclasses
    c = dataclasses.replace(cfg, connectivity_choices=(0.5,), link_penalty=4.0)
    st = optuna.create_study(directions=["minimize", "minimize"], sampler=optuna.samplers.RandomSampler(seed=0))
    st.optimize(lo.make_suite_objective(c, designs=lo.design_configs(c)), n_trials=3)
    for t in st.trials:
        assert t.user_attrs["link_fraction"] == 0.5
        assert t.values[0] == pytest.approx(-(t.user_attrs["cpd_impr_pct"] - 2.0))
        assert t.values[1] == pytest.approx(-(t.user_attrs["wl_impr_pct"] - 2.0))


def test_single_design_objective_unchanged_by_default(monkeypatch, tmp_path):
    """Defaults: the single-design objective returns (-CPD gain, -WL gain) and records no new
    attributes; with a link penalty it is charged and link_fraction recorded."""
    import dataclasses
    monkeypatch.setattr(lo, "_run_one", lambda c, s, name, *a, **k:
                        ((10.0, 100.0), None) if name.endswith("ref") else ((9.0, 95.0), None))
    c = lo.SearchConfig(lazagna_root="/r", benchmark_dir="/r/b/x", search_mode="connectivity",
                        fine_connectivity_choices=(0.5,), run_tag="t")
    st = optuna.create_study(directions=["minimize", "minimize"])
    st.optimize(lo.make_objective(c), n_trials=1)
    t = st.trials[0]
    assert t.values == pytest.approx([-10.0, -5.0]) and "link_fraction" not in t.user_attrs
    st2 = optuna.create_study(directions=["minimize", "minimize"])
    st2.optimize(lo.make_objective(dataclasses.replace(c, link_penalty=2.0)), n_trials=1)
    t2 = st2.trials[0]
    assert t2.user_attrs["link_fraction"] == 0.5 and t2.values == pytest.approx([-9.0, -4.0])


# ---- the shared reference file ---------------------------------------------------------------

def test_shared_value_computes_once_and_reuses(tmp_path):
    path = str(tmp_path / "b" / "ref.json")
    n = []
    compute = lambda: n.append(1) or (2.0, 30.0)
    assert lo._shared_value(path, compute) == (2.0, 30.0)
    assert lo._shared_value(path, compute) == (2.0, 30.0)
    assert len(n) == 1


def test_shared_value_waits_for_the_owner(tmp_path, monkeypatch):
    import time
    path = str(tmp_path / "ref.json")
    open(path + ".lock", "w").close()                   # another worker is computing
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            lo._write_baseline(path, 1.5, 40.0)        # ... and publishes its result
    monkeypatch.setattr(time, "sleep", fake_sleep)
    assert lo._shared_value(path, lambda: pytest.fail("must not compute"), poll_s=7) == (1.5, 40.0)
    assert sleeps == [7, 7]


def test_shared_value_failure_releases_the_lock(tmp_path, monkeypatch):
    import time
    path = str(tmp_path / "ref.json")
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("must not wait"))

    def boom():
        raise RuntimeError("reference run failed")
    with pytest.raises(RuntimeError):
        lo._shared_value(path, boom)
    assert not os.path.exists(path + ".lock")
    assert lo._shared_value(path, lambda: (3.0, 9.0)) == (3.0, 9.0)   # next caller retries at once


def test_shared_value_owner_died(tmp_path, monkeypatch):
    import time
    path = str(tmp_path / "ref.json")
    open(path + ".lock", "w").close()                   # stale lock, no result ever appears
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert lo._shared_value(path, lambda: (4.0, 5.0), polls=3) == (4.0, 5.0)
    assert lo._read_baseline(path) == (4.0, 5.0)
