"""The campaign scripts stage designs through benchmark_suites. The destinations and file
contents must be exactly what the old per-script code produced for koios/vtr, and BLIF suites
(mcnc) must now work too. The scripts read env vars and chdir at import, so each check runs
in a subprocess."""
import json
import os
import subprocess
import sys

import pytest

from conftest import REPO

pytest.importorskip("optuna")   # the campaign scripts import lazagna_optuna

SCRIPT = r"""
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["LAZAGNA_CODE"], "campaign"))
import experiment, characterize, worker
out = {}
for e in ["koios/eltwise_layer", "vtr/stereovision1", "koios/tpu_like.small.os"]:
    out["exp:" + e] = experiment.stage(e)
    out["char:" + e] = characterize.bench_dir(e)
    out["worker:" + e] = worker.stage_bench(e, "cols_")
out["char:missing"] = characterize.bench_dir("koios/nope")
out["mcnc"] = sorted(os.listdir(experiment.stage("mcnc/clma")))
out["mcnc_is_verilog"] = experiment.is_verilog_entry("mcnc/clma")
w = os.environ["WORK"]
out["files"] = sorted(os.path.relpath(os.path.join(r, f), w) for r, _, fs in os.walk(w) for f in fs)
print(json.dumps(out).replace(w, "$WORK"))
"""


def test_campaign_staging(fake_root, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO, WORK=str(work),
               TASK_INDEX="0", WORKER_ID="0")
    res = subprocess.run([sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-2000:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    for e, name in [("koios/eltwise_layer", "eltwise_layer"), ("vtr/stereovision1", "stereovision1"),
                    ("koios/tpu_like.small.os", "tpu_like.small.os")]:
        assert out["exp:" + e] == f"$WORK/bench/{name}"
        assert out["char:" + e] == f"$WORK/bench/char_{name}"
        assert out["worker:" + e] == f"$WORK/bench/cols_{name}"
    assert out["char:missing"] is None
    assert out["mcnc"] == ["clma.act", "clma.blif", "clma.v"] and out["mcnc_is_verilog"] is False
    assert "bench/eltwise_layer/eltwise_layer.v" in out["files"]
    assert not [f for f in out["files"] if f.endswith(".tmp")]
    src = open(os.path.join(fake_root, "benchmarks/VTR_benchmarks/stereovision1.v")).read()
    assert open(work / "bench" / "cols_stereovision1" / "stereovision1.v").read() == src


def test_worker_missing_design_is_fatal(fake_root, tmp_path):
    env = dict(os.environ, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO, WORK=str(tmp_path), WORKER_ID="0")
    code = ("import os, sys; sys.path.insert(0, os.path.join(os.environ['LAZAGNA_CODE'], 'campaign')); "
            "import worker; worker.stage_bench('koios/nope', 'cols_')")
    res = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=REPO)
    assert res.returncode != 0 and "FATAL" in res.stderr


EXPERIMENT_CUSTOM = r"""
import dataclasses, json, os, sys
sys.path.insert(0, os.path.join(os.environ["LAZAGNA_CODE"], "campaign"))
import experiment
import lazagna_optuna as lo
calls = []
experiment.autosize = lambda cfg: (dataclasses.replace(cfg, width=26, height=26, width_2d=36, height_2d=36), {})
def fake(cfg, spec, name, arch, conn, delay, **k):
    calls.append({"columns": spec.columns, "conn": conn, "delay": delay,
                  "vconn": k.get("vertical_connectivity"), "loc": k.get("sb_location")})
    return (1e-8, 1e3), None
experiment._run_one = fake
frac = {"dsp_frac_l0": 1.0, "bram_frac_l0": 0.0, "cluster": 0.2, "stagger": 0.5, "band_pos": 0.5}
experiment.run({"id": "c1", "kind": "custom", "design": "vtr/sha", "seeds": 2, "structured_frac": frac,
                "conn": 0.5, "delay": 0.9})
experiment.run({"id": "c2", "kind": "custom", "design": "vtr/sha", "seeds": 2,
                "structured": {"dsp_on_l0": 2, "bram_on_l0": 1, "cluster": 0.0, "stagger": 0.0, "band_pos": 0.5}})
cfg = dataclasses.replace(lo.SearchConfig(lazagna_root="/x", benchmark_dir=""), width=26, height=26)
print(json.dumps({"calls": calls, "want": lo.structured_from_fractions(cfg, frac).columns}))
"""


def test_experiment_custom_structured_frac(fake_root, tmp_path):
    """experiment.py can validate a multi-benchmark champion (fraction form, with its
    connectivity and delay); an old-style custom task runs exactly as before."""
    env = dict(os.environ, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO, WORK=str(tmp_path))
    res = subprocess.run([sys.executable, "-c", EXPERIMENT_CUSTOM], env=env, capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-2000:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    frac, old = out["calls"]
    assert frac["columns"] == out["want"]
    assert (frac["conn"], frac["delay"], frac["vconn"], frac["loc"]) == (0.5, 0.9, 1.0, "repeated_interval")
    assert (old["conn"], old["delay"], old["vconn"], old["loc"]) == (1.0, 0.739, 1.0, "repeated_interval")


EXPERIMENT_CHAMPION = r"""
import dataclasses, json, os, sys
sys.path.insert(0, os.path.join(os.environ["LAZAGNA_CODE"], "campaign"))
import experiment
import lazagna_optuna as lo
calls = []
experiment.autosize = lambda cfg: (dataclasses.replace(cfg, width=62, height=50, width_2d=71, height_2d=86), {})
def fake(cfg, spec, name, arch, conn, delay, **k):
    calls.append({"columns": spec.columns, "conn": conn, "delay": delay, "vconn": k.get("vertical_connectivity"),
                  "seeds": list(cfg.seed_list)})
    return (1e-8, 1e3), None
experiment._run_one = fake
task = json.loads(os.environ["TASK"])
experiment.run(task)
cfg = dataclasses.replace(lo.SearchConfig(lazagna_root="/x", benchmark_dir=""), width=62, height=50)
print(json.dumps({"calls": calls, "want": lo.structured_from_fractions(cfg, task["structured_frac"]).columns}))
"""


def test_experiment_runs_a_lean_champion_task(fake_root, tmp_path):
    """A tasks_champion.jsonl line of a study with sampled vertical links (vconn) runs with that
    vertical connectivity and connectivity."""
    task = {"id": "lean__s__sha", "design": "vtr/sha", "seeds": 5, "kind": "custom", "conn": 0.5, "vconn": 0.1,
            "delay": 0.739, "structured_frac": {"dsp_frac_l0": 1.0, "bram_frac_l0": 0.0, "cluster": 0.0,
                                                "stagger": 0.501, "band_pos": 0.5}}
    env = dict(os.environ, LAZAGNA_ROOT=fake_root, LAZAGNA_CODE=REPO, WORK=str(tmp_path), TASK=json.dumps(task))
    res = subprocess.run([sys.executable, "-c", EXPERIMENT_CHAMPION], env=env, capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, res.stderr[-2000:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    (c,) = out["calls"]
    assert (c["conn"], c["vconn"], c["delay"], c["seeds"]) == (0.5, 0.1, 0.739, [1, 2, 3, 4, 5])
    assert c["columns"] == out["want"]
