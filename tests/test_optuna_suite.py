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
