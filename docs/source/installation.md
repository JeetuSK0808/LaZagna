# Installation

## Prerequisites

- Python 3.8+
- A Linux-based operating system (tested on Ubuntu)
- Git

## Step 1: Clone the Repository

```bash
git clone https://github.com/IY2002/LaZagna.git
cd LaZagna
```

## Step 2: Install System Dependencies

LaZagna requires certain system packages. Install them with:

```bash
make prereqs
```

This runs the `install_apt_packages.sh` script which installs the necessary system-level dependencies.

## Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

The key Python dependencies include:

- `lxml` — XML processing for architecture files
- `numpy` — Numerical operations
- `Pillow` — Image processing
- `psutil` — System monitoring
- `PyYAML` — YAML configuration file parsing

## Step 4: Build OpenFPGA

Build the full project (including OpenFPGA) using:

```bash
make all
```

For faster build times, use parallel processing:

```bash
make all -j4  # Uses 4 cores
```

## Verifying the Installation

Run a simple test to verify everything is working:

```bash
python3 lazagna/main.py -f setup_files/simple_test.yaml -v
```

If the run completes without errors, your installation is successful.
