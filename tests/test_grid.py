"""IMD grid definitions and region subsetting."""

import numpy as np
import pytest

from trustcast.config import load_config
from trustcast.grid.imd_grid import IMD_RAIN_0P25, IMD_TEMP_1P0, RegularGrid, flatten_points


def test_imd_rain_grid_matches_imd_spec():
    assert IMD_RAIN_0P25.lats[0] == 6.5 and IMD_RAIN_0P25.lats[-1] == 38.5
    assert IMD_RAIN_0P25.lons[0] == 66.5 and IMD_RAIN_0P25.lons[-1] == 100.0
    assert IMD_RAIN_0P25.lats.size == 129 and IMD_RAIN_0P25.lons.size == 135


def test_imd_temp_grid_matches_imd_spec():
    assert IMD_TEMP_1P0.lats[[0, -1]].tolist() == [7.5, 37.5]
    assert IMD_TEMP_1P0.lons[[0, -1]].tolist() == [67.5, 97.5]


def test_config_grid_is_the_imd_grid():
    assert RegularGrid.from_config(load_config().grid) == IMD_RAIN_0P25


def test_pilot_regions_sizes():
    cfg = load_config()
    lats, lons = IMD_RAIN_0P25.region_points(cfg.regions["rain_pilot"])
    assert (lats.size, lons.size) == (21, 13)
    lats, lons = IMD_RAIN_0P25.region_points(cfg.regions["heat_pilot"])
    assert (lats.size, lons.size) == (13, 13)


def test_subset_is_inclusive():
    lats, lons = IMD_RAIN_0P25.subset((10.0, 10.5), (76.0, 76.25))
    assert lats.tolist() == [10.0, 10.25, 10.5]
    assert lons.tolist() == [76.0, 76.25]


@pytest.mark.parametrize("bad", [(10.1, 10.5), (5.0, 6.5), (38.5, 39.0)])
def test_off_grid_bounds_raise(bad):
    with pytest.raises(ValueError):
        IMD_RAIN_0P25.subset(bad, (76.0, 76.25))


def test_flatten_is_row_major():
    la, lo = flatten_points(np.array([1.0, 2.0]), np.array([10.0, 20.0, 30.0]))
    assert la.tolist() == [1, 1, 1, 2, 2, 2]
    assert lo.tolist() == [10, 20, 30, 10, 20, 30]
