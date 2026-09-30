"""Per-run manifests: what was fetched, where it is, and hashes to prove it is intact."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from trustcast.config import REPO_ROOT
from trustcast.grid.schema import SchemaError, validate_archive

MANIFEST_SCHEMA = "trustcast.manifest.v1"


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def array_digest(values: np.ndarray) -> str:
    """Hex SHA-256 of an array as C-ordered float32 with canonical NaNs."""
    a = np.ascontiguousarray(values, dtype=np.float32).copy()
    a[np.isnan(a)] = np.nan
    return hashlib.sha256(a.tobytes()).hexdigest()


def git_version() -> str:
    """Current git commit (with ``-dirty``), or ``unknown``."""
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def write_raw(payload: dict[str, Any], path: Path) -> None:
    """Write a raw payload as deterministic gzip JSON (mtime fixed to 0)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    with path.open("wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
        gz.write(body)


def variable_summary(ds: xr.Dataset) -> dict[str, dict[str, Any]]:
    """Per-variable dtype, shape, NaN fraction, range and digest."""
    out: dict[str, dict[str, Any]] = {}
    for name, da in ds.data_vars.items():
        v = da.values
        finite = v[np.isfinite(v)]
        out[str(name)] = {
            "dtype": str(da.dtype),
            "shape": list(v.shape),
            "nan_fraction": round(float(np.isnan(v).mean()), 6),
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
            "sha256": array_digest(v),
        }
    return out


def build_manifest(
    *,
    ds: xr.Dataset,
    raw_path: Path,
    zarr_path: Path,
    data_root: Path,
    request: dict[str, Any],
    duration_s: float,
) -> dict[str, Any]:
    """Assemble the manifest dict for one archived run."""
    return {
        "schema": MANIFEST_SCHEMA,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "code_version": git_version(),
        "source": ds.attrs["source"],
        "provider": ds.attrs.get("provider"),
        "model_id": ds.attrs.get("model_id"),
        "licence": ds.attrs["licence"],
        "region": ds.attrs.get("region"),
        "init_time": ds.attrs.get("init_time"),
        "fetched_at": ds.attrs["fetched_at"],
        "bbox": {
            "lat": [float(ds.lat.min()), float(ds.lat.max())],
            "lon": [float(ds.lon.min()), float(ds.lon.max())],
        },
        "request": request,
        "duration_s": round(duration_s, 2),
        "raw": {
            "path": raw_path.relative_to(data_root).as_posix(),
            "sha256": sha256_file(raw_path),
            "bytes": raw_path.stat().st_size,
        },
        "processed": {
            "path": zarr_path.relative_to(data_root).as_posix(),
            "schema": ds.attrs["schema"],
            "dims": {k: int(v) for k, v in ds.sizes.items()},
            "variables": variable_summary(ds),
        },
    }


def verify_manifest(manifest_path: Path, data_root: Path) -> list[str]:
    """Re-check a manifest against disk. Returns a list of problems (empty = verified)."""
    problems: list[str] = []
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    if m.get("schema") != MANIFEST_SCHEMA:
        return [f"unknown manifest schema {m.get('schema')!r}"]
    raw = data_root / m["raw"]["path"]
    if not raw.exists():
        problems.append(f"raw file missing: {raw}")
    elif sha256_file(raw) != m["raw"]["sha256"]:
        problems.append("raw sha256 mismatch")
    else:
        try:
            with gzip.open(raw, "rb") as f:
                payload = json.loads(f.read())
            if payload.get("init_time") != m["init_time"]:
                problems.append("raw payload init_time differs from manifest")
        except (OSError, ValueError) as e:
            problems.append(f"raw file unreadable: {e}")
    zp = data_root / m["processed"]["path"]
    if not zp.exists():
        return [*problems, f"processed store missing: {zp}"]
    try:
        with xr.open_zarr(zp, consolidated=False) as ds:
            ds = ds.load()
    except Exception as e:  # any zarr/xarray failure means the store is unusable
        return [*problems, f"processed store unreadable: {e}"]
    try:
        validate_archive(ds)
    except SchemaError as e:
        problems.append(str(e))
    if {k: int(v) for k, v in ds.sizes.items()} != m["processed"]["dims"]:
        problems.append(f"dims {dict(ds.sizes)} != manifest {m['processed']['dims']}")
    for name, meta in m["processed"]["variables"].items():
        if name not in ds:
            problems.append(f"variable {name} missing from store")
        elif array_digest(ds[name].values) != meta["sha256"]:
            problems.append(f"variable {name} digest mismatch")
    return problems
