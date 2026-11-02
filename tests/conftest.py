"""Shared fixtures. The tests need no OpenFPGA/VPR build and no network: designs come from a
small fake copy of the benchmarks/ submodule (same folder names and file layout)."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "lazagna")):
    if p not in sys.path:
        sys.path.insert(0, p)

# A few files from each folder of github.com/IY2002/Benchmarks_LaZagna (paths are real).
FAKE_FILES = [
    "koios/README.md", "koios/attention_layer.v", "koios/eltwise_layer.v", "koios/tpu_like.small.os.v",
    "koios/complex_dsp_include.v", "koios/hard_block_include.v", "koios/hard_mem_include.v", "koios/test.v",
    "koios_proxy/README.md", "koios_proxy/proxy.1.v", "koios_proxy/proxy.2.v",
    "VTR_benchmarks/sha.v", "VTR_benchmarks/or1200.v", "VTR_benchmarks/stereovision1.v",
    "MCNC_benchmarks/clma/clma.blif", "MCNC_benchmarks/clma/clma.act", "MCNC_benchmarks/clma/clma.v",
    "MCNC_benchmarks/s38417/s38417.blif", "MCNC_benchmarks/s38417/s38417.act", "MCNC_benchmarks/s38417/s38417.v",
    "ITD_paper/softmax.v", "ITD_subset/softmax.v",
    "ITD_quick/eltwise_layer.v", "ITD_quick/softmax.v", "ITD_quick/spmv.v",
    "eltwise/eltwise_layer.v",
    "dsp_bram_tests/bram_test/bram_test.v", "dsp_bram_tests/mac_test/mac_test.v",
    "and2_or2/and2_or2.blif", "and2_or2/and2_or2.act", "and2_or2/and2_or2.v",
    "des/des.blif", "des/des.act", "des/des.v",
]
# Top-level folders of the real submodule (commit cb83712).
REAL_FOLDERS = {"ITD_paper", "ITD_quick", "ITD_subset", "MCNC_benchmarks", "VTR_benchmarks", "and2",
                "and2_or2", "des", "dsp_bram_tests", "eltwise", "koios", "koios_proxy"}


@pytest.fixture
def fake_root(tmp_path):
    root = tmp_path / "lazagna_root"
    for rel in FAKE_FILES:
        p = root / "benchmarks" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {rel}\n")
    return str(root)
