# YAML Configuration Guide

LaZagna uses YAML configuration files to define all parameters for 3D FPGA architecture generation and exploration. This guide covers every configuration option in detail, with examples.

## Key Concepts

### Defaults

Every parameter has a sensible default defined in `setup_files/defaults.yaml`. Your setup file is **merged on top of** the defaults — you only need to include what's different.

The only **required** field is `experiment_name`.

### Sweeping Parameters

Any parameter written as a **list** `[]` is automatically swept (Cartesian product with other swept parameters):

```yaml
# Fixed — same value for every run:
placement:
  algorithm: "cube_bb"

# Swept — each value produces a separate run:
placement:
  algorithm: ["cube_bb", "per_layer_bb"]
```

### Linked Parameters

Some parameters must vary **together** rather than as a Cartesian product:

- `architectures` entries — each `type` + `arch_file` pair is one run
- `switch_block_3d.custom_patterns` — each `input` + `output` pair is one run
- `switch_block_3d.location_pattern` + `grid_csv_path` — each location + its CSV is one run
- `seeds` — each seed is one run

### Path Placeholders

Use `{lazagna_root}` to reference paths relative to the LaZagna installation directory:

```yaml
benchmarks:
  directory: "{lazagna_root}/benchmarks/ITD_quick"
```

This resolves to the absolute path of your LaZagna install at runtime.

---

## Quick Start

To run LaZagna with a configuration file:

```bash
python3 lazagna/main.py -f <path_to_setup_file>
```

Add `-v` for verbose output. See the `setup_files/` directory for ready-to-use example configurations.

### Minimal Setup File

```yaml
experiment_name: "my_first_run"
```

This is a complete, valid setup file — everything else uses defaults (10×10 grid, `combined` architecture, `and2_or2` benchmarks).

---

## Configuration Sections

The YAML file is organized into hierarchical sections:

```
experiment_name          (required — unique name for this run)
├── grid                 (FPGA dimensions & channel width)
├── architectures        (architecture types to evaluate)
├── benchmarks           (benchmark circuits)
├── placement            (VPR placement algorithm)
├── seeds                (random seed configuration)
├── switch_block_3d      (3D switch block settings)
├── interlayer_delay      (vertical connection delay)
└── advanced             (extra VPR options)
```

---

## Complete Reference

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
|-----------|------|---------|-------------|
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

:::{note}
When the architecture type is `2d`, the `width_2d` and `height_2d` values override `width_3d` and `height_3d` automatically. Typically the 2D grid is larger (two 3D layers flattened into one), but this is not enforced.
:::

---

### `architectures`

A list of FPGA architecture types to evaluate. Each entry is tested as a separate run (linked parameter).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | `"combined"` | Architecture / switch-block type |
| `arch_file` | string | *(auto)* | Override the default architecture XML for this type |

#### Available Types

| Type | Description | Default Arch File |
|------|-------------|-------------------|
| `combined` | 3D SB with full vertical routing | `vtr_arch_dsp_bram.xml` |
| `3d_cb` | 3D connection block only | `vtr_3d_cb_arch_dsp_bram.xml` |
| `3d_cb_out_only` | 3D connection block (output only) | `vtr_3d_cb_out_only_arch_dsp_bram.xml` |
| `hybrid_cb` | Hybrid: CB + partial SB | `vtr_3d_cb_arch_dsp_bram.xml` |
| `hybrid_cb_out_only` | Hybrid: CB output + partial SB | `vtr_3d_cb_out_only_arch_dsp_bram.xml` |
| `2d` | 2D baseline (no vertical connections) | `vtr_3d_cb_arch_dsp_bram.xml` |

All default arch files are under `arch_files/templates/dsp_bram/`.

```yaml
# Simple — use default arch file for one type:
architectures:
  - type: combined

# Sweep multiple architecture types:
architectures:
  - type: combined
  - type: 3d_cb
  - type: 2d

# Override an arch file for a specific type:
architectures:
  - type: combined
    arch_file: "{lazagna_root}/arch_files/my_custom_arch.xml"
```

:::{tip}
You no longer need to remember arch file paths — just specify the `type` and the correct default file is chosen automatically. Use `arch_file` only when you have a custom architecture XML.
:::

---

### `benchmarks`

Which benchmark circuits to run through the FPGA flow.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
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

:::{note}
For Verilog benchmarks, LaZagna will run Yosys for synthesis before VPR. Set `is_verilog: true` and point to a directory containing `.v` files.
:::

---

### `placement`

Controls the VPR placement algorithm.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `algorithm` | string or list | `["cube_bb"]` | Placement cost function. List = sweep. |

**Options:** `"cube_bb"`, `"per_layer_bb"`

```yaml
# Single algorithm:
placement:
  algorithm: "cube_bb"

# Sweep two algorithms:
placement:
  algorithm: ["cube_bb", "per_layer_bb"]
```

---

### `seeds`

Controls random seed behaviour for reproducibility.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | string | `"fixed"` | `"fixed"` = one deterministic seed; `"random"` = generate N random seeds |
| `value` | int | `1` | In fixed mode: the seed value. In random mode: number of seeds to generate. |

```yaml
# Deterministic single run:
seeds:
  mode: fixed
  value: 42

# 5 random seeds for statistical analysis:
seeds:
  mode: random
  value: 5
```

---

### `switch_block_3d`

Configuration for 3D (vertical) switch blocks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `connectivity` | float or list | `[1]` | Fraction of vertical connections (0–1). List = sweep. |
| `connection_type` | string or list | `["subset"]` | SB wiring pattern: `"subset"` or `"custom"`. List = sweep. |
| `switch_name` | string | `"3D_SB_switch"` | Name of the 3D SB switch in the architecture XML |
| `segment_name` | string | `"3D_SB_connection"` | Name of the 3D SB routing segment in the architecture XML |
| `input_pattern` | list of int | `[]` | Custom input turn pattern `[N, E, S, W]` (used with `connection_type: custom`) |
| `output_pattern` | list of int | `[]` | Custom output turn pattern `[N, E, S, W]` |
| `location_pattern` | string or list | `["repeated_interval"]` | Where to place 3D SBs |
| `grid_csv_path` | string or list | `""` | CSV file(s) for custom SB placement (required with `location_pattern: "custom"`) |
| `custom_patterns` | list | *(none)* | Multiple input/output patterns to sweep (see below) |

#### Connectivity Sweep

```yaml
switch_block_3d:
  connectivity: [1, 0.66, 0.33]
```

#### Custom Turn Patterns

When `connection_type` is `"custom"`, you can define multiple turn patterns. Each `input`/`output` pair is a 4-element list representing turn offsets for `[North, East, South, West]`:

```yaml
switch_block_3d:
  connection_type: ["custom"]
  custom_patterns:
    - input:  [0, 0, 0, 0]     # subset
      output: [0, 0, 0, 0]
    - input:  [0, 1, 2, 3]     # wilton variant 1
      output: [0, 1, 2, 3]
    - input:  [0, 0, 0, 0]     # wilton variant 2
      output: [0, 1, 2, 3]
    - input:  [0, 0, 0, 0]     # offset
      output: [1, 1, 1, 1]
```

:::{note}
Each pattern pair is tested as a linked parameter — they are not crossed with each other.
:::

#### SB Location Patterns

Controls **where** 3D switch boxes are placed on the FPGA grid.

| Pattern | Description |
|---------|-------------|
| `"repeated_interval"` | 3D SBs placed at regular intervals across the grid |
| `"random"` | 3D SBs placed randomly |
| `"custom"` | User-defined placement via a CSV file |

```yaml
# Built-in pattern:
switch_block_3d:
  location_pattern: ["repeated_interval"]

# Custom CSV placement:
switch_block_3d:
  location_pattern: ["custom"]
  grid_csv_path: ["{lazagna_root}/setup_files/csv_patterns/rows_10x10_pattern.csv"]
```

##### CSV Pattern Format

When using `"custom"`, provide a CSV file where:
- **`X`** marks a 3D switch box location
- **`O`** marks a regular 2D switch box location

Example CSV patterns are available in `setup_files/csv_patterns/`.

---

### `interlayer_delay`

Controls the delay characteristics of vertical (inter-layer) connections.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vertical_connectivity` | int | `1` | Number of vertical connections per switch block |
| `delay_ratio` | float or list | `[0.739]` | Ratio of vertical-to-horizontal delay. List = sweep. |
| `base_delay_switch` | string | `"L4_driver"` | Reference switch whose delay is used for scaling |
| `update_arch_delay` | bool | `true` | Whether to update the arch XML with scaled delays |
| `switch_pairs` | dict | *(see below)* | Mapping from base switch name → inter-layer switch name |

```yaml
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

:::{tip}
Sweep across delay ratios to explore the impact of vertical interconnect delay: `delay_ratio: [0.5, 1.0, 2.0, 3.0, 4.0, 5.0]`
:::

---

### `advanced`

Catch-all for expert options.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `additional_vpr_options` | string | `""` | Extra CLI flags passed directly to VPR |

```yaml
advanced:
  additional_vpr_options: "--inner_num 0.5"
```

---

## Parameter Sweeping

LaZagna automatically generates all combinations of parameters specified as lists. This is a powerful feature for design space exploration.

### Independent Parameters

Parameters specified as lists are swept as a **Cartesian product**:

```yaml
switch_block_3d:
  connectivity: [1, 0.66, 0.33]

placement:
  algorithm: ["cube_bb", "per_layer_bb"]

interlayer_delay:
  delay_ratio: [0.5, 1.0, 2.0]
```

This generates $3 \times 2 \times 3 = 18$ combinations.

### Linked Parameters

Some parameters vary together. They are **not** crossed with each other — each entry is one run:

- **Architectures**: each `type` + `arch_file` pair
- **Custom patterns**: each `input` + `output` pair
- **Location + CSV**: each `location_pattern` + `grid_csv_path`
- **Seeds**: each seed value

### Automatic Filtering

LaZagna automatically filters out invalid combinations:

- `"2d"`, `"3d_cb"`, and `"3d_cb_out_only"` types are only valid with `connection_type: "subset"`
- `"2d"` type only works with `placement.algorithm: "cube_bb"`
- `"2d"`, `"3d_cb"`, and `"3d_cb_out_only"` types require `connectivity: 1.0`

---

## Complete Example

Here is a full configuration file showing all sections with explicit values:

```yaml
experiment_name: "full_example"

grid:
  width_3d: 10
  height_3d: 10
  width_2d: 15
  height_2d: 15
  channel_width: 50

architectures:
  - type: combined

benchmarks:
  directory: "{lazagna_root}/benchmarks/and2_or2"
  is_verilog: false

placement:
  algorithm: ["cube_bb"]

seeds:
  mode: fixed
  value: 1

switch_block_3d:
  connectivity: [1]
  connection_type: ["subset"]
  switch_name: "3D_SB_switch"
  segment_name: "3D_SB_connection"
  input_pattern: []
  output_pattern: []
  location_pattern: ["repeated_interval"]
  grid_csv_path: ""

interlayer_delay:
  vertical_connectivity: 1
  delay_ratio: [0.739]
  base_delay_switch: "L4_driver"
  update_arch_delay: true
  switch_pairs:
    L4_driver: "L4_inter_layer_driver"
    L16_driver: "L16_inter_layer_driver"
    ipin_cblock: "ipin_inter_layer_cblock"

advanced:
  additional_vpr_options: ""
```

Remember — you **never** need to write all of this. Thanks to the defaults system, the equivalent minimal version is:

```yaml
experiment_name: "full_example"
```
