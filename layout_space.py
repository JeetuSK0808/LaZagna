from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

CLB = "clb"
DSP = "dsp"
BRAM = "bram"
IO = "io"

def _blank(layers: int, height: int, width: int) -> list[list[list[str]]]:
    return [[["" for _ in range(width)] for _ in range(height)] for _ in range(layers)]

def _stamp_perimeter(grid: list[list[list[str]]]) -> None:

    for layer in grid:
        h = len(layer)
        w = len(layer[0])
        for x in range(w):
            layer[0][x] = IO
            layer[h - 1][x] = IO
        for y in range(h):
            layer[y][0] = IO
            layer[y][w - 1] = IO

def _fill_interior(grid: list[list[list[str]]], block_for: Callable[[int, int, int], str]) -> None:

    for li, layer in enumerate(grid):
        h = len(layer)
        w = len(layer[0])
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                layer[y][x] = block_for(li, x, y)

@dataclass
class LayoutSpec:
    """
    The reduced design space the optimizer actually searches over. Each field maps
    to one of the paper's axes of variation, so a sampled LayoutSpec is a concrete
    point that may or may not coincide with one of the 7 named layouts.

    family:        "distributed" or "edge"   (the two clusters the paper found)
    hb_period:     for distributed layouts, columns between hard-block columns
    edge_fraction: for edge layouts, fraction of width given to the hard-block band
    asymmetry:     0.0 = layers identical, 1.0 = fully separated (All-Top style)
    separate_dsp_bram: True puts DSP and BRAM on different layers (Iso-Edge style)
    """
    family: str = "distributed"
    hb_period: int = 8
    edge_fraction: float = 0.25
    asymmetry: float = 0.0
    separate_dsp_bram: bool = False

    def build(self, width: int, height: int) -> list[list[list[str]]]:
        if self.family == "distributed":
            grid = self._build_distributed(width, height)
        elif self.family == "edge":
            grid = self._build_edge(width, height)
        else:
            raise ValueError(f"unknown family '{self.family}'")
        _stamp_perimeter(grid)
        return grid

    def _build_distributed(self, width: int, height: int) -> list[list[list[str]]]:
        grid = _blank(2, height, width)
        period = max(2, self.hb_period)

        all_top = self.asymmetry >= 0.999
        shift = int(round(self.asymmetry * (period // 2)))

        def block_for(layer: int, x: int, y: int) -> str:
            if layer == 1 and all_top:
                return CLB
            col = x + (shift if layer == 1 else 0)
            if col % period == 0:

                if self.separate_dsp_bram:
                    return DSP if layer == 0 else BRAM
                return DSP if (y % 2 == 0) else BRAM
            return CLB

        _fill_interior(grid, block_for)
        return grid

    def _build_edge(self, width: int, height: int) -> list[list[list[str]]]:
        grid = _blank(2, height, width)
        band = max(1, int(round(self.edge_fraction * width)))
        left_edge = range(1, 1 + band)
        right_edge = range(width - 1 - band, width - 1)

        def block_for(layer: int, x: int, y: int) -> str:

            in_left = x in left_edge
            in_right = x in right_edge
            mine = in_left if layer == 0 else in_right
            theirs = in_right if layer == 0 else in_left
            in_band = mine or (theirs and self.asymmetry < 0.5)
            if not in_band:
                return CLB
            if self.separate_dsp_bram:

                return DSP if layer == 0 else BRAM

            return DSP if (y % 2 == 0) else BRAM

        _fill_interior(grid, block_for)
        return grid

@dataclass
class ColumnLayoutSpec:
    columns: list[list[str]]

    def build(self, width: int, height: int) -> list[list[list[str]]]:
        n_interior = width - 2
        if len(self.columns) != 2 or any(len(c) != n_interior for c in self.columns):
            raise ValueError(f"need 2 layers x {n_interior} interior columns")
        grid = _blank(2, height, width)

        def block_for(layer: int, x: int, y: int) -> str:
            return self.columns[layer][x - 1]

        _fill_interior(grid, block_for)
        _stamp_perimeter(grid)
        return grid


NAMED_LAYOUTS: dict[str, LayoutSpec] = {
    "aligned":  LayoutSpec(family="distributed", hb_period=8, asymmetry=0.0),
    "offset":   LayoutSpec(family="distributed", hb_period=8, asymmetry=0.25),
    "all_top":  LayoutSpec(family="distributed", hb_period=4, asymmetry=1.0),
    "striped":  LayoutSpec(family="distributed", hb_period=8, asymmetry=0.5, separate_dsp_bram=True),
    "border":   LayoutSpec(family="edge", edge_fraction=0.125, asymmetry=0.6),
    "mix_edge": LayoutSpec(family="edge", edge_fraction=0.25, asymmetry=0.0),
    "iso_edge": LayoutSpec(family="edge", edge_fraction=0.25, asymmetry=0.0, separate_dsp_bram=True),
}

def summarize(grid: list[list[list[str]]]) -> dict[str, int]:

    counts: dict[str, int] = {}
    for layer in grid:
        for row in layer:
            for cell in row:
                if cell:
                    counts[cell] = counts.get(cell, 0) + 1
    return counts

if __name__ == "__main__":
    for name, spec in NAMED_LAYOUTS.items():
        g = spec.build(width=12, height=12)
        print(f"{name:9s} {summarize(g)}")
