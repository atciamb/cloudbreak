"""Landability map: a grid of ground classes built from imagery. Runs on the laptop.

Unknown ground is never treated as usable. Only cells with positive evidence
of usable ground count. Georeferencing and the imagery-to-grid step come later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Cell(IntEnum):
    UNKNOWN = 0
    USABLE = 1
    OBSTACLE = 2
    PERSON = 3
    WATER = 4


@dataclass
class LandabilityGrid:
    cell_size_m: float
    cells: list[list[Cell]]

    @classmethod
    def unknown(cls, rows: int, cols: int, cell_size_m: float) -> LandabilityGrid:
        """A grid with no evidence yet: every cell UNKNOWN."""
        return cls(cell_size_m, [[Cell.UNKNOWN] * cols for _ in range(rows)])

    def is_usable(self, row: int, col: int) -> bool:
        return self.cells[row][col] is Cell.USABLE
