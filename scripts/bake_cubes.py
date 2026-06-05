"""bake_cubes.py — resample emission datacubes from generic-etc into compact float32 binaries
for the web app.

Input  : /Users/Vincent/Github/generic-etc/data/Emission_cube/*_resampled.fits
Output : data/cubes/<name>.bin   (float32 little-endian, shape = nz × ny × nx)
         data/cubes/index.json   (manifest with shape, WCS, label for each cube)

The output cubes are already in erg/cm²/s/arcsec²/Å (same unit as the app's Signal slider).
Each cube is peak-normalised to 1 — the app scales by Signal_el at render time, exactly
as Observation.py does:  cube_detector = Signal_el * cube / percentile(cube, 99.999)

Disable cube support in the web app by setting EMISSION_CUBES_ENABLED = false at the top
of index.html — that single flag prevents any cube from loading or appearing in the UI.

Run:
    /usr/local/bin/python3 scripts/bake_cubes.py
"""
from __future__ import annotations
import json, struct
from pathlib import Path
import numpy as np
from astropy.io import fits
from scipy.ndimage import zoom

# ---------------------------------------------------------------------------
ROOT     = Path(__file__).resolve().parent.parent
CUBES_IN = Path("/Users/Vincent/Github/generic-etc/data/Emission_cube")
OUT_DIR  = ROOT / "data" / "cubes"
OUT_IDX  = OUT_DIR / "index.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Output spatial size (nx × ny on sky, not detector pixels).
# Kept at 100×100 — the resampled FITS are already 100×100 on sky; we just redispatch spectrally.
OUT_NX = 100
OUT_NY = 100
# Output spectral axis: we keep 500 channels — same as the FITS. No spectral resampling needed
# since the FITS was already baked to 500 channels by Observation.py's convert_fits_cube().
OUT_NZ = 500

# Cubes to bake: (fits_stem, display_label)
CUBES = [
    ("lya_cube_merged_with_artificial_source_CU_1pc_resampled", "Lya CGM + artificial source"),
    ("CGM_cube_resampled",                                       "CGM cube"),
    ("galaxy_disk_cube_resampled",                               "Galaxy disk"),
    ("galaxy_and_cgm_cube_resampled",                            "Galaxy + CGM"),
    ("cube_01_resampled",                                        "cube_01"),
]

# ---------------------------------------------------------------------------
def fits_wcs(header):
    """Extract linear WCS for axis 3 (wavelength) in nm."""
    crval = float(header["CRVAL3"])
    cdelt = float(header["CDELT3"])
    crpix = float(header.get("CRPIX3", 1))
    unit  = header.get("CUNIT3", "m").strip().lower()
    fac   = {"m": 1e9, "nm": 1.0, "angstrom": 0.1, "aa": 0.1, "a": 0.1}.get(unit, 1e9)
    nz    = int(header["NAXIS3"])
    pix   = np.arange(nz)
    wave_nm = (crval + (pix + 1 - crpix) * cdelt) * fac
    return wave_nm   # shape (nz,)

def resample_cube(data, wave_nm_in, nx_out, ny_out, nz_out):
    """
    Resample a (nz, ny, nx) float32 cube to (nz_out, ny_out, nx_out).
    Spatial axes: zoom with order=1.
    Spectral axis: kept as-is if nz == nz_out, else zoom order=1.
    """
    nz, ny, nx = data.shape
    zoom_z = nz_out / nz
    zoom_y = ny_out / ny
    zoom_x = nx_out / nx
    if abs(zoom_z - 1) < 1e-6 and abs(zoom_y - 1) < 1e-6 and abs(zoom_x - 1) < 1e-6:
        return data.astype(np.float32)
    out = zoom(data.astype(np.float32), (zoom_z, zoom_y, zoom_x), order=1, prefilter=False)
    return out.astype(np.float32)

# ---------------------------------------------------------------------------
index = {}

for stem, label in CUBES:
    src = CUBES_IN / (stem + ".fits")
    if not src.exists():
        print(f"  SKIP {stem} (not found)")
        continue

    print(f"  {label}  ({stem})")
    with fits.open(src) as hdul:
        hdr  = hdul[0].header
        data = hdul[0].data.astype(np.float32)   # shape: (nz, ny, nx)

    wave_nm = fits_wcs(hdr)
    nz, ny, nx = data.shape
    print(f"    input  : ({nz}, {ny}, {nx})  λ={wave_nm[0]:.1f}–{wave_nm[-1]:.1f} nm")

    # Subtract median background (same as Observation.py)
    med = np.nanmedian(data)
    data = data - med
    data = np.clip(data, 0, None)

    # Resample to output shape
    out = resample_cube(data, wave_nm, OUT_NX, OUT_NY, OUT_NZ)
    nz_o, ny_o, nx_o = out.shape

    # Compute output wavelength axis (same linear spacing, resampled)
    if nz_o == nz:
        wave_out = wave_nm
    else:
        wave_out = np.linspace(wave_nm[0], wave_nm[-1], nz_o)

    # Peak-normalise to 1 (Observation.py uses percentile 99.999 — we use nanmax for simplicity;
    # the app will rescale by Signal_el anyway)
    p999 = float(np.percentile(out, 99.999)) if out.max() > 0 else 1.0
    if p999 > 0:
        out = out / p999

    print(f"    output : ({nz_o}, {ny_o}, {nx_o})  λ={wave_out[0]:.1f}–{wave_out[-1]:.1f} nm  "
          f"peak={out.max():.3f}  size={out.nbytes/1024/1024:.1f} MB")

    # Write binary — row-major (nz, ny, nx) float32 little-endian
    bin_name = stem + ".bin"
    out_path = OUT_DIR / bin_name
    out.astype("<f4").tofile(out_path)
    print(f"    → {out_path}  ({out_path.stat().st_size/1024/1024:.1f} MB)")

    # Manifest entry
    key = stem  # used as the JS dict key
    index[key] = {
        "label":    label,
        "file":     bin_name,
        "shape":    [int(nz_o), int(ny_o), int(nx_o)],   # [nz, ny, nx]
        "wave_min": float(round(wave_out[0],  3)),
        "wave_max": float(round(wave_out[-1], 3)),
        "wave_n":   int(nz_o),
        "spatial_arcsec": float(round(float(hdr.get("CDELT1", 0)) * 3600 * nx_o, 1)),
    }

OUT_IDX.write_text(json.dumps(index, indent=2))
OUT_IDX_JS = OUT_DIR / "index.js"
OUT_IDX_JS.write_text("window.CUBE_INDEX_BAKED = " + json.dumps(index, separators=(",",":")) + ";")
print(f"\nWrote {OUT_IDX}")
print(f"Wrote {OUT_IDX_JS}")

print(f"  {len(index)} cubes baked")
for k, v in index.items():
    print(f"  {v['label']:35s}  λ={v['wave_min']:.0f}–{v['wave_max']:.0f} nm  "
          f"shape={v['shape']}")
