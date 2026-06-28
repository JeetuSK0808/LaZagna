# Usage

## Running LaZagna

Execute LaZagna with a YAML configuration file:

```bash
python3 lazagna/main.py -f <path_to_setup_file>
```

### Command-Line Options

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--yaml_file` | `-f` | Path to the YAML setup file **(required)** | — |
| `--verbose` | `-v` | Enable verbose output | off |
| `--num_workers` | `-j` | Number of parallel experiment workers | `1` |
| `--num_task_workers` | `-n` | Number of parallel benchmark workers per experiment | `1` |

### Examples

```bash
# Simple run
python3 lazagna/main.py -f setup_files/simple_test.yaml

# Verbose with parallelism (total cores = -j × -n)
python3 lazagna/main.py -f setup_files/verilog_benchmark_test.yaml -v -j 4 -n 8
```

:::{tip}
Total CPU cores used = `num_workers` × `num_task_workers`. For a 32-core machine, try `-j 4 -n 8`.
:::

---

## Setup Files

LaZagna is configured entirely through **YAML setup files** organised into clear, hierarchical sections. Only `experiment_name` is required — everything else has sensible defaults defined in [`setup_files/defaults.yaml`](https://github.com/your-org/LaZagna/blob/main/setup_files/defaults.yaml).

See the [YAML Configuration Guide](yaml_configuration.md) for a complete reference of every parameter.

### Minimal Setup File

```yaml
experiment_name: "my_first_run"
```

This single line is a valid setup file. It will run a 10×10 grid, `combined` architecture, `and2_or2` benchmarks, and all default switch-block / delay settings.

### A More Typical Setup File

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

Only 13 lines — everything else comes from the defaults.

### Example Configurations

Ready-to-use examples in `setup_files/`:

| File | What it tests | Key parameters changed |
|------|---------------|------------------------|
| `simple_test.yaml` | Basic sanity check | *(all defaults)* |
| `connectivity_type_test.yaml` | All 6 architecture types | `architectures` |
| `sb_percentage_test.yaml` | Vertical connectivity sweep | `switch_block_3d.connectivity: [1, 0.66, 0.33]` |
| `sb_pattern_test.yaml` | Custom turn patterns | `switch_block_3d.custom_patterns` |
| `verilog_benchmark_test.yaml` | Large Verilog benchmarks | `grid`, `benchmarks` |
| `sb_locations_test.yaml` | Custom SB placement from CSV | `switch_block_3d.location_pattern` |
| `vertical_delay_test.yaml` | Delay ratio sweep | `interlayer_delay.delay_ratio: [0.5–5.0]` |

---

## Output Structure

LaZagna generates two types of output:

### `results/`

Contains CSV files with aggregated placement and routing results for each benchmark, making it easy to compare across parameter sweeps.

```
results/
└── 3d_<type>_cw_<params>/
    └── <benchmark>_results_*.csv
```

### `tasks_run/`

Contains the detailed results and generated RTL code for each parameter combination, including:

- Modified VTR architecture files
- VPR placement and routing results
- Timing reports
- OpenFPGA logs and generated configurations

```
tasks_run/
└── 3d_<type>_cw_<params>_<timestamp>/
    └── task_<benchmark>/
```

---

## Cleaning Up

```bash
# Remove output files (results, tasks_run, generated arch files, RRGs)
make clean_files

# Clean OpenFPGA build
make clean_openfpga

# Clean everything
make clean_all
```
