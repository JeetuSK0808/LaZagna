"""The multi-benchmark study entry point: campaign/suite_study.py with the flow mocked out (two
"workers" sharing one journal, then the analysis), and the PACE launcher in DRY_RUN mode."""
import json
import os
import subprocess
import sys

import pytest

from conftest import REPO

optuna = pytest.importorskip("optuna")

# Runs suite_study.main() with the VPR flow, synthesis and sizing replaced by stand-ins.
DRIVER = r"""
import dataclasses, hashlib, os, sys
sys.path[:0] = [os.environ["LAZAGNA_CODE"], os.path.join(os.environ["LAZAGNA_CODE"], "campaign")]
import lazagna_optuna as lo

def fake_autosize(cfg):
    return dataclasses.replace(cfg, width=22, height=22, width_2d=30, height_2d=30), {}

def fake_run_one(cfg, spec, name, arch_type, conn, delay, *a, **k):
    h = int(hashlib.sha1(repr((os.path.basename(cfg.benchmark_dir), spec.columns if hasattr(spec, "columns") else spec,
                               conn, delay, name.endswith("ref"))).encode()).hexdigest(), 16)
    f = 1 + ((h % 1000) / 1000 - 0.5) * 0.2
    return ((1e-8, 1e3) if name.endswith("ref") else (1e-8 * f, 1e3 * f)), None

lo.autosize = fake_autosize
lo._run_one = fake_run_one
lo.prepare = lambda cfg: {"demand": {"clb": 100, "complex_dsp": 2, "spram": 3}}
import suite_study
suite_study.main()
"""


def run_worker(env):
    res = subprocess.run([sys.executable, "-c", DRIVER], env=env, capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-3000:]
    return res.stdout


@pytest.fixture
def env(fake_root, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    return dict(os.environ, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO, WORK=str(work), WORKER_ID="0",
                DESIGNS="vtr/sha mcnc/clma", SAMPLER="random", STUDY="s1", TRIALS="3", MPLBACKEND="Agg")


def load(env):
    from lazagna_optuna import journal_storage
    return optuna.load_study(study_name=env["STUDY"],
                             storage=journal_storage(os.path.join(env["WORK"], "journal", env["STUDY"] + ".log")))


def test_workers_share_one_study_then_report(env):
    out = run_worker(env)
    assert "ALL DONE" in out and "vtr/sha: 2D 30x30, 3D 2x22x22" in out
    st = load(env)
    assert [t.state.name for t in st.trials] == ["COMPLETE"] * 3
    ua = st.user_attrs
    assert ua["designs"] == ["vtr/sha", "mcnc/clma"] and ua["search_mode"] == "structured"
    assert ua["sampler"] == "random" and ua["arch_type"] == "combined" and ua["objective_weights"] == []
    assert sorted(st.trials[0].user_attrs["per_design"]) == ["mcnc/clma", "vtr/sha"]
    work = env["WORK"]
    designs = json.load(open(os.path.join(work, "designs.json")))
    assert [d["design"] for d in designs] == ["vtr/sha", "mcnc/clma"] and designs[0]["device_3d"] == [2, 22, 22]
    assert len([f for f in os.listdir(os.path.join(work, "journal", "baselines")) if f.endswith(".json")]) == 2
    assert sorted(os.listdir(os.path.join(work, "bench"))) == ["suite_clma", "suite_sha"]

    # a second worker with a bigger budget adds only the missing trials
    run_worker(dict(env, WORKER_ID="1", TRIALS="5"))
    assert len(load(env).trials) == 5

    res = subprocess.run([sys.executable, os.path.join(REPO, "campaign", "analyze_optuna.py")], env=env,
                         capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-3000:]
    d = os.path.join(work, "analysis", "s1")
    assert "s1: 5 complete trials" in res.stdout
    assert os.path.exists(os.path.join(d, "report.md")) and os.path.exists(os.path.join(d, "tasks_champion.jsonl"))


def test_other_designs_in_the_same_study_are_refused(env):
    run_worker(env)
    res = subprocess.run([sys.executable, "-c", DRIVER], env=dict(env, DESIGNS="vtr/sha"),
                         capture_output=True, text=True, cwd=REPO)
    assert res.returncode != 0 and "was started with designs" in res.stderr


def test_weighted_study_has_one_objective(env):
    run_worker(dict(env, WEIGHTS="0.7,0.3", LINK_PENALTY="1", CONN_CHOICES="0.5 1.0"))
    st = load(env)
    assert len(st.directions) == 1 and st.user_attrs["objective_weights"] == [0.7, 0.3]
    for t in st.trials:
        u, pen = t.user_attrs, 1.0 * t.user_attrs["link_fraction"]
        assert t.value == pytest.approx(-(0.7 * (u["cpd_impr_pct"] - pen) + 0.3 * (u["wl_impr_pct"] - pen)))
        assert t.params["connectivity"] in (0.5, 1.0)


def _launch(tmp_path, **extra):
    env = dict(os.environ, DRY_RUN="1", WORK_ROOT=str(tmp_path / "w"), **extra)
    env.pop("ACCOUNT", None)
    return subprocess.run(["bash", os.path.join(REPO, "campaign", "suite_study.sh")], env=env,
                          capture_output=True, text=True)


def test_launcher_dry_run(tmp_path):
    r = _launch(tmp_path, DESIGNS="koios/eltwise_layer vtr/stereovision1", SAMPLER="nsga3", WEIGHTS="0.7,0.3",
                N_WORKERS="4")
    assert r.returncode == 0, r.stdout + r.stderr
    cmds = [l for l in r.stderr.splitlines() if l.startswith("sbatch ")]
    search = next(c for c in cmds if "PHASE=search" in c)
    report = next(c for c in cmds if "PHASE=report" in c)
    assert "--array=0-3" in search and "suite_study.sbatch" in search and "-A gts-DRYRUN" in search
    assert "--dependency=afterany:" in report and "SEARCH_JOB=" in report and "--output=logs/suite/report_%j.out" in report
    envf = open(tmp_path / "w" / "suite_study.env").read()
    assert "DESIGNS=koios/eltwise_layer\\ vtr/stereovision1" in envf and "SAMPLER=nsga3" in envf
    assert "WEIGHTS=0.7\\,0.3" in envf or "WEIGHTS=0.7,0.3" in envf
    # the env file must give back the exact values when the job script sources it
    got = subprocess.run(["bash", "-c", f". '{tmp_path / 'w' / 'suite_study.env'}'; echo \"$DESIGNS|$WEIGHTS\""],
                         capture_output=True, text=True).stdout.strip()
    assert got == "koios/eltwise_layer vtr/stereovision1|0.7,0.3"
    assert "_results.tar.gz" in r.stdout


@pytest.mark.parametrize("bad", [dict(SAMPLER="cmaes"), dict(SEARCH_MODE="columns"), dict(WEIGHTS="0.7"),
                                 dict(N_WORKERS="0"), dict(FIDELITY="fast")])
def test_launcher_refuses_bad_settings(tmp_path, bad):
    r = _launch(tmp_path, **bad)
    assert r.returncode != 0 and not os.path.exists(tmp_path / "w")


@pytest.mark.parametrize("script", ["campaign/suite_study.sh", "suite_study.sbatch", "submit_campaign.sh"])
def test_shell_syntax(script):
    assert subprocess.run(["bash", "-n", os.path.join(REPO, script)]).returncode == 0
