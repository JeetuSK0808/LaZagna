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


# ---- vertical links, links objective, anchors ---------------------------------------------------

TRIO = "koios/tpu_like.small.ws vtr/mkDelayWorker32B vtr/stereovision2"
RECOMMENDED = dict(DESIGNS=TRIO, TRIALS="64", ANCHORS="1", LINKS_OBJECTIVE="1", CONN_CHOICES="0.25 0.5 1.0",
                   VCONN_CHOICES="0.05 0.1 0.25 0.5 1.0")
ANCHOR_NAMES = ["even_split", "split_types", "split_rev", "hb_top", "hb_one_layer", "recommended"]
# the same worker, with every sleep (startup stagger, reference polls) cut short
DRIVER_FAST = "import time as _t\n_s = _t.sleep\n_t.sleep = lambda s: _s(min(s, 0.05))\n" + DRIVER
# ... and each enqueue_trial 0.3 s slow, so racing workers all look for queued anchors before the
# first one lands (with only the seeded_from check, every worker would then queue them all)
DRIVER_RACE = DRIVER_FAST.replace(
    "import lazagna_optuna as lo\n",
    "import optuna as _o\n_enq = _o.study.Study.enqueue_trial\n"
    "def _slow(self, *a, **k):\n    _s(0.3)\n    return _enq(self, *a, **k)\n"
    "_o.study.Study.enqueue_trial = _slow\nimport lazagna_optuna as lo\n", 1)


def add_trio(fake_root):
    for rel in ("koios/tpu_like.small.ws.v", "VTR_benchmarks/mkDelayWorker32B.v", "VTR_benchmarks/stereovision2.v"):
        open(os.path.join(fake_root, "benchmarks", rel), "w").write(f"// {rel}\n")


def test_default_study_records_what_it_did_before(env):
    run_worker(env)
    st = load(env)
    assert set(st.user_attrs) == {"designs", "search_mode", "sampler", "seeds", "fidelity", "channel_width", "tall",
                                  "target_util", "arch_type", "connectivity_choices", "delay_ratio_range",
                                  "objective_weights", "link_penalty"}
    assert len(st.directions) == 2 and all("vertical_connectivity" not in t.params for t in st.trials)
    assert not [t for t in st.trials if "seeded_from" in t.user_attrs]
    assert not os.path.exists(os.path.join(env["WORK"], "journal", "s1.anchors"))


def test_recommended_settings(env, fake_root):
    add_trio(fake_root)
    out = run_worker(dict(env, **dict(RECOMMENDED, TRIALS="9", SAMPLER="tpe")))
    assert "queued anchors: " + ", ".join(ANCHOR_NAMES) in out
    st = load(env)
    assert len(st.directions) == 3
    ua = st.user_attrs
    assert ua["designs"] == TRIO.split() and ua["links_objective"] is True and ua["anchors"] is True
    assert ua["vertical_connectivity_choices"] == [0.05, 0.1, 0.25, 0.5, 1.0]
    assert ua["connectivity_choices"] == [0.25, 0.5, 1.0]
    assert [t.user_attrs.get("seeded_from") for t in st.trials] == ANCHOR_NAMES + [None] * 3
    for t in st.trials:
        assert t.state.name == "COMPLETE"
        links = t.params["connectivity"] * t.params["vertical_connectivity"]
        assert t.user_attrs["link_fraction"] == pytest.approx(links) and t.values[2] == pytest.approx(links)
    assert st.trials[5].params["vertical_connectivity"] == 0.1 and st.trials[1].params["stagger"] == 0.501
    res = subprocess.run([sys.executable, os.path.join(REPO, "campaign", "analyze_optuna.py")], env=env,
                         capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-3000:]
    rep = open(os.path.join(env["WORK"], "analysis", "s1", "report.md")).read()
    assert "three objectives" in rep and '## Champion "best"' in rep and '## Champion "lean"' in rep
    assert "Anchors (known layouts queued first): even_split = trial 0" in rep


def test_anchors_queued_once_by_racing_workers(env):
    """Four workers that start at the same moment (same WORKER_ID, so no startup stagger) share
    one study: each anchor is queued exactly once, and a restarted worker queues nothing."""
    assert DRIVER_RACE != DRIVER_FAST
    e = dict(env, ANCHORS="1", TRIALS="12", CONN_CHOICES="0.5 1.0", VCONN_CHOICES="0.1 1.0")
    procs = [subprocess.Popen([sys.executable, "-c", DRIVER_RACE], env=e, cwd=REPO,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outs = [p.communicate(timeout=600) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1][-2000:] for o in outs]
    assert sum(o[0].count("queued anchors:") for o in outs) == 1
    seeded = [t.user_attrs["seeded_from"] for t in load(env).trials if "seeded_from" in t.user_attrs]
    assert sorted(seeded) == sorted(ANCHOR_NAMES)
    assert open(os.path.join(env["WORK"], "journal", "s1.anchors")).read().split() == ANCHOR_NAMES
    out = run_worker(dict(e, TRIALS="14"))                           # restart with a bigger budget
    assert "queued anchors" not in out
    st = load(env)
    assert sorted(t.user_attrs["seeded_from"] for t in st.trials if "seeded_from" in t.user_attrs) == \
        sorted(ANCHOR_NAMES)
    assert sum(1 for t in st.trials if t.state.name == "COMPLETE") >= 14


def test_nsga_population_and_vertical_links_reach_the_study(env):
    run_worker(dict(env, SAMPLER="nsga2", NSGA_POP="4", TRIALS="6", VCONN_CHOICES="0.1 1.0"))
    st = load(env)
    assert st.user_attrs["nsga_population"] == 4 and st.user_attrs["vertical_connectivity_choices"] == [0.1, 1.0]
    assert all(t.params["vertical_connectivity"] in (0.1, 1.0) for t in st.trials)


def test_launcher_dry_run_recommended(tmp_path):
    r = _launch(tmp_path, **RECOMMENDED)
    assert r.returncode == 0, r.stdout + r.stderr
    cmds = [l for l in r.stderr.splitlines() if l.startswith("sbatch ")]
    search = next(c for c in cmds if "PHASE=search" in c)
    report = next(c for c in cmds if "PHASE=report" in c)
    assert "--array=0-7" in search and "-A gts-DRYRUN" in search and search.endswith("suite_study.sbatch")
    assert "--dependency=afterany:" in report and "SEARCH_JOB=" in report and report.endswith("suite_study.sbatch")
    envf = tmp_path / "w" / "suite_study.env"
    got = subprocess.run(["bash", "-c", f". '{envf}'; echo \"$DESIGNS|$TRIALS|$ANCHORS|$LINKS_OBJECTIVE|$CONN_CHOICES"
                                        f"|$VCONN_CHOICES|${{FIDELITY:-route}}\""],
                         capture_output=True, text=True).stdout.strip()
    assert got == f"{TRIO}|64|1|1|0.25 0.5 1.0|0.05 0.1 0.25 0.5 1.0|route"
    assert "note:" not in r.stdout


@pytest.mark.parametrize("bad", [dict(LINKS_OBJECTIVE="1", WEIGHTS="0.7,0.3"), dict(LINKS_OBJECTIVE="1", LINK_PENALTY="2"),
                                 dict(LINKS_OBJECTIVE="yes"), dict(ANCHORS="2"), dict(ANCHORS="1", SEARCH_MODE="layout"),
                                 dict(VCONN_CHOICES="0 1"), dict(VCONN_CHOICES="0.5,2"), dict(CONN_CHOICES="half"),
                                 dict(VCONN_CHOICES="0.5", SEARCH_MODE="connectivity"), dict(NSGA_POP="1"),
                                 dict(NSGA_POP="ten"), dict(CHAMPION_MAX_LINKS="-0.1"), dict(LINK_PENALTY="a lot"),
                                 dict(TRIALS="0")])
def test_launcher_refuses_bad_link_settings(tmp_path, bad):
    r = _launch(tmp_path, **bad)
    assert r.returncode != 0 and not os.path.exists(tmp_path / "w"), r.stdout


def test_launcher_notes(tmp_path):
    r = _launch(tmp_path, LINKS_OBJECTIVE="1", LINK_PENALTY="0")
    assert r.returncode == 0 and "every trial has the same links" in r.stdout
    r = _launch(tmp_path, SAMPLER="nsga2", TRIALS="40")
    assert r.returncode == 0 and "samples at random throughout" in r.stdout


def test_sbatch_passes_the_settings_into_the_container(tmp_path):
    """suite_study.sbatch, both phases, with a stand-in apptainer that records what it is given."""
    camp = tmp_path / "campaign_dir"
    camp.mkdir()
    for d in ("campaign", "arch_files"):
        os.symlink(os.path.join(REPO, d), camp / d)
    (camp / "lazagna.sif").write_text("")
    (camp / "logs" / "suite").mkdir(parents=True)
    stub = tmp_path / "bin" / "apptainer"
    stub.parent.mkdir()
    stub.write_text('#!/bin/bash\n{ echo "CALL $*"; env | grep "^APPTAINERENV_" | sort; } >> "$STUB_LOG"\n')
    stub.chmod(0o755)
    r = _launch(tmp_path, CHAMPION_MAX_LINKS="0.2", NSGA_POP="16", SAMPLER="nsga2", **RECOMMENDED)
    assert r.returncode == 0, r.stdout + r.stderr
    log = tmp_path / "stub.log"
    base = dict(os.environ, PATH=f"{stub.parent}:{os.environ['PATH']}", CAMPAIGN=str(camp),
                WORK_ROOT=str(tmp_path / "w"), STUB_LOG=str(log), SLURM_ARRAY_TASK_ID="3")
    for phase in ("search", "report"):
        p = subprocess.run(["bash", os.path.join(REPO, "suite_study.sbatch")], env=dict(base, PHASE=phase),
                           capture_output=True, text=True, cwd=str(camp))
        assert p.returncode == 0, p.stdout + p.stderr
    calls = log.read_text().split("CALL ")
    worker = next(c for c in calls if "/campaign/suite_study.py" in c)
    for line in ("APPTAINERENV_VCONN_CHOICES=0.05 0.1 0.25 0.5 1.0", "APPTAINERENV_LINKS_OBJECTIVE=1",
                 "APPTAINERENV_ANCHORS=1", "APPTAINERENV_NSGA_POP=16", "APPTAINERENV_TRIALS=64",
                 "APPTAINERENV_CONN_CHOICES=0.25 0.5 1.0", f"APPTAINERENV_DESIGNS={TRIO}", "APPTAINERENV_WORKER_ID=3"):
        assert line in worker.splitlines(), line
    analysis = next(c for c in calls if "/campaign/analyze_optuna.py" in c)
    assert "APPTAINERENV_CHAMPION_MAX_LINKS=0.2" in analysis.splitlines()
    assert os.path.exists(tmp_path / "w" / "w_results.tar.gz")
