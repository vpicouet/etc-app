"""bake_spectra.py — read CSV/TXT/FITS spectra/atm/sky from generic-etc/data and emit data/spectra.json.

Produces a single JSON resampled on common wavelength grids:
  spectra (continuum SEDs):  λ = 80..1100 nm, 4000 points, log-uniform-ish... actually plain linear.
  atm transmission:          same grid as spectra
  sky emission lines:        λ = 100..400 nm, 8000 points (finer because lines are narrow)

The web app then linearly interpolates each curve onto the detector's spectral pixel grid.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import numpy as np

DATA = Path("/Users/Vincent/Github/generic-etc/data")
OUT  = Path("/Users/Vincent/Github/etc-app/data/spectra.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

# ---------- common grids ----------
GRID_MIN_NM, GRID_MAX_NM, GRID_N = 80.0, 1100.0, 4000     # general SED grid
SKY_MIN_NM,  SKY_MAX_NM,  SKY_N  = 100.0, 400.0,  8000    # sky lines grid (finer)

grid    = np.linspace(GRID_MIN_NM, GRID_MAX_NM, GRID_N)
skygrid = np.linspace(SKY_MIN_NM,  SKY_MAX_NM,  SKY_N)

def resample(wave_nm, flux, target):
    """Linear interp, zeros outside the input range."""
    wave_nm = np.asarray(wave_nm, float); flux = np.asarray(flux, float)
    ok = np.isfinite(wave_nm) & np.isfinite(flux)
    wave_nm, flux = wave_nm[ok], flux[ok]
    if wave_nm.size < 2:
        return np.zeros_like(target)
    order = np.argsort(wave_nm)
    wave_nm, flux = wave_nm[order], flux[order]
    out = np.interp(target, wave_nm, flux, left=0.0, right=0.0)
    return out

def normalize(arr):
    m = float(np.nanmax(np.abs(arr)))
    return arr / m if m > 0 else arr

def round_arr(arr, decimals=6):
    """Return a Python list with rounded floats (smaller JSON)."""
    return [float(f"{v:.{decimals}g}") for v in arr]

# ---------- 1. Atmosphere transmission ----------
print("--- Atmosphere ---")
atm_curves = {}
try:
    # 1a. pwv_atm_combined_ground.csv: wave_microns, transmission
    p = DATA / "Atm_transmission/pwv_atm_combined_ground.csv"
    import csv as _csv
    with open(p) as f:
        rdr = _csv.DictReader(f)
        rows = list(rdr)
    wave_nm = np.array([float(r["wave_microns"])*1000 for r in rows])
    trans   = np.array([float(r["transmission"])      for r in rows])
    out = resample(wave_nm, trans, grid)
    atm_curves["pwv_kpno (ground)"] = round_arr(out, 5)
    print(f"  pwv_kpno: native {wave_nm.size} → {grid.size}")
except Exception as e:
    print(f"  pwv_kpno: SKIP ({e})")

# 1b. transmission_ground.csv (smaller alt)
try:
    p = DATA / "Atm_transmission/transmission_ground.csv"
    with open(p) as f:
        rdr = _csv.reader(f)
        rows = list(rdr)
    hdr = rows[0]
    arr = np.array(rows[1:], dtype=float)
    wave_col = 0 if "wave" in hdr[0].lower() or "lam" in hdr[0].lower() else 0
    # Guess units: if < 50, microns; if < 10000, nm; else Å
    wmean = float(np.nanmedian(arr[:, wave_col]))
    if wmean < 50:
        wave_nm = arr[:,wave_col] * 1000
    elif wmean < 10000:
        wave_nm = arr[:,wave_col]
    else:
        wave_nm = arr[:,wave_col] / 10
    trans = arr[:, 1]
    out = resample(wave_nm, trans, grid)
    atm_curves["transmission_ground"] = round_arr(out, 5)
    print(f"  transmission_ground: {arr.shape[0]} → {grid.size}")
except Exception as e:
    print(f"  transmission_ground: SKIP ({e})")

# ---------- 2. Sky emission lines ----------
print("--- Sky lines ---")
sky_curves = {}
try:
    p = DATA / "Sky_emission_lines/spectra_0.2A.csv"
    with open(p) as f:
        rdr = _csv.reader(f)
        rows = list(rdr)
    hdr = rows[0]
    arr = np.array(rows[1:], dtype=float)
    # wavelength is in Å, flux in arbitrary units
    wave_nm = arr[:,0] / 10
    flux    = arr[:,1]
    out = resample(wave_nm, flux, skygrid)
    sky_curves["spectra_0.2A"] = round_arr(normalize(out), 4)
    print(f"  spectra_0.2A: {arr.shape[0]} → {skygrid.size}")
except Exception as e:
    print(f"  spectra_0.2A: SKIP ({e})")

# UV-specific sky lines
try:
    p = DATA / "Sky_emission_lines/UV_atm_lines.csv"
    with open(p) as f:
        rdr = _csv.reader(f)
        rows = list(rdr)
    hdr = rows[0]
    arr = np.array(rows[1:], dtype=float)
    # nm, counts
    wave_nm = arr[:,0]
    flux = arr[:,1]
    out = resample(wave_nm, flux, skygrid)
    sky_curves["UV_atm_lines"] = round_arr(normalize(out), 4)
    print(f"  UV_atm_lines: {arr.shape[0]} → {skygrid.size}")
except Exception as e:
    print(f"  UV_atm_lines: SKIP ({e})")

# ---------- 3. Source spectra ----------
print("--- Source spectra ---")
spectra = {}

# 3a. FITS files in data/Spectra/ — h_*fos_spc.fits
print("  FITS:")
try:
    from astropy.io import fits
    for f in sorted((DATA/"Spectra").glob("h_*fos_spc.fits")):
        name = f.stem.replace("h_","").replace("fos_spc","").rstrip("_")
        try:
            with fits.open(f) as hdul:
                # The HST FOS standard layout: data table in HDU 1, cols WAVELENGTH (Å), FLUX
                d = hdul[1].data
                if d is None or d.size == 0:
                    print(f"    SKIP {f.name}: no data")
                    continue
                cols = [c.lower() for c in d.dtype.names]
                wcol = next((c for c in d.dtype.names if "wave" in c.lower() or "lam" in c.lower()), d.dtype.names[0])
                fcol = next((c for c in d.dtype.names if "flux" in c.lower()), d.dtype.names[1])
                wave_A = np.asarray(d[wcol]).ravel()
                flux   = np.asarray(d[fcol]).ravel()
                # Some FOS files are 2D (n_rows × n_samples per row)
                if wave_A.ndim != 1:
                    wave_A = wave_A.ravel()
                    flux   = flux.ravel()
                wave_nm = wave_A / 10
                out = resample(wave_nm, flux, grid)
                spectra[f"QSO: {name}"] = round_arr(normalize(out), 4)
                print(f"    {name}: ok")
        except Exception as e:
            print(f"    SKIP {f.name}: {e}")
except ImportError:
    print("    astropy not installed → SKIP all FITS")

# 3b. TXT files in QSO_SALVATO2015 and GAL_COSMOS_SED
print("  TXT (QSO Salvato):")
for f in sorted((DATA/"Spectra/QSO_SALVATO2015").glob("*.txt")):
    if "list" in f.name.lower(): continue
    try:
        arr = np.loadtxt(f)
        if arr.ndim != 2 or arr.shape[1] < 2: continue
        wave_nm = arr[:,0]   # already in nm (file starts at 100)
        flux    = arr[:,1]
        out = resample(wave_nm, flux, grid)
        spectra[f"QSO Salvato: {f.stem}"] = round_arr(normalize(out), 4)
        print(f"    {f.stem}: ok ({arr.shape[0]} pts)")
    except Exception as e:
        print(f"    SKIP {f.name}: {e}")

print("  TXT (GAL COSMOS):")
for f in sorted((DATA/"Spectra/GAL_COSMOS_SED").glob("*.txt")):
    if "list" in f.name.lower(): continue
    try:
        arr = np.loadtxt(f)
        if arr.ndim != 2 or arr.shape[1] < 2: continue
        wave_nm = arr[:,0]
        flux    = arr[:,1]
        out = resample(wave_nm, flux, grid)
        spectra[f"GAL COSMOS: {f.stem}"] = round_arr(normalize(out), 4)
        print(f"    {f.stem}: ok ({arr.shape[0]} pts)")
    except Exception as e:
        print(f"    SKIP {f.name}: {e}")

# 3c. STAR_LAGET
print("  TXT (STAR Laget):")
for f in sorted((DATA/"Spectra/STAR_LAGET").glob("*.txt")):
    if "list" in f.name.lower(): continue
    try:
        arr = np.loadtxt(f)
        if arr.ndim != 2 or arr.shape[1] < 2: continue
        wave_nm = arr[:,0]
        flux    = arr[:,1]
        out = resample(wave_nm, flux, grid)
        spectra[f"Star: {f.stem}"] = round_arr(normalize(out), 4)
        print(f"    {f.stem}: ok ({arr.shape[0]} pts)")
    except Exception as e:
        print(f"    SKIP {f.name}: {e}")

# ---------- Emit JSON ----------
payload = {
    "grid": {"min_nm": GRID_MIN_NM, "max_nm": GRID_MAX_NM, "n": GRID_N},
    "sky_grid": {"min_nm": SKY_MIN_NM, "max_nm": SKY_MAX_NM, "n": SKY_N},
    "atm": atm_curves,
    "sky_lines": sky_curves,
    "spectra": spectra,
}

with open(OUT, "w") as f:
    json.dump(payload, f, separators=(",",":"))
size = OUT.stat().st_size
print(f"\nSaved {OUT}  ({size/1024:.1f} KB)")
print(f"  {len(spectra)} spectra, {len(atm_curves)} atm, {len(sky_curves)} sky lines")
