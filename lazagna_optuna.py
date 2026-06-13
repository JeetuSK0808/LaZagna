from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import glob
import math
import os

import optuna

from lazagna_arch_model import (
    ExperimentOptions, GridOptions, BenchmarkOptions, PlacementOptions,
    SeedOptions, SwitchBlock3DOptions, InterlayerDelayOptions, run_lazagna,
)
from layout_space import LayoutSpec, ColumnLayoutSpec, NAMED_LAYOUTS, CLB, DSP, BRAM, IO
from arch_from_template import render_arch_from_template

def build_architecture(spec: LayoutSpec, width: int, height: int, template_path: str) -> str:

    return render_arch_from_template(template_path, spec, width, height)


import re as _re

_CPD_RE = _re.compile(r"Final critical path delay \(least slack\):\s*([\d.eE+-]+)\s*ns")
_WL_RE = _re.compile(r"Total wirelength:\s*([\d]+)")

def parse_results(results_dir: str, only_containing: Optional[str] = None) -> Optional[tuple[float, float]]:
    """Read real CPD (seconds) and WL from VPR's own logs under tasks_run/.

    LaZagna runs each benchmark into tasks_run/<run-folder>/.../Common/vpr_stdout.log
    and that log holds the true 'Final critical path delay' and 'Total wirelength'.
    The results/ summary CSV is unreliable (often zero-filled), so we go to source.

    `only_containing` filters run folders by experiment name so we score exactly the
    run we just launched. lazagna_root is inferred from results_dir's parent.
    """
    lazagna_root = os.path.dirname(results_dir.rstrip("/"))
    tasks_run = os.path.join(lazagna_root, "tasks_run")
    logs = glob.glob(os.path.join(tasks_run, "**", "vpr_stdout.log"), recursive=True)
    if only_containing:

        def _exp_matches(logpath: str) -> bool:
            folder = os.path.basename(logpath.split("/task_")[0])
            if "_vp_" not in folder:
                return False
            before = folder.split("_vp_")[0]
            return only_containing in before.split("_")
        matched = [l for l in logs if _exp_matches(l)]
        if not matched:
            return None
        logs = matched
    if not logs:
        return None

    cpds: list[float] = []
    wls: list[float] = []
    seen_folders = set()
    for path in logs:
        folder = path.split("/task_")[0]
        if folder in seen_folders:
            continue
        seen_folders.add(folder)
        try:
            text = open(path, errors="ignore").read()
        except OSError:
            continue
        if "VPR succeeded" not in text:
            continue
        m_cpd = _CPD_RE.search(text)
        m_wl = _WL_RE.search(text)
        if m_cpd:
            cpds.append(float(m_cpd.group(1)) * 1e-9)
        if m_wl:
            wls.append(float(m_wl.group(1)))
    if not cpds or not wls:
        return None
    return _geomean(cpds), _geomean(wls)

def _geomean(xs: list[float]) -> float:
    xs = [x for x in xs if x > 0]
    if not xs:
        return float("inf")
    return math.exp(sum(math.log(x) for x in xs) / len(xs))

@dataclass
class SearchConfig:
    """Everything the study needs that isn't a tuned hyperparameter."""
    lazagna_root: str
    benchmark_dir: str
    is_verilog: bool = False
    width: int = 12
    height: int = 12
    width_2d: int = 17
    height_2d: int = 17
    channel_width: int = 100
    seeds: int = 1
    arch_type: str = "3d_sb"
    search_mode: str = "layout"
    sampler: str = "tpe"
    parallel: bool = False

    run_tag: str = field(default_factory=lambda: "run" + str(int(__import__("time").time())))

    template_path: str = "arch_files/vtr_3d_cb_arch_dsp_bram_10x10_delay_ratio_0.739.xml"

    hb_period_choices: tuple[int, ...] = (4, 6, 8, 12)
    edge_fraction_range: tuple[float, float] = (0.1, 0.35)
    delay_ratio_range: tuple[float, float] = (0.4, 1.2)
    connectivity_choices: tuple[float, ...] = (0.33, 0.66, 1.0)
    column_block_choices: tuple[str, ...] = (CLB, DSP, BRAM)
    type_sb_choices: tuple[str, ...] = ("3d_sb",)
    connection_type_choices: tuple[str, ...] = ("subset",)
    fine_connectivity_choices: tuple[float, ...] = (0.1, 0.2, 0.33, 0.5, 0.66, 0.8, 1.0)

def sample_layout(trial: optuna.Trial, cfg: SearchConfig) -> LayoutSpec:
    family = trial.suggest_categorical("family", ["distributed", "edge"])
    asymmetry = trial.suggest_float("asymmetry", 0.0, 1.0)
    separate = trial.suggest_categorical("separate_dsp_bram", [False, True])
    if family == "distributed":
        period = trial.suggest_categorical("hb_period", list(cfg.hb_period_choices))
        return LayoutSpec(family=family, hb_period=period, asymmetry=asymmetry, separate_dsp_bram=separate)
    frac = trial.suggest_float("edge_fraction", *cfg.edge_fraction_range)
    return LayoutSpec(family=family, edge_fraction=frac, asymmetry=asymmetry, separate_dsp_bram=separate)


def sample_columns(trial: optuna.Trial, cfg: SearchConfig) -> ColumnLayoutSpec:
    n_interior = cfg.width - 2
    cols = []
    for layer in range(2):
        layer_cols = [
            trial.suggest_categorical(f"L{layer}c{i}", list(cfg.column_block_choices))
            for i in range(n_interior)
        ]
        cols.append(layer_cols)
    return ColumnLayoutSpec(columns=cols)


def sample_connectivity(trial: optuna.Trial, cfg: SearchConfig):
    type_sb = trial.suggest_categorical("type_sb", list(cfg.type_sb_choices))
    if type_sb in ("2d", "3d_cb", "3d_cb_out_only"):
        connectivity = 1.0
        connection_type = "subset"
    else:
        connectivity = trial.suggest_categorical("connectivity", list(cfg.fine_connectivity_choices))
        connection_type = trial.suggest_categorical("connection_type", list(cfg.connection_type_choices)) \
            if len(cfg.connection_type_choices) > 1 else cfg.connection_type_choices[0]
    delay_ratio = trial.suggest_float("delay_ratio", *cfg.delay_ratio_range)
    return type_sb, connectivity, connection_type, delay_ratio

def _run_one(cfg: SearchConfig, spec_or_none, exp_name: str, arch_type: str,
             connectivity: float, delay_ratio: float, connection_type: str = "subset"):
    template = os.path.join(cfg.lazagna_root, cfg.template_path)\
        if not os.path.isabs(cfg.template_path) else cfg.template_path
    spec = spec_or_none if spec_or_none is not None else NAMED_LAYOUTS["aligned"]
    arch = build_architecture(spec, cfg.width, cfg.height, template)

    opts = ExperimentOptions(
        experiment_name=exp_name,
        grid=GridOptions(width_3d=cfg.width, height_3d=cfg.height,
                         width_2d=cfg.width_2d, height_2d=cfg.height_2d,
                         channel_width=cfg.channel_width),
        benchmarks=BenchmarkOptions(directory=cfg.benchmark_dir, is_verilog=cfg.is_verilog),
        placement=PlacementOptions(algorithm=["cube_bb"]),
        seeds=SeedOptions(mode="fixed" if cfg.seeds == 1 else "random", value=cfg.seeds),
        switch_block_3d=SwitchBlock3DOptions(connectivity=[connectivity],
                                             connection_type=[connection_type]),
        interlayer_delay=InterlayerDelayOptions(delay_ratio=[delay_ratio]),
    )
    opts.architectures[0].type = arch_type

    result = run_lazagna(arch, opts, lazagna_root=cfg.lazagna_root)
    if result["returncode"] != 0:
        return None, result["stderr"][-500:]

    metrics = parse_results(os.path.join(cfg.lazagna_root, "results"), only_containing=exp_name)
    return metrics, None

def make_objective(cfg: SearchConfig, block_types=None):

    baseline = {"cpd": None, "wl": None}

    def ensure_baseline():
        if baseline["cpd"] is not None:
            return
        metrics, err = _run_one(cfg, None, f"{cfg.run_tag}base", "2d", 1.0, 1.0)
        if metrics is None:
            raise RuntimeError(f"2D baseline run failed: {err}")
        baseline["cpd"], baseline["wl"] = metrics

    def objective(trial: optuna.Trial) -> tuple[float, float]:
        ensure_baseline()
        if cfg.search_mode == "connectivity":
            spec = NAMED_LAYOUTS["aligned"]
            arch_type, connectivity, connection_type, delay_ratio = sample_connectivity(trial, cfg)
        elif cfg.search_mode == "columns":
            spec = sample_columns(trial, cfg)
            arch_type = cfg.arch_type
            connectivity = trial.suggest_categorical("connectivity", list(cfg.connectivity_choices))
            connection_type = "subset"
            delay_ratio = trial.suggest_float("delay_ratio", *cfg.delay_ratio_range)
        else:
            spec = sample_layout(trial, cfg)
            arch_type = cfg.arch_type
            connectivity = trial.suggest_categorical("connectivity", list(cfg.connectivity_choices))
            connection_type = "subset"
            delay_ratio = trial.suggest_float("delay_ratio", *cfg.delay_ratio_range)

        metrics, err = _run_one(cfg, spec, f"{cfg.run_tag}t{trial.number}",
                                arch_type, connectivity, delay_ratio, connection_type)
        if metrics is None:
            trial.set_user_attr("stderr_tail", err or "parse_failed")
            raise optuna.TrialPruned()

        cpd, wl = metrics

        cpd_impr = 100.0 * (baseline["cpd"] - cpd) / baseline["cpd"]
        wl_impr = 100.0 * (baseline["wl"] - wl) / baseline["wl"]
        trial.set_user_attr("cpd_raw", cpd)
        trial.set_user_attr("wl_raw", wl)
        trial.set_user_attr("cpd_impr_pct", cpd_impr)
        trial.set_user_attr("wl_impr_pct", wl_impr)
        trial.set_user_attr("baseline_cpd", baseline["cpd"])
        trial.set_user_attr("baseline_wl", baseline["wl"])

        return -cpd_impr, -wl_impr

    return objective

def _make_sampler(cfg: SearchConfig):
    if cfg.sampler == "nsga2":
        return optuna.samplers.NSGAIISampler()
    return optuna.samplers.TPESampler(constant_liar=cfg.parallel)


def run_study(cfg: SearchConfig, n_trials: int = 40, seed_named: bool = True,
              study_name: str = "lazagna_3d", storage: Optional[str] = None) -> optuna.Study:
    study = optuna.create_study(
        directions=["minimize", "minimize"],
        study_name=study_name,
        storage=storage,
        load_if_exists=storage is not None,
        sampler=_make_sampler(cfg),
    )

    if seed_named and cfg.search_mode == "layout":

        for name, spec in NAMED_LAYOUTS.items():
            params = {
                "family": spec.family,
                "asymmetry": spec.asymmetry,
                "separate_dsp_bram": spec.separate_dsp_bram,
                "connectivity": 1.0,
                "delay_ratio": 0.739,
            }
            if spec.family == "distributed":
                params["hb_period"] = spec.hb_period if spec.hb_period in cfg.hb_period_choices else 8
            else:
                params["edge_fraction"] = min(max(spec.edge_fraction, cfg.edge_fraction_range[0]),
                                              cfg.edge_fraction_range[1])
            study.enqueue_trial(params, user_attrs={"seeded_from": name})

    study.optimize(make_objective(cfg), n_trials=n_trials)
    return study

def report(study: optuna.Study) -> None:

    base_cpd = base_wl = None
    for t in study.trials:
        if t.user_attrs.get("baseline_cpd"):
            base_cpd = t.user_attrs["baseline_cpd"]
            base_wl = t.user_attrs["baseline_wl"]
            break

    print(f"\nfinished {len(study.trials)} trials")
    if base_cpd:
        print(f"2D baseline: CPD={base_cpd:.4e}  WL={base_wl:.1f}")
    print("\nPareto-optimal 3D configurations (improvement over 2D, higher = better):")

    best = sorted(study.best_trials,
                  key=lambda t: t.user_attrs.get("cpd_impr_pct", -999), reverse=True)
    for t in best:
        cpd_i = t.user_attrs.get("cpd_impr_pct")
        wl_i = t.user_attrs.get("wl_impr_pct")
        seeded = t.user_attrs.get("seeded_from", "")
        tag = f"  [from {seeded}]" if seeded else ""
        if cpd_i is not None:
            print(f"  trial {t.number}: CPD {cpd_i:+.2f}%  WL {wl_i:+.2f}%{tag}")
        else:
            print(f"  trial {t.number}: (pruned/no metrics){tag}")
        print(f"      params: {t.params}")

    scored = [t for t in study.trials if t.user_attrs.get("cpd_impr_pct") is not None]
    if scored:
        top = max(scored, key=lambda t: t.user_attrs["cpd_impr_pct"])
        print(f"\nBest CPD improvement overall: trial {top.number}, "
              f"{top.user_attrs['cpd_impr_pct']:+.2f}% vs 2D")
        print(f"  params: {top.params}")
        seeded_top = max((t for t in scored if t.user_attrs.get("seeded_from")),
                         key=lambda t: t.user_attrs["cpd_impr_pct"], default=None)
        if seeded_top and seeded_top.number != top.number:
            print(f"  best paper layout: {seeded_top.user_attrs['seeded_from']} "
                  f"at {seeded_top.user_attrs['cpd_impr_pct']:+.2f}% "
                  f"-- optimizer beat it by "
                  f"{top.user_attrs['cpd_impr_pct'] - seeded_top.user_attrs['cpd_impr_pct']:.2f} pts")

if __name__ == "__main__":
    cfg = SearchConfig(
        lazagna_root=os.environ.get("LAZAGNA_ROOT", os.path.expanduser("~/LaZagna")),
        benchmark_dir="{lazagna_root}/benchmarks/MCNC_benchmarks/clma",
        is_verilog=False,
        width=30, height=30, width_2d=42, height_2d=42,
        channel_width=100, seeds=3,
        search_mode="connectivity",
    )
    study = run_study(cfg, n_trials=15, study_name="lazagna_clma_conn",
                      storage="sqlite:///lazagna_clma_conn.db")
    report(study)
