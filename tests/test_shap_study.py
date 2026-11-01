"""campaign/shap_study.py's table of the study runs, built from the versioned results."""
import os
import sys

import pytest

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "campaign"))
import shap_study  # noqa: E402

STUDY = os.path.join(REPO, "docs", "study")


@pytest.fixture(scope="module")
def rows():
    if not os.path.isdir(os.path.join(STUDY, "results")):
        pytest.skip("study results not present")
    return shap_study.build_rows(STUDY)


def test_one_row_per_configuration(rows):
    assert len(rows) == 255 and len({r["design"] for r in rows}) == 22
    keys = [(r["design"], r["layout"], r["conn"], r["vconn"], r["loc"], r["delay"], r["id"].startswith("custom"))
            for r in rows if r["kind"] != "custom"]
    assert len(keys) == len(set(keys))
    assert sum(r["kind"] == "rq1" for r in rows) == 22


def test_gains_match_the_study_tables(rows):
    by = {r["id"]: r for r in rows}
    spmv = by["rq1__spmv"]                       # tables.md RQ1: +23.8 CPD, +15.9 WL
    assert round(spmv["cpd_vs2d_pct"], 1) == 23.8 and round(spmv["wl_vs2d_pct"], 1) == 15.9
    assert spmv["cpd_vs3d_pct"] == "" and spmv["n_vs2d"] == 5
    edges = by["layout__tpu_like.small.os__edges"]   # tables.md RQ2: WL -27.2 vs aligned
    assert round(edges["wl_vs3d_pct"], 1) == -27.2


def test_committed_csv_is_current(rows, tmp_path):
    path = tmp_path / "runs.csv"
    shap_study.write_csv(rows, str(path))
    assert open(path).read() == open(os.path.join(STUDY, "study_runs.csv")).read()
