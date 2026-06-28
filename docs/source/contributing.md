# Contributing

We welcome contributions to LaZagna! Here's how you can help.

## Reporting Issues

If you find a bug or have a feature request, please open an issue on the [GitHub repository](https://github.com/IY2002/LaZagna/issues).

## Development Setup

1. Fork and clone the repository
2. Follow the [Installation](installation.md) guide
3. Create a new branch for your feature or fix

```bash
git checkout -b feature/my-new-feature
```

## Code Structure

The main source code is in the `lazagna/` package:

| Module | Description |
|--------|-------------|
| `main.py` | Entry point and CLI argument parsing |
| `yaml_file_processing.py` | YAML configuration parsing and parameter sweep generation |
| `arch_xml_modification.py` | VTR architecture XML file modification |
| `csv_locations_generator.py` | CSV-based switch box location pattern generation |
| `file_handling.py` | File I/O utilities |
| `run_flow.py` | OpenFPGA/VPR flow execution |
| `run_interface.py` | Interface for running experiments |
| `script_editing.py` | OpenFPGA script template editing |
| `split_top_module.py` | Top module splitting for 3D designs |
| `printing.py` | Output formatting utilities |

## Submitting Changes

1. Ensure your code follows the existing style
2. Test your changes with the example setup files
3. Submit a pull request with a clear description of the changes

## License

LaZagna is licensed under the [MIT License](https://github.com/IY2002/LaZagna/blob/main/LICENSE). By contributing, you agree that your contributions will be licensed under the same license.
