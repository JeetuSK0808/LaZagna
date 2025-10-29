# LaZagna Configuration Guide
> ⚠️ **Note**: Under Development, new schema coming soon :construction_worker: :construction:

This document explains how to configure LaZagna using YAML files.

## Configuration Basics

LaZagna uses a YAML configuration file to define parameters for your FPGA fabric design. The system loads default values from `default_options.yaml` for any parameters not explicitly specified in your configuration.

## Parameters by Category

### FPGA Fabric Dimensions

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `width` | integer | Width of the 3D FPGA fabric | `50` |
| `height` | integer | Height of the 3D FPGA fabric | `50` |
| `width_2d` | integer | Width of 2D FPGA fabric (when comparing to 3D) | `70` |
| `height_2d` | integer | Height of 2D FPGA fabric (when comparing to 3D) | `70` |
| `channel_width` | integer | Channel width for the FPGA fabric (2D only) | `100` |

### 3D Connectivity Configuration

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `percent_connectivity` | list of integers | Percentage of switch boxes that are 3D | `[10, 20, 30]` |
| `connection_type` | list of strings | Pattern for 3D SBs (options: `subset`, `custom`) | `["subset"]` |
| `vertical_connectivity` | integer | Number of channels connecting vertically (not yet implemented) | `4` |

### Switch Box Configuration

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `sb_switch_name` | string | Switch in VTR architecture file for 3D SB interlayer connections | `3D_SB_switch` |
| `sb_segment_name` | string | Segment in VTR architecture file for 3D SB interlayer connections | `3D_SB_connection` |
| `sb_input_pattern` | list | Pattern defining 3D SB inputs | `[/path/to.]` |
| `sb_output_pattern` | list | Pattern defining 3D SB outputs | `[/path/to.]` |

### SB Location Pattern

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `sb_location_pattern` | list of strings | Pattern for SB locations. Options: `core`, `perimeter`, `rows`, `columns`, `repeated_interval`, `custom` | `["core"]` |
| `sb_grid_csv_path` | string | Path to CSV file defining custom SB patterns (required when using `custom` pattern) | `"patterns/custom_grid.csv"` |

### Delay Configuration

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `vertical_delay` | list of floats | Exact delay values for vertical connections (in seconds) | `[1e-9, 5e-9]` |
| `vertical_delay_ratio` | list of floats | Ratio of vertical to horizontal delay | `[1.0, 2.0]` |
| `base_delay_switch` | string | Switch name for calculating vertical delay ratio | `L4_driver` |
| `update_arch_delay` | boolean | Whether to modify vertical delays in the VTR architecture file | `true` |

### VTR/VPR Configuration

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `place_algorithm` | list of strings | 3D bounding box computation method (`cube_bb` or `per_layer_bb`) | `["cube_bb"]` |
| `linked_params` | object | Maps connection types to architecture files | See example below |
| `additional_vpr_options` | string | Extra VPR command-line options | `"--timing_analysis off"` |

### Benchmark Configuration

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `is_verilog_benchmarks` | boolean | Whether benchmarks are in Verilog (vs BLIF) format | `true` |
| `benchmarks_dir` | string | Directory containing benchmarks | `"/path/to/benchmarks/koios"` |

### Seed Configuration

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `num_seeds` | integer | Number of random seeds to test | `3` |
| `random_seed` | boolean | Whether to use random seeds for placement | `true` |
| `non_random_seed` | integer | Specific seed if not using random seeds | `1` |

## Examples

### Linked Parameters Example
```yaml
linked_params:
  type_sb_arch_mapping:
    - type_sb: "2d"
      arch_file: "/path/to/arch_files/templates/basic/vtr_2d_arch.xml"
    - type_sb: "3d_cb"
      arch_file: "/path/to/arch_files/templates/basic/vtr_3d_cb_arch.xml"
```
### Switch Interlayer Pairs Example
```yaml
switch_interlayer_pairs:
  L4_driver: "L4_inter_layer_driver"
  L16_driver: "L16_inter_layer_driver"
  ipin_cblock: "ipin_inter_layer_cblock"
```
## CSV Pattern Format

When using `custom` for the `sb_location_pattern`, provide a CSV file where:
- 'X' represents a 3D switch box location
- 'O' represents a 2D switch box location

Example patterns are available in the `csv_patterns` directory.
