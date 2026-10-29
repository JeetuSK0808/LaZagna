import glob
import json
import os
import random

import pytest
import yaml

from conftest import REPO
import yaml_file_processing_v2 as v2
import main as lzmain

GOLDEN = os.path.join(REPO, "tests", "data", "yaml_v2_golden.json")


def _run(path):
    random.seed(12345)
    return v2.get_run_params_from_yaml_v2(path)


def test_existing_setup_files_unchanged():
    """Every shipped setup file expands to exactly what it did before suites were added
    (golden output recorded from the previous code)."""
    golden = json.load(open(GOLDEN))
    cwd = os.getcwd()
    os.chdir(REPO)
    try:
        for rel, want in golden.items():
            got = json.loads(json.dumps(_run(rel), sort_keys=True, default=str).replace(v2.LAZAGNA_ROOT, "{lazagna_root}"))
            assert got == want, rel
    finally:
        os.chdir(cwd)


def test_plain_form_has_no_mapping():
    assert v2.build_benchmark_mapping(None) is None
    assert v2.build_benchmark_mapping({"directory": "x", "is_verilog": True}) is None


def _write(tmp_path, cfg):
    p = tmp_path / "setup.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return str(p)


@pytest.fixture
def at_fake_root(fake_root, monkeypatch):
    monkeypatch.setattr(v2, "LAZAGNA_ROOT", fake_root)
    monkeypatch.setattr(lzmain, "original_dir", fake_root)
    return fake_root


def test_list_of_suites_is_swept_and_tagged(at_fake_root, tmp_path):
    combos = _run(_write(tmp_path, {"experiment_name": "ms", "benchmarks": [
        {"suite": "and2_or2"}, {"suite": "itd_quick", "designs": ["softmax", "spmv"]}]}))
    assert [c["cur_loop_identifier"] for c in combos] == ["ms_and2_or2_vp_0.739", "ms_itd_quick_vp_0.739"]
    assert [c["is_verilog_benchmarks"] for c in combos] == [False, True]
    params = lzmain.setup_benchmark_files(combos)
    assert [os.path.basename(f) for f in params[0]["blif_files"]] == ["and2_or2.blif"]
    assert [os.path.basename(f) for f in params[0]["act_files"]] == ["and2_or2.act"]
    assert [os.path.basename(f) for f in params[1]["verilog_files"]] == ["softmax.v", "spmv.v"]


def test_single_suite_entry_has_no_tag(at_fake_root, tmp_path):
    combos = _run(_write(tmp_path, {"experiment_name": "one", "benchmarks": {"suite": "vtr", "designs": ["sha"]}}))
    assert [c["cur_loop_identifier"] for c in combos] == ["one_vp_0.739"]
    p = lzmain.setup_benchmark_files(combos)[0]
    assert [os.path.basename(f) for f in p["verilog_files"]] == ["sha.v"]
    assert p["top_module_names"] is lzmain.VTR_benchmarks_top_modules


def test_suite_skips_helper_files(at_fake_root, tmp_path):
    p = lzmain.setup_benchmark_files(_run(_write(tmp_path, {"experiment_name": "k", "benchmarks": {"suite": "koios"}})))[0]
    assert sorted(os.path.basename(f) for f in p["verilog_files"]) == [
        "attention_layer.v", "eltwise_layer.v", "tpu_like.small.os.v"]


def test_mcnc_design_filter(at_fake_root, tmp_path):
    p = lzmain.setup_benchmark_files(_run(_write(tmp_path, {"experiment_name": "m", "benchmarks": {
        "suite": "mcnc", "designs": ["s38417"]}})))[0]
    assert [os.path.relpath(f, at_fake_root) for f in p["blif_files"]] == [
        "benchmarks/MCNC_benchmarks/s38417/s38417.blif"]


def test_same_basename_entries_get_unique_labels(at_fake_root, tmp_path):
    combos = _run(_write(tmp_path, {"experiment_name": "d", "benchmarks": [
        {"directory": "{lazagna_root}/benchmarks/eltwise", "is_verilog": True},
        {"suite": "eltwise"}]}))
    ids = [c["cur_loop_identifier"] for c in combos]
    assert len(set(ids)) == 2, ids


@pytest.mark.parametrize("bench, err", [
    ([{"suite": "nope"}], KeyError),
    ([{"suite": "vtr", "is_verilog": False}], ValueError),
    ([{"suite": "vtr", "directory": "{lazagna_root}/benchmarks/koios"}], ValueError),
    ([{"designs": ["x"]}], ValueError),
    ([{"suite": "vtr", "desings": ["x"]}], ValueError),
    ([], ValueError),
    (["vtr"], ValueError),
])
def test_bad_entries_are_rejected(at_fake_root, tmp_path, bench, err):
    with pytest.raises(err):
        _run(_write(tmp_path, {"experiment_name": "e", "benchmarks": bench}))


def test_missing_design_is_an_error(at_fake_root, tmp_path):
    combos = _run(_write(tmp_path, {"experiment_name": "x", "benchmarks": {"suite": "vtr", "designs": ["nope"]}}))
    with pytest.raises(ValueError, match="not found"):
        lzmain.setup_benchmark_files(combos)


def test_blif_entry_needs_act_and_v(at_fake_root, tmp_path):
    os.remove(os.path.join(at_fake_root, "benchmarks/des/des.act"))
    combos = _run(_write(tmp_path, {"experiment_name": "x", "benchmarks": {"suite": "des"}}))
    with pytest.raises(ValueError, match="des.act"):
        lzmain.setup_benchmark_files(combos)


def test_example_setup_file_parses(at_fake_root):
    combos = _run(os.path.join(REPO, "setup_files", "multi_suite_test.yaml"))
    assert len(combos) == 2
    assert {c["benchmark_suite"] for c in combos} == {"and2_or2", "itd_quick"}


def test_plain_directory_path_unchanged(at_fake_root):
    """The plain form still lists every file of the extension (helpers included), as before."""
    p = lzmain.setup_benchmark_files([{"benchmarks_dir": at_fake_root + "/benchmarks/koios",
                                       "is_verilog_benchmarks": True}])[0]
    assert len(p["verilog_files"]) == 7
