"""Benchmark suites shipped in the benchmarks/ submodule, in one place.

Every place that runs designs from a suite (the YAML flow, the Python API, the Optuna search
and the campaign scripts) resolves suite names through this module, so a suite is defined once.

A design is named "<suite>/<design>", e.g. "koios/eltwise_layer", "vtr/stereovision1" or
"mcnc/clma". `expand()` also accepts a bare suite name ("vtr") or "vtr/*" for every design in it.

Layouts on disk (paths relative to the LaZagna root):
  flat            <dir>/<design>.v              (Verilog suites: koios, vtr, itd_*, ...)
  per-design dir  <dir>/<design>/<design>.blif  (+ .act and .v; MCNC)
"""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

VERILOG = "verilog"
BLIF = "blif"


@dataclass(frozen=True)
class Suite:
    name: str
    directory: str                    # relative to the LaZagna root
    fmt: str                          # VERILOG or BLIF
    per_design_dirs: bool = False     # True: one sub-directory per design
    exclude: tuple[str, ...] = ()     # file stems that are helpers, not designs
    description: str = ""

    @property
    def is_verilog(self) -> bool:
        return self.fmt == VERILOG

    @property
    def ext(self) -> str:
        return ".v" if self.is_verilog else ".blif"

    def path(self, lazagna_root: str) -> str:
        return os.path.join(lazagna_root, self.directory)


SUITES: dict[str, Suite] = {s.name: s for s in (
    Suite("koios", "benchmarks/koios", VERILOG,
          # include files and a test stub that sit next to the designs
          exclude=("complex_dsp_include", "hard_block_include", "hard_mem_include", "test"),
          description="Koios deep-learning benchmarks"),
    Suite("koios_proxy", "benchmarks/koios_proxy", VERILOG,
          description="Koios proxy designs (proxy.1 - proxy.8)"),
    Suite("vtr", "benchmarks/VTR_benchmarks", VERILOG,
          description="VTR benchmarks"),
    Suite("mcnc", "benchmarks/MCNC_benchmarks", BLIF, per_design_dirs=True,
          description="MCNC20, pre-synthesized BLIF with activity files"),
    Suite("itd_paper", "benchmarks/ITD_paper", VERILOG,
          description="Koios designs used in the ITD paper"),
    Suite("itd_subset", "benchmarks/ITD_subset", VERILOG,
          description="Subset of itd_paper"),
    Suite("itd_quick", "benchmarks/ITD_quick", VERILOG,
          description="Small, quick subset of itd_paper"),
    Suite("eltwise", "benchmarks/eltwise", VERILOG,
          description="eltwise_layer on its own"),
    Suite("dsp_bram_tests", "benchmarks/dsp_bram_tests", VERILOG, per_design_dirs=True,
          description="Small DSP / BRAM test designs"),
    Suite("and2_or2", "benchmarks/and2_or2", BLIF,
          description="Smoke-test design (the flow's default)"),
    Suite("des", "benchmarks/des", BLIF,
          description="des, on its own"),
)}


def get_suite(name: str) -> Suite:
    try:
        return SUITES[name]
    except KeyError:
        raise KeyError(f"unknown benchmark suite '{name}'. Known suites: {', '.join(sorted(SUITES))}") from None


def suite_for_directory(directory: str, lazagna_root: str) -> Optional[Suite]:
    """The registered suite whose directory is `directory` ({lazagna_root} allowed), if any."""
    d = os.path.normpath(directory.replace("{lazagna_root}", lazagna_root))
    for s in SUITES.values():
        if os.path.normpath(s.path(lazagna_root)) == d:
            return s
    return None


def parse_entry(entry: str) -> tuple[Suite, str]:
    """'suite/design' -> (Suite, design). Design names may contain dots ('tpu_like.small.os')."""
    if "/" not in entry:
        raise ValueError(f"design entry '{entry}' must look like '<suite>/<design>', e.g. 'koios/eltwise_layer'")
    suite_name, design = entry.split("/", 1)
    if not design or "/" in design:
        raise ValueError(f"design entry '{entry}' must look like '<suite>/<design>'")
    return get_suite(suite_name), design


def list_designs(suite: str | Suite, lazagna_root: str) -> list[str]:
    """Design names in a suite, sorted. Helper files listed in Suite.exclude are skipped."""
    s = suite if isinstance(suite, Suite) else get_suite(suite)
    root = s.path(lazagna_root)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"suite '{s.name}' not found at {root} "
                                f"(is the benchmarks submodule checked out? `git submodule update --init benchmarks`)")
    names = []
    if s.per_design_dirs:
        for d in os.listdir(root):
            if os.path.isfile(os.path.join(root, d, d + s.ext)):
                names.append(d)
    else:
        for f in os.listdir(root):
            stem, ext = os.path.splitext(f)
            if ext == s.ext and os.path.isfile(os.path.join(root, f)):
                names.append(stem)
    return sorted(n for n in names if n not in s.exclude)


def expand(entries: Iterable[str], lazagna_root: str) -> list[str]:
    """Expand 'suite' / 'suite/*' to every design in the suite; check 'suite/design' entries.
    Keeps order and drops duplicates."""
    out: list[str] = []
    for e in entries:
        e = e.strip()
        if not e:
            continue
        name, _, design = e.partition("/")
        if design in ("", "*"):
            items = [f"{name}/{d}" for d in list_designs(name, lazagna_root)]
        else:
            s, _ = parse_entry(e)
            if design_files(e, lazagna_root)[s.fmt] is None:
                raise FileNotFoundError(f"design '{e}' not found in {s.path(lazagna_root)}")
            items = [e]
        for i in items:
            if i not in out:
                out.append(i)
    return out


def design_files(entry: str, lazagna_root: str) -> dict:
    """Source files of one design: {"verilog": path|None, "blif": path|None, "act": path|None}.
    For a Verilog suite only "verilog" is set. For a BLIF suite, "blif" is set and "act" /
    "verilog" when the files exist next to it."""
    s, design = parse_entry(entry)
    base = os.path.join(s.path(lazagna_root), design) if s.per_design_dirs else s.path(lazagna_root)

    def f(ext):
        p = os.path.join(base, design + ext)
        return p if os.path.isfile(p) else None

    if s.is_verilog:
        return {VERILOG: f(".v"), BLIF: None, "act": None}
    return {VERILOG: f(".v"), BLIF: f(".blif"), "act": f(".act")}


def is_verilog_entry(entry: str) -> bool:
    return parse_entry(entry)[0].is_verilog


def stage_design(entry: str, lazagna_root: str, work_dir: str, prefix: str = "",
                 refresh: bool = False) -> str:
    """Copy one design into <work_dir>/bench/<prefix><design>/ and return that directory.

    The flow and the fast flow both expect a directory holding exactly ONE design, and the
    benchmarks/ tree inside the container is read-only, which is why designs are staged.
    Verilog: <design>.v only. BLIF: <design>.blif plus its .act and .v when present (the BLIF
    flow reads all three). Copies go through a unique temp name + os.replace, so concurrent
    workers staging the same design never see a partial file. Existing copies are kept
    unless refresh=True."""
    s, design = parse_entry(entry)
    files = design_files(entry, lazagna_root)
    main = files[s.fmt]
    if main is None:
        base = os.path.join(s.path(lazagna_root), design) if s.per_design_dirs else s.path(lazagna_root)
        raise FileNotFoundError(f"benchmark source missing: {os.path.join(base, design + s.ext)}")
    out_dir = os.path.join(work_dir, "bench", prefix + design)
    os.makedirs(out_dir, exist_ok=True)
    srcs = [main] if s.is_verilog else [p for p in (files[BLIF], files["act"], files[VERILOG]) if p]
    for src in srcs:
        dst = os.path.join(out_dir, os.path.basename(src))
        if os.path.exists(dst) and not refresh:
            continue
        tmp = f"{dst}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        shutil.copy(src, tmp)
        os.replace(tmp, dst)
    return out_dir


def describe(lazagna_root: Optional[str] = None) -> str:
    """One line per suite (name, format, directory, design count if the submodule is present)."""
    lines = []
    for s in SUITES.values():
        n = ""
        if lazagna_root:
            try:
                n = f"{len(list_designs(s, lazagna_root))} designs"
            except FileNotFoundError:
                n = "missing"
        lines.append(f"{s.name:<15} {s.fmt:<8} {s.directory:<32} {n:<12} {s.description}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LAZAGNA_ROOT", os.path.dirname(os.path.abspath(__file__)))
    print(describe(root))
