"""bake_spectra.py — resample source spectra, atmosphere & sky curves into a single JSON
that the web app loads at startup.

Input  : data/sources/   (CSVs and TXTs originally from vpicouet/generic-etc/data/)
Output : data/spectra.json   +   data/spectra.js   (= window.SPECTRA_DATA_BAKED = {…})

Structure of the JSON:
  grid          : {min_nm, max_nm, n}                          — common SED + atm grid
  sky_grid      : {min_nm, max_nm, n}                          — finer grid for sky lines
  atm           : { name: [...] }                              — global atm transmission curves
  sky_lines     : { name: [...] }                              — global sky-line catalogues
  spectra       : { name: [...] }                              — source SEDs (continuum, peak=1)
  atm_per_instrument        : { instrument: [...] }            — instrument-specific atm
  throughput_per_instrument : { instrument: [...] }            — instrument-specific E2E throughput
  sky_lines_per_instrument  : { instrument: [...] }            — instrument-specific sky lines

The instrument name keys are the folder names under data/sources/Instruments/, e.g.
"SCWI_SPEC", "FIREBall-2_2025". When the web app loads the instrument list from the
Google sheet, it tries to match each instrument's name (with spaces replaced by underscores
and dashes preserved) against this dict and prefers the instrument-specific curve over the
generic one.
"""
from __future__ import annotations
import json
import csv as _csv
from pathlib import Path
import numpy as np

# ---------------------------------------------------------------------------
ROOT   = Path(__file__).resolve().parent.parent
SRC    = ROOT / "data" / "sources"
OUT    = ROOT / "data" / "spectra.json"
OUTJS  = ROOT / "data" / "spectra.js"
SPEC_SRC = Path("/Users/Vincent/Github/generic-etc/data/Spectra")   # local-only sources (FITS + Salvato + COSMOS)
OUT.parent.mkdir(parents=True, exist_ok=True)

# ---------- common grids ----------
GRID_MIN_NM, GRID_MAX_NM, GRID_N = 80.0, 1100.0, 4000     # general SED grid
SKY_MIN_NM,  SKY_MAX_NM,  SKY_N  = 100.0, 400.0,  8000    # sky lines grid (finer)

grid    = np.linspace(GRID_MIN_NM, GRID_MAX_NM, GRID_N)
skygrid = np.linspace(SKY_MIN_NM,  SKY_MAX_NM,  SKY_N)


# ===========================================================================
# helpers
# ===========================================================================

def resample(wave_nm, flux, target):
    """Linear interp, zeros outside the input range."""
    wave_nm = np.asarray(wave_nm, float); flux = np.asarray(flux, float)
    ok = np.isfinite(wave_nm) & np.isfinite(flux)
    wave_nm, flux = wave_nm[ok], flux[ok]
    if wave_nm.size < 2:
        return np.zeros_like(target)
    order = np.argsort(wave_nm)
    wave_nm, flux = wave_nm[order], flux[order]
    return np.interp(target, wave_nm, flux, left=0.0, right=0.0)

def normalize(arr):
    m = float(np.nanmax(np.abs(arr)))
    return arr / m if m > 0 else arr

def round_arr(arr, decimals=5):
    """Return a Python list with rounded floats (smaller JSON)."""
    return [float(f"{v:.{decimals}g}") for v in arr]

def auto_wave_nm(wave_col):
    """Guess whether wave_col is in microns, nm or Å from its median value."""
    wm = float(np.nanmedian(wave_col))
    if wm < 50:
        return wave_col * 1000           # microns → nm
    elif wm < 10000:
        return wave_col                  # nm
    else:
        return wave_col / 10             # Å → nm

def read_two_col_csv(path):
    """Read a CSV/TXT with two numerical columns, returning (wave_nm, flux).

    Tolerates a header row, comma or whitespace separation, and units in microns,
    nm or Å (auto-detected from the median wavelength)."""
    text = path.read_text()
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        # split by comma or whitespace
        parts = [p.strip() for p in (line.split(",") if "," in line else line.split())]
        if len(parts) < 2: continue
        try:
            a = float(parts[0]); b = float(parts[1])
        except ValueError:
            continue
        rows.append((a, b))
    if not rows:
        raise ValueError("no numeric rows")
    arr = np.array(rows, float)
    return auto_wave_nm(arr[:,0]), arr[:,1]


# ===========================================================================
# 1. Global atmosphere transmission curves
# ===========================================================================
print("--- Atmosphere (global) ---")
atm_curves = {}

for fname, key in [
    ("pwv_atm_combined_ground.csv", "pwv_kpno (ground)"),
    ("pwv_atm.csv",                  "pwv_atm (KPNO)"),
    ("transmission_ground.csv",      "transmission_ground"),
    ("atm_transmission_secz1.5_1.6mm.txt", "atm_secz1.5_1.6mm"),
]:
    p = SRC / "Atm_transmission" / fname
    try:
        w_nm, t = read_two_col_csv(p)
        out = resample(w_nm, t, grid)
        atm_curves[key] = round_arr(np.clip(out, 0, 1.5), 4)
        print(f"  {key:32s} {len(w_nm):6d} pts native")
    except Exception as e:
        print(f"  {key:32s} SKIP ({e})")


# ===========================================================================
# 2. Global sky emission line catalogues
# ===========================================================================
print("--- Sky lines (global) ---")
sky_curves = {}

# These two files live in generic-etc (large), not in our data/sources to keep the repo small.
ETC_DATA = Path("/Users/Vincent/Github/generic-etc/data")
for src, key in [
    (ETC_DATA / "Sky_emission_lines/spectra_0.2A.csv", "spectra_0.2A"),
    (ETC_DATA / "Sky_emission_lines/UV_atm_lines.csv", "UV_atm_lines"),
]:
    try:
        w_nm, f = read_two_col_csv(src)
        out = resample(w_nm, f, skygrid)
        sky_curves[key] = round_arr(normalize(out), 4)
        print(f"  {key:20s} {len(w_nm)} pts")
    except Exception as e:
        print(f"  {key:20s} SKIP ({e})")


# ===========================================================================
# 3. Source SEDs — only locally available, not committed to etc-app
# ===========================================================================
print("--- Source SEDs ---")
spectra = {}

# 3a. FITS (HST/FOS QSOs)
try:
    from astropy.io import fits
    for f in sorted(SPEC_SRC.glob("h_*fos_spc.fits")):
        name = f.stem.replace("h_","").replace("fos_spc","").rstrip("_")
        try:
            with fits.open(f) as hdul:
                d = hdul[1].data
                if d is None or d.size == 0: continue
                wcol = next((c for c in d.dtype.names if "wave" in c.lower() or "lam" in c.lower()), d.dtype.names[0])
                fcol = next((c for c in d.dtype.names if "flux" in c.lower()), d.dtype.names[1])
                wave_A = np.asarray(d[wcol]).ravel()
                flux   = np.asarray(d[fcol]).ravel()
                spectra[f"QSO: {name}"] = round_arr(normalize(resample(wave_A/10, flux, grid)), 4)
        except Exception as e:
            print(f"    SKIP {f.name}: {e}")
    print(f"  FITS QSO: {sum(1 for k in spectra if k.startswith('QSO: '))}")
except ImportError:
    print("  astropy not installed — FITS SKIPped")

# 3b. Salvato QSO templates
n = 0
for f in sorted((SPEC_SRC/"QSO_SALVATO2015").glob("*.txt")):
    if "list" in f.name.lower(): continue
    try:
        arr = np.loadtxt(f)
        if arr.ndim != 2 or arr.shape[1] < 2: continue
        spectra[f"QSO Salvato: {f.stem}"] = round_arr(normalize(resample(arr[:,0], arr[:,1], grid)), 4)
        n += 1
    except Exception:
        pass
print(f"  QSO Salvato: {n}")

# 3c. COSMOS galaxy SEDs
n = 0
for f in sorted((SPEC_SRC/"GAL_COSMOS_SED").glob("*.txt")):
    if "list" in f.name.lower(): continue
    try:
        arr = np.loadtxt(f)
        if arr.ndim != 2 or arr.shape[1] < 2: continue
        spectra[f"GAL COSMOS: {f.stem}"] = round_arr(normalize(resample(arr[:,0], arr[:,1], grid)), 4)
        n += 1
    except Exception:
        pass
print(f"  GAL COSMOS: {n}")


# ===========================================================================
# 4. Instrument-specific curves
# ===========================================================================
print("--- Instrument-specific (from data/sources/Instruments) ---")

atm_per_inst       = {}
throughput_per_inst = {}
sky_per_inst       = {}

inst_root = SRC / "Instruments"
if inst_root.exists():
    for inst_dir in sorted(inst_root.iterdir()):
        if not inst_dir.is_dir(): continue
        name = inst_dir.name
        notes = []

        # Atmosphere
        p = inst_dir / "Atmosphere_transmission.csv"
        if p.exists():
            try:
                w_nm, t = read_two_col_csv(p)
                if w_nm.size >= 2:
                    atm_per_inst[name] = round_arr(np.clip(resample(w_nm, t, grid), 0, 1.5), 4)
                    notes.append(f"atm({w_nm.size})")
            except Exception as e:
                notes.append(f"atm ERR ({e})")

        # Throughput
        p = inst_dir / "Throughput.csv"
        if p.exists():
            try:
                w_nm, t = read_two_col_csv(p)
                if w_nm.size >= 2:
                    throughput_per_inst[name] = round_arr(np.clip(resample(w_nm, t, grid), 0, 1.5), 4)
                    notes.append(f"th({w_nm.size})")
            except Exception as e:
                notes.append(f"th ERR ({e})")

        # Sky emission lines
        p = inst_dir / "Sky_emission_lines.csv"
        if p.exists():
            try:
                w_nm, f = read_two_col_csv(p)
                if w_nm.size >= 2:
                    sky_per_inst[name] = round_arr(normalize(resample(w_nm, f, skygrid)), 4)
                    notes.append(f"sky({w_nm.size})")
            except Exception as e:
                notes.append(f"sky ERR ({e})")

        if notes:
            print(f"  {name:24s} → {', '.join(notes)}")
else:
    print(f"  (no folder {inst_root})")


# ===========================================================================
# Emit JSON + JS wrapper
# ===========================================================================
payload = {
    "grid":     {"min_nm": GRID_MIN_NM, "max_nm": GRID_MAX_NM, "n": GRID_N},
    "sky_grid": {"min_nm": SKY_MIN_NM,  "max_nm": SKY_MAX_NM,  "n": SKY_N},
    "atm":       atm_curves,
    "sky_lines": sky_curves,
    "spectra":   spectra,
    "atm_per_instrument":        atm_per_inst,
    "throughput_per_instrument": throughput_per_inst,
    "sky_lines_per_instrument":  sky_per_inst,
}

OUT.write_text(json.dumps(payload, separators=(",",":")))
OUTJS.write_text("window.SPECTRA_DATA_BAKED = " + json.dumps(payload, separators=(",",":")) + ";")
size = OUT.stat().st_size
print(f"\nSaved {OUT}  ({size/1024:.1f} KB)")
print(f"Saved {OUTJS}")
print(f"  {len(spectra)} spectra, {len(atm_curves)} atm, {len(sky_curves)} sky line catalogues")
print(f"  + per-instrument: {len(atm_per_inst)} atm, {len(throughput_per_inst)} throughput, {len(sky_per_inst)} sky")
