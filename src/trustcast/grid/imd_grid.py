"""IMD target grids and bounding-box helpers.

IMD gridded rainfall is 0.25 deg on lat 6.5..38.5 N, lon 66.5..100.0 E (129 x 135).
IMD gridded Tmax/Tmin is 1.0 deg on lat 7.5..37.5 N, lon 67.5..97.5 E (31 x 31).
All TRUSTCAST forecast and truth products live on the 0.25 deg grid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trustcast.config import GridConfig, RegionConfig

_TOL = 1e-6


@dataclass(frozen=True)
class RegularGrid:
    """A regular lat/lon grid; coordinates are cell centres in degrees."""

    name: str
    lat0: float
    lon0: float
    step: float
    nlat: int
    nlon: int

    @classmethod
    def from_config(cls, g: GridConfig) -> RegularGrid:
        """Build from the ``grid`` block of the YAML config."""
        return cls(g.name, g.lat0, g.lon0, g.step, g.nlat, g.nlon)

    @property
    def lats(self) -> np.ndarray:
        """All latitudes, ascending."""
        return np.round(self.lat0 + self.step * np.arange(self.nlat), 6)

    @property
    def lons(self) -> np.ndarray:
        """All longitudes, ascending."""
        return np.round(self.lon0 + self.step * np.arange(self.nlon), 6)

    def _on_grid(self, value: float, origin: float, n: int) -> int:
        k = (value - origin) / self.step
        idx = round(k)
        if abs(k - idx) > _TOL or not 0 <= idx < n:
            raise ValueError(f"{value} is not a point of grid {self.name}")
        return idx

    def subset(
        self, lat: tuple[float, float], lon: tuple[float, float]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (lats, lons) of the grid points inside an inclusive bbox.

        Raises ``ValueError`` if a bound does not lie exactly on the grid, so that
        regions never silently shift by half a cell.
        """
        i0, i1 = (self._on_grid(v, self.lat0, self.nlat) for v in lat)
        j0, j1 = (self._on_grid(v, self.lon0, self.nlon) for v in lon)
        return self.lats[i0 : i1 + 1], self.lons[j0 : j1 + 1]

    def region_points(self, region: RegionConfig) -> tuple[np.ndarray, np.ndarray]:
        """Grid points of a configured region."""
        return self.subset(region.lat, region.lon)


IMD_RAIN_0P25 = RegularGrid("imd_0p25", 6.5, 66.5, 0.25, 129, 135)
IMD_TEMP_1P0 = RegularGrid("imd_1p0", 7.5, 67.5, 1.0, 31, 31)


def flatten_points(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row-major (lat outer, lon inner) flattening used for multi-point API requests."""
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    return la.ravel(), lo.ravel()
