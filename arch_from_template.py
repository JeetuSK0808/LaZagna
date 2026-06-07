from __future__ import annotations
import re

from layout_space import LayoutSpec, CLB, DSP, BRAM, IO

BLOCK_NAME_MAP = {
    CLB: "clb",
    DSP: "complex_dsp",
    BRAM: "spram",
    IO: "io",
}

def _grid_to_layout_xml(grid: list[list[list[str]]], width: int, height: int,
                        layout_name: str = "generated") -> str:

    lines = ['  <layout tileable="false">']
    lines.append(f'    <fixed_layout name="{layout_name}" width="{width}" height="{height}">')
    for die_idx, layer in enumerate(grid):
        lines.append(f'      <layer die="{die_idx}">')
        lines.append('        <perimeter type="io" priority="100"/>')
        lines.append('        <corners type="EMPTY" priority="101"/>')
        lines.append('        <fill type="clb" priority="10"/>')
        h = len(layer)
        w = len(layer[0])
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                generic = layer[y][x]
                if not generic or generic == CLB:
                    continue
                mapped = BLOCK_NAME_MAP.get(generic)
                if mapped is None or mapped == "io":
                    continue
                lines.append(
                    f'        <single type="{mapped}" x="{x}" y="{y}" priority="20"/>'
                )
        lines.append('      </layer>')
    lines.append('    </fixed_layout>')
    lines.append('  </layout>')
    return "\n".join(lines)

def render_arch_from_template(template_path: str, spec: LayoutSpec,
                              width: int, height: int) -> str:
    """Read a template arch XML and return it with the <layout> block swapped."""
    with open(template_path) as f:
        xml = f.read()

    grid = spec.build(width, height)
    new_layout = _grid_to_layout_xml(grid, width, height)

    pattern = re.compile(r"[ \t]*<layout\b.*?</layout>", re.DOTALL)
    if not pattern.search(xml):
        raise ValueError(f"no <layout> block found in template {template_path}")
    return pattern.sub(new_layout, xml, count=1)

if __name__ == "__main__":

    import sys
    import xml.etree.ElementTree as ET
    from layout_space import NAMED_LAYOUTS

    template = sys.argv[1] if len(sys.argv) > 1 else (
        "arch_files/vtr_3d_cb_arch_dsp_bram_10x10_delay_ratio_0.739.xml"
    )
    for name, spec in NAMED_LAYOUTS.items():
        out = render_arch_from_template(template, spec, 10, 10)
        ET.fromstring(out)
        n_single = out.count("<single ")
        print(f"{name:9s} valid XML, {n_single} explicit block placements")
