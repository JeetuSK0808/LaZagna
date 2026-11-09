# LaZagna: 3D FPGA Architecture Exploration Tool <img src="./images/LaZagna_logo.png" alt="Logo" width="100" style="vertical-align:middle; ">

LaZagna is an open-source tool for designing and evaluating **3D FPGA architectures**. It supports customizable vertical interconnects, layer heterogeneity, and switch block patterns. LaZagna generates synthesizable RTL and bitstreams through a modified version of [OpenFPGA](https://github.com/lnis-uofu/OpenFPGA), enabling full 3D FPGA architectural exploration from high-level specs to physical design.

---
## Documentation
LaZagna's [documentation website](https://lazagna.readthedocs.io/en/latest/) describes how to use and build the tool. 

---

## Table of Contents

- [Installation](#installation)
- [Building](#building)
- [Quick Start](#quick-start)
- [Setup Files](#setup-files)
  - [Minimal Example](#minimal-example)
  - [Configuration Sections](#configuration-sections)
  - [Defaults](#defaults)
  - [Sweeping Parameters](#sweeping-parameters)
  - [Path Placeholders](#path-placeholders)
- [Configuration Reference](#configuration-reference)
  - [experiment_name](#experiment_name)
  - [grid](#grid)
  - [architectures](#architectures)
  - [benchmarks](#benchmarks)
  - [placement](#placement)
  - [seeds](#seeds)
  - [switch_block_3d](#switch_block_3d)
  - [interlayer_delay](#interlayer_delay)
  - [advanced](#advanced)
- [Example Configurations](#example-configurations)
- [Running LaZagna](#running-lazagna)
- [Output Structure](#output-structure)
- [Directory Structure](#directory-structure)
- [Design-Space Search Across Benchmarks, and SHAP Importance](#design-space-search-across-benchmarks-and-shap-importance)
  - [Quick start for a multi-benchmark study](#quick-start-for-a-multi-benchmark-study)
- [Cleaning Up](#cleaning-up)
- [License](#license)

---

## Installation

Ensure you have all system and Python dependencies installed:

```bash
make prereqs
pip install -r requirements.txt
```

## Building

Build the project (this compiles the OpenFPGA toolchain):

```bash
make all
```

For faster builds, use the `-j` flag:

```bash
make all -j8   # Uses 8 cores
```

---

## Quick Start

1. **Build** the project (one-time):
   ```bash
   make all -j4
   ```

2. **Run** a simple test:
   ```bash
   python3 lazagna/main.py -f setup_files/simple_test.yaml -v
   ```

3. **Check results** in the `results/` and `tasks_run/` directories.

The simple test runs a small `and2_or2` benchmark on a 10×10 3D FPGA grid with default settings — it should complete in under a minute.

---

## Setup Files

LaZagna is driven by **YAML setup files** that describe what experiments to run. The setup files live in `setup_files/` and are organized into intuitive, hierarchical sections.

### Minimal Example

The only **required** field is `experiment_name`. Everything else falls back to defaults:

```yaml
experiment_name: "my_first_run"
```

This will run a single experiment with a 10×10 grid, `3d_sb` architecture, `and2_or2` benchmarks, and all default switch-block / delay settings.

### A More Typical Example

```yaml
experiment_name: "delay_sweep"

grid:
  width_3d: 25
  height_3d: 25
  channel_width: 100

benchmarks:
  directory: "{lazagna_root}/benchmarks/ITD_quick"
  is_verilog: true

interlayer_delay:
  delay_ratio: [0.5, 1.0, 2.0, 5.0]
```

This sweeps 4 vertical delay ratios on a 25×25 grid with Verilog benchmarks — only 13 lines instead of 50+.

### Defaults

Every parameter has a sensible default defined in [`setup_files/defaults.yaml`](setup_files/defaults.yaml). Your setup file is **merged on top of** the defaults — you only need to include what's different. Defaults are well-commented and serve as a reference for all available options.

### Sweeping Parameters

Any parameter written as a **list** `[]` is automatically swept (Cartesian product with other swept parameters):

```yaml
# Single value — fixed across all runs:
placement:
  algorithm: "cube_bb"

# List — swept (each value produces a separate run):
placement:
  algorithm: ["cube_bb", "per_layer_bb"]
```

Some parameters are **linked** — they sweep together rather than as a Cartesian product:
- `architectures` entries (each `type` + `arch_file` pair is one run)
- `switch_block_3d.custom_patterns` entries (each `input` + `output` pair is one run)
- `switch_block_3d.location_pattern` + `grid_csv_path` (each location + its CSV is one run)
- `seeds` (each seed is one run)

### Path Placeholders

Use `{lazagna_root}` to reference paths relative to the LaZagna installation directory:

```yaml
benchmarks:
  directory: "{lazagna_root}/benchmarks/ITD_quick"
```

This resolves to the absolute path of your LaZagna install at runtime.

---

## Configuration Reference

### `experiment_name`

| | |
|---|---|
| **Required** | ✅ Yes |
| **Type** | string |
| **Description** | A unique name for this experiment. Used in output directory names. |

```yaml
experiment_name: "my_experiment"
```

---

### `grid`

FPGA fabric dimensions and routing channel width.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `width_3d` | int | `10` | 3D FPGA grid width (columns) |
| `height_3d` | int | `10` | 3D FPGA grid height (rows) |
| `width_2d` | int | `15` | 2D-equivalent grid width (used when architecture type is `2d`) |
| `height_2d` | int | `15` | 2D-equivalent grid height |
| `channel_width` | int | `50` | Routing channel width |

```yaml
grid:
  width_3d: 25
  height_3d: 25
  width_2d: 35
  height_2d: 35
  channel_width: 100
```

> **Note:** The 2D dimensions are used automatically when the architecture type is `2d`. Typically the 2D grid is larger (since two 3D layers are flattened into one), but this is not enforced.

---

### `architectures`

A list of FPGA architecture types to evaluate. Each entry is tested as a separate run.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `type` | string | `"3d_sb"` | Architecture / switch-block type |
| `arch_file` | string | *(auto)* | Override the default architecture XML for this type |

**Available types:**

| Type | Description | Default Arch File |
|---|---|---|
| `3d_sb` | 3D SB with full vertical routing | `vtr_arch_dsp_bram.xml` |
| `3d_cb` | 3D connection block only | `vtr_3d_cb_arch_dsp_bram.xml` |
| `3d_cb_out_only` | 3D connection block (output only) | `vtr_3d_cb_out_only_arch_dsp_bram.xml` |
| `hybrid_cb` | Hybrid: CB + partial SB | `vtr_3d_cb_arch_dsp_bram.xml` |
| `hybrid_cb_out_only` | Hybrid: CB output + partial SB | `vtr_3d_cb_out_only_arch_dsp_bram.xml` |
| `2d` | 2D baseline (no vertical connections) | `vtr_3d_cb_arch_dsp_bram.xml` |

```yaml
# Simple — use default arch file:
architectures:
  - type: 3d_sb

# Multiple types to compare:
architectures:
  - type: 3d_sb
  - type: 3d_cb
  - type: 2d

# Override an arch file for one type:
architectures:
  - type: 3d_sb
    arch_file: "{lazagna_root}/arch_files/my_custom_arch.xml"
```

---

### `benchmarks`

Which benchmarks to run through the FPGA flow.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `directory` | string | `"{lazagna_root}/benchmarks/and2_or2"` | Path to the benchmark directory |
| `is_verilog` | bool | `false` | `true` = Verilog (`.v`) benchmarks, `false` = BLIF (`.blif`) benchmarks |

```yaml
# BLIF benchmarks (MCNC-style):
benchmarks:
  directory: "{lazagna_root}/benchmarks/and2_or2"
  is_verilog: false

# Verilog benchmarks (Koios/ITD):
benchmarks:
  directory: "{lazagna_root}/benchmarks/ITD_quick"
  is_verilog: true
```

#### Benchmark suites

Instead of a directory, you can name a suite from the `benchmarks/` submodule (`python3 benchmark_suites.py` lists them with their design counts):

| Suite | Format | Directory |
|---|---|---|
| `koios` | Verilog | `benchmarks/koios` (its `*_include.v` helpers are skipped) |
| `koios_proxy` | Verilog | `benchmarks/koios_proxy` |
| `vtr` | Verilog | `benchmarks/VTR_benchmarks` |
| `mcnc` | BLIF + `.act` | `benchmarks/MCNC_benchmarks` (one folder per design) |
| `itd_paper`, `itd_subset`, `itd_quick` | Verilog | `benchmarks/ITD_paper`, `ITD_subset`, `ITD_quick` |
| `eltwise`, `dsp_bram_tests` | Verilog | small single-purpose sets |
| `and2_or2`, `des` | BLIF | single small designs |

With `suite`, `is_verilog` comes from the suite. `designs` runs only some of a suite's (or a directory's) designs, and names a missing design as an error. A **list** of entries is swept like `architectures`: each entry is its own run, and with more than one entry the entry's suite name is added to the run identifier, so the same design name in two suites never overwrites the other.

```yaml
# Every VTR design:
benchmarks:
  suite: vtr

# Two MCNC designs only:
benchmarks:
  suite: mcnc
  designs: [clma, s38417]

# Several suites in one experiment:
benchmarks:
  - suite: vtr
  - suite: mcnc
    designs: [clma]
  - directory: "{lazagna_root}/benchmarks/ITD_quick"
    is_verilog: true
```

From Python: `BenchmarkOptions.from_suite("vtr")`, `BenchmarkOptions.from_suite("mcnc", ["clma"])`, and `ExperimentOptions(benchmarks=[...])` for several entries.

---

### `placement`

Controls the VPR placement algorithm.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `algorithm` | string or list | `["cube_bb"]` | Placement cost function. List = sweep. |

**Options:** `"cube_bb"`, `"per_layer_bb"`

```yaml
# Sweep two algorithms:
placement:
  algorithm: ["cube_bb", "per_layer_bb"]
```

---

### `seeds`

Controls random seed behaviour for reproducibility.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mode` | string | `"fixed"` | `"fixed"` = one deterministic seed; `"random"` = generate N random seeds |
| `value` | int | `1` | In fixed mode: the seed value. In random mode: number of seeds to generate. |

```yaml
# Fixed seed (deterministic):
seeds:
  mode: fixed
  value: 42

# 5 random seeds:
seeds:
  mode: random
  value: 5
```

---

### `switch_block_3d`

Configuration for 3D (vertical) switch blocks.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `connectivity` | float or list | `[1]` | Fraction of vertical connections (0–1). List = sweep. |
| `connection_type` | string or list | `["subset"]` | SB wiring pattern: `"subset"` or `"custom"`. List = sweep. |
| `switch_name` | string | `"3D_SB_switch"` | Name of the 3D SB switch in the architecture XML |
| `segment_name` | string | `"3D_SB_connection"` | Name of the 3D SB routing segment in the architecture XML |
| `input_pattern` | list of int | `[]` | Custom input turn pattern `[N, E, S, W]` (used with `connection_type: custom`) |
| `output_pattern` | list of int | `[]` | Custom output turn pattern `[N, E, S, W]` |
| `location_pattern` | string or list | `["repeated_interval"]` | Where to place 3D SBs: `"repeated_interval"`, `"random"`, or `"custom"` |
| `grid_csv_path` | string or list | `""` | CSV file(s) for custom SB placement (required with `location_pattern: "custom"`) |
| `custom_patterns` | list | *(none)* | Multiple input/output patterns to sweep (see below) |

#### Custom Turn Patterns

When `connection_type` is `"custom"`, you can define multiple turn patterns. Each `input`/`output` pair is a 4-element list representing turn offsets for `[North, East, South, West]`:

```yaml
switch_block_3d:
  connection_type: ["custom"]
  custom_patterns:
    - input:  [0, 0, 0, 0]     # subset
      output: [0, 0, 0, 0]
    - input:  [0, 1, 2, 3]     # wilton
      output: [0, 1, 2, 3]
    - input:  [0, 0, 0, 0]     # offset
      output: [1, 1, 1, 1]
```

#### Custom SB Placement

Use a CSV file to control exactly which grid tiles get 3D switch blocks:

```yaml
switch_block_3d:
  location_pattern: ["custom"]
  grid_csv_path: ["{lazagna_root}/setup_files/csv_patterns/rows_10x10_pattern.csv"]
```

#### Connectivity Sweep

```yaml
switch_block_3d:
  connectivity: [1, 0.66, 0.33]
```

---

### `interlayer_delay`

Controls the delay characteristics of vertical (inter-layer) connections.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `vertical_connectivity` | int | `1` | Number of vertical connections per switch block |
| `delay_ratio` | float or list | `[0.739]` | Ratio of vertical-to-horizontal delay. List = sweep. |
| `base_delay_switch` | string | `"L4_driver"` | Reference switch whose delay is used for scaling |
| `update_arch_delay` | bool | `true` | Whether to update the arch XML with scaled delays |
| `switch_pairs` | dict | *(see default)* | Mapping from base switch name → inter-layer switch name |

```yaml
# Sweep delay ratios to study inter-layer delay impact:
interlayer_delay:
  delay_ratio: [0.5, 1.0, 2.0, 3.0, 5.0]
```

Default `switch_pairs`:
```yaml
switch_pairs:
  L4_driver: "L4_inter_layer_driver"
  L16_driver: "L16_inter_layer_driver"
  ipin_cblock: "ipin_inter_layer_cblock"
```

---

### `advanced`

Catch-all for expert options.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `additional_vpr_options` | string | `""` | Extra CLI flags passed directly to VPR (e.g. `"--inner_num 0.5"`) |

```yaml
advanced:
  additional_vpr_options: "--inner_num 0.5"
```

---

## Example Configurations

Ready-to-use examples in `setup_files/`:

| File | What it tests | Key parameters changed |
|---|---|---|
| [`simple_test.yaml`](setup_files/simple_test.yaml) | Basic sanity check | *(all defaults)* |
| [`connectivity_type_test.yaml`](setup_files/connectivity_type_test.yaml) | All 6 architecture types | `architectures` |
| [`sb_percentage_test.yaml`](setup_files/sb_percentage_test.yaml) | Vertical connectivity sweep | `switch_block_3d.connectivity: [1, 0.66, 0.33]` |
| [`sb_pattern_test.yaml`](setup_files/sb_pattern_test.yaml) | Custom turn patterns | `switch_block_3d.custom_patterns` |
| [`verilog_benchmark_test.yaml`](setup_files/verilog_benchmark_test.yaml) | Large Verilog benchmarks | `grid`, `benchmarks` |
| [`sb_locations_test.yaml`](setup_files/sb_locations_test.yaml) | Custom SB placement from CSV | `switch_block_3d.location_pattern` |
| [`vertical_delay_test.yaml`](setup_files/vertical_delay_test.yaml) | Delay ratio sweep | `interlayer_delay.delay_ratio: [0.5–5.0]` |
| [`multi_suite_test.yaml`](setup_files/multi_suite_test.yaml) | Designs from two suites in one experiment | `benchmarks` (list of suites) |

---

## Running LaZagna

```bash
python3 lazagna/main.py -f <path_to_setup_file> [options]
```

| Flag | Description |
|---|---|
| `-f`, `--yaml_file` | **(required)** Path to the YAML setup file |
| `-v`, `--verbose` | Enable verbose output |
| `-j`, `--num_workers` | Number of parallel experiment workers (default: 1) |
| `-n`, `--num_task_workers` | Number of parallel benchmark workers per experiment (default: 1) |

**Examples:**

```bash
# Simple run:
python3 lazagna/main.py -f setup_files/simple_test.yaml

# Verbose with parallelism:
python3 lazagna/main.py -f setup_files/verilog_benchmark_test.yaml -v -j 4 -n 8
```

> **Tip:** Total CPU cores used = `num_workers` × `num_task_workers`. For a 32-core machine, try `-j 4 -n 8`.

---

## Output Structure

LaZagna generates two types of output:

```
LaZagna/
├── results/                      # Aggregated CSV results
│   └── 3d_<type>_cw_<params>/   # One folder per configuration
│       └── <benchmark>_results_*.csv
│
└── tasks_run/                    # Detailed per-run outputs
    └── 3d_<type>_cw_<params>_<timestamp>/
        └── task_<benchmark>/    # Generated RTL, logs, route/place files
```

- **`results/`** — CSV files with placement and routing metrics for each benchmark. Use these for analysis.
- **`tasks_run/`** — Full task outputs including generated RTL, bitstreams, timing reports, and OpenFPGA logs. Useful for debugging.

---

## Directory Structure

```
LaZagna/
├── arch_files/           # Architecture XML files (generated and templates)
│   └── templates/        # Base architecture templates
├── benchmarks/           # Benchmark circuits (BLIF and Verilog), see benchmark_suites.py
├── benchmark_suites.py   # Registry of the benchmark suites (koios, vtr, mcnc, ...)
├── lazagna_shap.py       # SHAP importance of search parameters (optional analysis)
├── lazagna_pareto.py     # Pareto front (CPD vs WL gain) of a search, with its champion
├── docs/                 # Documentation (Sphinx/ReadTheDocs)
├── images/               # Logos and figures
├── lazagna/              # Core Python source code
│   ├── main.py           # Entry point
│   ├── yaml_file_processing_v2.py  # YAML config parser
│   ├── run_interface.py  # Orchestrates benchmark runs
│   ├── run_flow.py       # OpenFPGA task execution
│   ├── arch_xml_modification.py    # Architecture XML manipulation
│   ├── script_editing.py # OpenFPGA script generation
│   └── file_handling.py  # File utilities
├── OpenFPGA/             # OpenFPGA submodule (built during make)
├── results/              # Output: aggregated CSV results
├── scripts/              # Utility scripts (RRG creation, analysis)
├── setup_files/          # Experiment configuration
│   ├── defaults.yaml     # Default values for all parameters
│   ├── *.yaml            # Example setup files
│   └── csv_patterns/     # Custom SB placement grids
├── task/                 # OpenFPGA task templates
├── tasks_run/            # Output: detailed per-run results
├── makefile              # Build targets
├── requirements.txt      # Python dependencies
└── requirements-analysis.txt  # Optional: scikit-learn + shap for lazagna_shap.py
```

---

## Design-Space Search Across Benchmarks, and SHAP Importance

**Searching for one architecture across many designs.** `lazagna_optuna.SearchConfig` normally searches for one design (`benchmark_dir`). Setting `benchmarks` (e.g. `("koios/eltwise_layer", "vtr/stereovision1", "mcnc/clma")`, or `("vtr",)` for a whole suite) makes every trial evaluate its architecture on each design, each on its own autosized device and against its own reference. The objective becomes the geometric mean of the per-design CPD and wirelength ratios, as % improvement, and the per-design numbers are kept in each trial's `per_design` user attribute. It supports the `layout`, `connectivity` and `structured` search modes. In `structured` mode the layer-0 hard-block shares are sampled as fractions (`dsp_frac_l0`, `bram_frac_l0`), so a trial means the same arrangement on every device size.

**Optimizers.** `SearchConfig.sampler` picks Optuna's sampler: `tpe` (default), `nsga2`, `nsga3`, `random`, or `qmc` (a Sobol sequence; needs scipy). An unknown name is an error. CMA-ES is not offered, because Optuna's CMA-ES sampler handles only one objective.

**Priorities.** By default a search has two objectives, CPD gain and wirelength gain, and finds their Pareto front. `objective_weights=(w_cpd, w_wl)` turns them into one weighted objective, e.g. `(1, 0)` for CPD only. `link_penalty=p` charges vertical links: `p` percentage points come off each gain at full 3D connectivity, in proportion to the share of switch blocks with vertical links. Both are off by default, and then the objective is unchanged.

**Vertical links.** In the multi-benchmark search, `connectivity_choices` is the share of switch blocks that are 3D and `vertical_connectivity_choices` the share of each 3D switch block's channels that cross the layers (structured and layout modes). With more than one value, each is sampled. A trial's vertical links are their product, `link_fraction` (1 = full 3D). `links_objective=True` makes the links a third objective, so the search finds the front of CPD gain, WL gain and links; it cannot be combined with `objective_weights` or `link_penalty`. Such a study gets two champions: **best**, the front point with the highest CPD + WL gain, and **lean**, the same among front points with links at most `CHAMPION_MAX_LINKS` (default 0.1). Its report shows the front sorted by links and plots WL and CPD gain against links. `nsga_population` sets the population of the `nsga2` and `nsga3` samplers (default 50). They draw their first generation at random, so with fewer trials than the population they are a random search. All of these are off by default.

**Anchors.** `anchors=True` (structured mode) queues known layouts as the first trials, once per study, however many workers share it: `even_split`, `split_types` (DSP on layer 0, BRAM on layer 1), `split_rev`, `hb_top`, `hb_one_layer`, and `recommended` (split_types with 10% of the channels crossing, the study's recommended architecture; only when 0.1 is a vertical-connectivity choice). `split_types` and `recommended` have exactly the columns of the study's runs, on every study device. The others keep the per-layer column counts of the study's layouts but not their positions, which the structured parameters cannot express (`lazagna_optuna.ANCHORS` explains why). `even_split` is therefore not the reference layout: its gain shows the seed noise, not exactly 0.

**Placement vs routing.** Routed multi-benchmark runs also keep VPR's placement estimates of the same runs, for every trial and reference. The report compares them with the routed gains: Spearman ρ, the mean offset, and the trials whose rank changes most. This shows how far a cheaper `FIDELITY=place` search can be trusted on these designs.

**Which parameters matter.** `lazagna_shap.py` explains a finished study. It fits a gradient-boosted tree surrogate from the trial parameters to a target (default `cpd_impr_pct` and `wl_impr_pct`), then reports each parameter's mean |SHAP| value in the target's units, its share, its spread over repeated fits, and its direction. Every table also carries the surrogate's cross-validated R², so a weak fit is visible. For a CSV of runs over several designs, `--group-col design` adds a second R² with whole designs held out. It needs `pip install -r requirements-analysis.txt`.

```bash
python3 lazagna_shap.py --journal campaign_work/<run>/journal/<study>.log --study <study> --out shap_out
python3 lazagna_shap.py --storage sqlite:///lazagna_clma_conn.db --study lazagna_clma_conn
python3 lazagna_shap.py --csv runs.csv --target cpd_gain --features cluster,stagger
```

For the fixed-configuration study, `campaign/shap_study.py` builds one table of every routed run (`docs/study/study_runs.csv`) and its SHAP view, written up in [`docs/study/shap_study.md`](docs/study/shap_study.md).

**Pareto fronts.** `lazagna_pareto.py` writes the Pareto front of a study (CPD gain vs WL gain) as a CSV, a table and a plot, with the champion marked. The champion is the front point with the highest `w_cpd` x CPD gain + `w_wl` x WL gain, with weights (1, 1) unless the study was run with others. For a study with links as a third objective, it uses the three-objective front and marks the best and lean champions (`--max-links` sets the lean budget).

```bash
python3 lazagna_pareto.py --journal campaign_work/<run>/journal/<study>.log --study <study> --out pareto_out
```

`campaign/analyze_optuna.py` adds the same SHAP table next to its Spearman table when these packages are installed, and writes a full report for each multi-benchmark study (below). On PACE, optuna is only in the container, so run these there, e.g. `apptainer exec --no-home --cleanenv -B "$PWD:/code" lazagna.sif python3 /code/lazagna_pareto.py --journal /code/campaign_work/<run>/journal/<study>.log --study <study> --out /code/pareto_out`.

### Quick start for a multi-benchmark study

On PACE, from a login node, in the repo directory that holds `lazagna.sif`:

```bash
git pull
bash campaign/suite_study.sh
```

That is the whole setup: the Python comes from the checkout through the container binds, so no image rebuild is needed (the image is only built if `lazagna.sif` is missing). The script submits 8 search jobs that share one Optuna study and a report job that runs after them. The defaults are 40 completed trials, the structured hard-block layout search, TPE, 3 seeds and routed results, on `koios/attention_layer`, `vtr/stereovision1` and `koios/tpu_like.small.os`, the designs of the single-design structured searches. Everything lands in one file:

```
campaign_work/<study>_<time>/<study>_<time>_results.tar.gz
  analysis/<study>/report.md      Pareto front, champion (per design), Spearman, SHAP, top trials,
                                  placement vs routing (routed runs)
  analysis/<study>/pareto.{png,csv,md}, shap*.{png,csv,md}, trials.csv
  analysis/<study>/tasks_champion.jsonl   5-seed check of the champion(s) on every design
  journal/<study>.log             the Optuna study (every trial and its per-design results)
  designs.json, suite_study.env, logs/
```

Pick the designs, optimizer, priorities and budget with environment variables:

```bash
DESIGNS="koios/eltwise_layer vtr/stereovision1 mcnc/clma" SAMPLER=nsga2 TRIALS=60 N_WORKERS=8 \
    bash campaign/suite_study.sh
WEIGHTS=0.7,0.3 LINK_PENALTY=2 CONN_CHOICES="0.25 0.5 1.0" bash campaign/suite_study.sh
DRY_RUN=1 bash campaign/suite_study.sh      # print the sbatch commands only
```

The recommended next run is a routed search over hard-block layout and vertical links. It runs on three designs where layout matters (type-dedicated layers gained +2.9 to +5.8% WL on them at 10 seeds in the study) and starts from the known layouts:

```bash
DESIGNS="koios/tpu_like.small.ws vtr/mkDelayWorker32B vtr/stereovision2" TRIALS=64 ANCHORS=1 LINKS_OBJECTIVE=1 \
    CONN_CHOICES="0.25 0.5 1.0" VCONN_CHOICES="0.05 0.1 0.25 0.5 1.0" bash campaign/suite_study.sh
```

The study's 10-seed layout confirmations for these designs (`docs/study/tables.md`) and its recommended-architecture runs are a direct check on the anchors. Settings: `VCONN_CHOICES` (vertical connectivity values), `LINKS_OBJECTIVE=1` (links as a third objective), `CHAMPION_MAX_LINKS` (the lean champion's budget, default 0.1), `ANCHORS=1`, `NSGA_POP` (NSGA population).

The header of `campaign/suite_study.sh` lists every setting. SHAP needs scikit-learn and shap. If the image lacks them, the report job installs them once into `campaign_work/pyextras`, outside the image. If that fails, or with `INSTALL_EXTRAS=0`, the report is written without the SHAP tables. To check the champion at 5 seeds, run its task file with `experiment.sbatch`, e.g. in the study dir: `sbatch -A <acct> --array=0-5 --export=ALL,WORK_ROOT=$PWD/campaign_work/study,TASKS=$PWD/campaign_work/study/tasks/tasks_champion.jsonl experiment.sbatch` (copy `tasks_champion.jsonl` to `campaign_work/study/tasks/` first; set `--array` to the number of lines minus one).

---

## Cleaning Up

```bash
# Remove generated output files (results, tasks_run, rrg, arch_files)
make clean_files

# Clean OpenFPGA build
make clean_openfpga

# Clean everything
make clean_all
```

---

## License

This project is licensed under the MIT License.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Copyright (c) 2025 Ismael Youssef

See the [LICENSE](./LICENSE) file for full license details.
