# About LaZagna

## Overview

**LaZagna** is the first open-source framework for **automated, end-to-end 3D FPGA architecture generation and evaluation**. It enables rapid exploration of 3D FPGA designs — from high-level architectural specification to synthesizable RTL and bitstream generation.

While 3D IC technology has been extensively explored for ASICs, its application to FPGAs remains limited. Existing studies on 3D FPGAs are often constrained to fixed prototypes, narrow architectural templates, and simulation-only evaluations. LaZagna fills this gap by providing a unified, scalable infrastructure for comprehensive 3D FPGA design space exploration.

```{figure} /_static/figures/overview_figure.png
:alt: LaZagna Tool Overview
:width: 100%
:align: center

**Figure 1:** Overview of the LaZagna tool workflow, showing the fabric generation flow and bitstream generation flow.
```

---

<!-- ## Key Contributions

1. **End-to-end RTL and bitstream generation for 3D FPGAs:** LaZagna is the first framework to generate both synthesizable RTL and programming bitstreams for custom 3D FPGA fabrics, enabling evaluation beyond simulation.

2. **Full-spectrum 3D architecture exploration:** LaZagna supports scalable exploration of a wide range of 3D architectural parameters — including layer count, resource partitioning, inter-layer connectivity, and routing granularity. It introduces novel vertical interconnect patterns, flexible 3D switch block designs, and logic heterogeneity across layers.

3. **Comprehensive case studies:** The framework has been validated through five representative case studies evaluating key architectural parameters and their impact on wirelength (WL), critical path delay (CPD), and routing runtime.

---

## Tool Workflow

LaZagna consists of two distinct flows:

### Fabric Generation Flow

This flow begins with a user-defined description of the target 3D FPGA architecture, specified via configurable input parameters (see the [YAML Configuration Guide](yaml_configuration.md)). Based on this description, LaZagna generates **synthesizable RTL** using a customized version of [OpenFPGA](https://github.com/lnis-uofu/OpenFPGA) with extended support for 3D integration. The RTL can then be passed through standard physical design steps (placement and routing) to produce a GDSII layout ready for fabrication with accurate PPA metrics.

### Bitstream Generation Flow

In this flow, benchmark circuits are mapped onto the generated 3D FPGA architecture using [VTR (Verilog-to-Routing)](https://verilogtorouting.org/). After benchmark placement and routing, key performance metrics such as wirelength and critical path delay are extracted. The routing results are then passed to the customized 3D-enabled OpenFPGA to generate a **programming bitstream** that configures the 3D FPGA.

---

## 3D FPGA Architectural Parameters

LaZagna accepts several architectural parameters that allow users to define custom 3D FPGA configurations. The table below summarizes all supported parameters:

| # | Parameter | Options |
|---|-----------|---------|
| 1 | **Vertical Connection Types** | 3D CB, 3D CB-O, 3D SB, 3D Hybrid, 3D Hybrid-O, User-Defined |
| 2 | **3D SB Percentage and Locations** | 0–100%, with patterns: Perimeter, Core, Rows, Columns, Repeated Interval, Random, Custom |
| 3 | **3D Switch Block Patterns** | Any two 4-integer combinations for input/output patterns |
| 4 | **Vertical Connection Delay Ratio** | Floating-point ratio between horizontal and vertical delay |
| 5 | **Layer Count and Heterogeneity** | Arbitrary layer count; Homogeneous, Non-Logic Heterogeneous, or Logic Heterogeneous |
| 6 | **Standard 2D FPGA Parameters** | Channel width, grid size, LUT size, segment length, etc. |

:::{tip}
Even with fixed 2D parameters, only two homogeneous layers, restricted SB pattern indices (-3 to 3), and only default placement patterns, there are over **1.7 billion unique 3D FPGA configurations** possible. When custom 3D SB placements are included, the design space grows to over **2¹³⁰** configurations!
:::

### Vertical Connection Types

Vertical connections determine how layers are interconnected and directly impact wirelength, critical path delay, and vertical via count and density.

```{figure} /_static/figures/3D_patterns.png
:alt: 3D Vertical Connection Types
:width: 100%
:align: center

**Figure 2:** Vertical connection types supported by LaZagna. Only connections from Layer 2 to Layer 1 are shown; reverse connections are implied.
```

LaZagna supports the following vertical connection types:

- **3D CB (Connection Block):** All input and output pins of grid elements (CLBs, IOs, DSPs, BRAMs) can connect across layers via vertical vias. This offers maximum routing flexibility but incurs a high vertical via count.

- **3D CB-O (Connection Block, Output-Only):** Cross-layer connectivity is restricted to output pins only. Nets only traverse layers at their source, reducing via usage.

- **3D SB (Switch Block):** Cross-layer connections are confined to switch blocks. Nets may change layers only at designated 3D SBs, localizing vertical vias to routing junctions.

- **3D Hybrid:** Combines 3D CB and 3D SB designs — allows cross-layer pin connections *and* SB-based crossings. Maximizes routing flexibility but has the highest via count.

- **3D Hybrid-O:** A variant of 3D Hybrid that restricts cross-layer connections to output pins only. Balances flexibility and via demand.

- **User-Defined:** Custom vertical connection strategies can be defined, such as input-only crossings or partial inter-layer connectivity on specific pins or SB tracks.

### 3D SB Placement Locations

LaZagna allows users to configure both the **percentage** and **spatial distribution** of 3D switch boxes across the FPGA grid.

```{figure} /_static/figures/SB_placements.png
:alt: 3D SB Placement Patterns
:width: 100%
:align: center

**Figure 3:** Supported 3D SB placement patterns.
```

Available placement patterns include:
- **Repeated Interval** — Evenly spaced across the grid
- **Rows** / **Columns** — Alternating row or column placement
- **Core** — Placed in the center of the FPGA, excluding the perimeter
- **Perimeter** — Placed along the edges only
- **Random** — Randomly distributed
- **Custom** — User-defined via CSV file

### 3D Switch Block Connection Patterns

To extend a traditional 2D switch block to 3D, vertical cross-layer routing tracks are added. A 3D SB can support up to six sides (four planar + above + below).

```{figure} /_static/figures/SB_patterns.png
:alt: 3D Switch Block Connection Patterns
:width: 100%
:align: center

**Figure 4:** Various 3D SB input and output patterns and their realization within the 3D SB structure.
```

Both input and output patterns are expressed as a sequence of four integers corresponding to the four planar sides in counter-clockwise order. Each integer indicates the starting track index on that side for vertical connectivity. For a switch block with channel width $W$ and output pattern $[i_0, i_1, i_2, i_3]$, the $k$-th output cross-layer track is driven by planar tracks at indices $(i_j + k) \bmod W$ on each side $j$.

### Vertical Connection Delay

```{figure} /_static/figures/Vertical_delay.png
:alt: Vertical Connection Delay
:width: 80%
:align: center

**Figure 5:** Vertical connection delay ratio concept.
```

This parameter specifies the delay cost of vertical interconnects relative to horizontal connections. Since LaZagna is technology-independent, users define a **delay ratio** that scales vertical connection delay with respect to a baseline switch (e.g., an L4 driver). Alternatively, absolute delay values can be specified.

### Layer Count and Heterogeneity

```{figure} /_static/figures/Layer_hetero.png
:alt: Layer Heterogeneity Options
:width: 60%
:align: center

**Figure 6:** Layer heterogeneity options supported by LaZagna.
```

LaZagna supports three types of layer configurations:

- **Homogeneous:** All layers share an identical layout, including logic blocks, routing components, and configuration memory.
- **Non-Logic Heterogeneous:** Logic blocks are placed on one layer, while other components (SBs, CBs, or configuration memory) are on separate layers.
- **Logic Heterogeneous:** Each layer contains a different combination of logic resources (CLBs, DSPs, BRAMs), while maintaining full routing capabilities.

--- -->

## Citation

If you use LaZagna in your research, please cite the ICCAD 2025 paper:

```bibtex
@inproceedings{lazagna2025,
  title={LaZagna: An Open-Source Framework for Automated 3D FPGA Architecture Generation and Evaluation},
  author={Youssef, Ismael and others},
  booktitle={Proceedings of the International Conference on Computer-Aided Design (ICCAD)},
  year={2025}
}
```

---

## Links

- **GitHub:** [https://github.com/IY2002/LaZagna](https://github.com/IY2002/LaZagna)
- **License:** [MIT License](https://github.com/IY2002/LaZagna/blob/main/LICENSE)
