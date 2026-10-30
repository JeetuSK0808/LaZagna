import pytest

from lazagna_arch_model import BenchmarkOptions, ExperimentOptions


def test_default_benchmarks_dict_unchanged():
    assert ExperimentOptions().to_dict()["benchmarks"] == {
        "directory": "{lazagna_root}/benchmarks/and2_or2", "is_verilog": False}


def test_from_suite():
    b = BenchmarkOptions.from_suite("mcnc", ["clma"])
    assert b.to_dict() == {"directory": "{lazagna_root}/benchmarks/MCNC_benchmarks", "is_verilog": False,
                           "suite": "mcnc", "designs": ["clma"]}
    assert BenchmarkOptions.from_suite("vtr").to_dict() == {
        "directory": "{lazagna_root}/benchmarks/VTR_benchmarks", "is_verilog": True, "suite": "vtr"}
    with pytest.raises(KeyError):
        BenchmarkOptions.from_suite("nope")


def test_list_of_benchmarks():
    d = ExperimentOptions(benchmarks=[BenchmarkOptions.from_suite("vtr"), BenchmarkOptions()]).to_dict()
    assert isinstance(d["benchmarks"], list) and len(d["benchmarks"]) == 2
    assert d["benchmarks"][1] == {"directory": "{lazagna_root}/benchmarks/and2_or2", "is_verilog": False}


def test_fast_flow_refuses_a_list():
    from lazagna_fastflow import prepare_benchmark
    opts = ExperimentOptions(benchmarks=[BenchmarkOptions.from_suite("vtr")])
    with pytest.raises(ValueError, match="one design"):
        prepare_benchmark("<architecture/>", opts, "/nonexistent", "/nonexistent")
