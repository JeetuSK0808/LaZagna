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
