# LaZagna: 3D FPGA Architecture Exploration Tool <img src="./images/LaZagna_logo.png" alt="Logo" width="100" style="vertical-align:middle; ">

> ⚠️ **Note**: Tutorials and documentation website are currently under development. :construction_worker: :construction:

LaZagna is an open-source tool for designing and evaluating 3D FPGA architectures. It supports customizable vertical interconnects, layer heterogeneity, and switch block patterns. LaZagna generates synthesizable RTL and bitstreams, enabling full architectural exploration from high-level specs to physical design.

## Table of Contents
- [Installation](#installation)
- [Building](#building)
- [Usage](#usage)
- [Directory Structure](#directory-structure)
- [Cleaning Up](#cleaning-up)
- [License](#license)

## Installation

Before building, ensure you have all the Python dependencies installed. You can do this using:

```bash
make prereqs
pip install -r requirements.txt
```

## Building

Build the project using make:
```bash
make all
```

For faster build times, use parallel processing with the -j flag:

```bash
make all -j4  # Uses 4 cores
```
# Usage
## Running LaZagna
Execute the tool using:

```bash
python3 lazagna/main.py -f <path_to_setup_file>
```

Optional flag:
    `-v`: Enable verbose output

## Setup Files
Configuration is done through setup files. See the `setup_files` directory for:

1. Setup file format
2. Available options
3. Example configurations

## Output Structure

LaZagna generates two types of output:

1. `tasks_run/`: Contains detailed results and generated RTL code
2. `results/`: CSV files with placement and routing results for each benchmark

## Cleaning Up
Clean specific outputs:

```bash

# Remove output files
make clean_files

# Clean OpenFPGA build
make clean_openfpga

# Clean everything
make clean
```

## Directory Structure
To Do

## License
This project is licensed under the MIT License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Copyright (c) 2025 Ismael Youssef

See the [LICENSE](./LICENSE) file for full license details.
