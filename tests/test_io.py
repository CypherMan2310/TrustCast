"""Atomic directory replacement."""

import numpy as np
import xarray as xr

from trustcast.io import replace_dir, write_zarr_atomic


def test_write_zarr_atomic_replaces_existing(tmp_path):
    dest = tmp_path / "a.zarr"
    write_zarr_atomic(xr.Dataset({"x": ("t", np.arange(3.0))}), dest)
    write_zarr_atomic(xr.Dataset({"x": ("t", np.arange(5.0))}), dest)
    assert xr.open_zarr(dest, consolidated=False).sizes["t"] == 5
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.zarr"]  # no tmp/old leftovers


def test_replace_dir_moves_into_new_location(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("new")
    replace_dir(src, tmp_path / "nested_dest")
    assert (tmp_path / "nested_dest" / "f.txt").read_text() == "new"
