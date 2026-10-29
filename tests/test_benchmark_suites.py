import os

import pytest

import benchmark_suites as bs
from conftest import REAL_FOLDERS


def test_registry_points_at_real_submodule_folders():
    for s in bs.SUITES.values():
        assert s.directory.startswith("benchmarks/")
        assert s.directory.split("/", 1)[1] in REAL_FOLDERS, s.name


def test_list_designs_flat_skips_helpers(fake_root):
    assert bs.list_designs("koios", fake_root) == ["attention_layer", "eltwise_layer", "tpu_like.small.os"]
    assert bs.list_designs("koios_proxy", fake_root) == ["proxy.1", "proxy.2"]
    assert bs.list_designs("vtr", fake_root) == ["or1200", "sha", "stereovision1"]


def test_list_designs_per_design_dirs(fake_root):
    assert bs.list_designs("mcnc", fake_root) == ["clma", "s38417"]
    assert bs.list_designs("dsp_bram_tests", fake_root) == ["bram_test", "mac_test"]
    assert bs.list_designs("and2_or2", fake_root) == ["and2_or2"]


def test_missing_suite_dir_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="submodule"):
        bs.list_designs("vtr", str(tmp_path))


def test_parse_entry():
    s, d = bs.parse_entry("koios/tpu_like.small.os")
    assert s.name == "koios" and d == "tpu_like.small.os"
    for bad in ("koios", "koios/", "koios/a/b"):
        with pytest.raises(ValueError):
            bs.parse_entry(bad)
    with pytest.raises(KeyError, match="Known suites"):
        bs.parse_entry("nope/x")


def test_expand(fake_root):
    assert bs.expand(["vtr"], fake_root) == ["vtr/or1200", "vtr/sha", "vtr/stereovision1"]
    assert bs.expand(["mcnc/*", "vtr/sha", "mcnc/clma"], fake_root) == ["mcnc/clma", "mcnc/s38417", "vtr/sha"]
    with pytest.raises(FileNotFoundError):
        bs.expand(["vtr/nope"], fake_root)


def test_design_files(fake_root):
    f = bs.design_files("mcnc/clma", fake_root)
    assert f["blif"].endswith("MCNC_benchmarks/clma/clma.blif")
    assert f["act"].endswith("clma.act") and f["verilog"].endswith("clma.v")
    f = bs.design_files("vtr/sha", fake_root)
    assert f["verilog"].endswith("VTR_benchmarks/sha.v") and f["blif"] is None
    assert bs.is_verilog_entry("vtr/sha") and not bs.is_verilog_entry("mcnc/clma")


def test_stage_verilog_copies_only_the_design(fake_root, tmp_path):
    d = bs.stage_design("koios/eltwise_layer", fake_root, str(tmp_path / "work"), prefix="cols_")
    assert d == str(tmp_path / "work" / "bench" / "cols_eltwise_layer")
    assert os.listdir(d) == ["eltwise_layer.v"]


def test_stage_blif_copies_blif_act_and_v(fake_root, tmp_path):
    d = bs.stage_design("mcnc/clma", fake_root, str(tmp_path / "work"))
    assert sorted(os.listdir(d)) == ["clma.act", "clma.blif", "clma.v"]


def test_stage_keeps_existing_copy_unless_refresh(fake_root, tmp_path):
    work = str(tmp_path / "work")
    d = bs.stage_design("vtr/sha", fake_root, work)
    dst = os.path.join(d, "sha.v")
    with open(dst, "w") as f:
        f.write("local edit")
    bs.stage_design("vtr/sha", fake_root, work)
    assert open(dst).read() == "local edit"
    bs.stage_design("vtr/sha", fake_root, work, refresh=True)
    assert open(dst).read().startswith("// VTR_benchmarks/sha.v")
    assert not [f for f in os.listdir(d) if f.endswith(".tmp")]


def test_stage_missing_source(fake_root, tmp_path):
    with pytest.raises(FileNotFoundError, match="benchmark source missing"):
        bs.stage_design("vtr/nope", fake_root, str(tmp_path))


def test_suite_for_directory(fake_root):
    assert bs.suite_for_directory("{lazagna_root}/benchmarks/VTR_benchmarks", fake_root).name == "vtr"
    assert bs.suite_for_directory(fake_root + "/benchmarks/somewhere_else", fake_root) is None
