from cloudbreak.landability import Cell, LandabilityGrid


def test_unknown_ground_is_not_usable():
    grid = LandabilityGrid.unknown(rows=3, cols=4, cell_size_m=2.0)
    assert not any(grid.is_usable(r, c) for r in range(3) for c in range(4))


def test_only_usable_cells_count():
    grid = LandabilityGrid.unknown(rows=1, cols=3, cell_size_m=2.0)
    grid.cells[0] = [Cell.USABLE, Cell.WATER, Cell.PERSON]
    assert [grid.is_usable(0, c) for c in range(3)] == [True, False, False]
