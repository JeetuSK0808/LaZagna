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
├── benchmarks/           # Benchmark circuits (BLIF and Verilog)
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
└── requirements.txt      # Python dependencies
```

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
