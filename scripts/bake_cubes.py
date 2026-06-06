"""bake_cubes.py — resample emission datacubes to a single bin per cube,
covering exactly the native spatial FOV of each cube at 100×100 pixels.

The JS then maps the detector FOV onto this bin using the stored native_fov_arcsec,
exactly mirroring Observation.py which resamples to output_x = linspace(±detFov/2)
onto input_x = linspace(±nativeFov/2).

Input  : /Users/Vincent/Github/generic-etc/data/Emission_cube/*.fits  (originals)
Output : data/cubes/<name>.bin         float32 (nz, ny, nx) little-endian
         data/cubes/index.json / index.js

Run:
    /usr/local/bin/python3 scripts/bake_cubes.py
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy import units as u
from scipy.interpolate import RegularGridInterpolator

ROOT     = Path(__file__).resolve().parent.parent
CUBES_IN = Path("/Users/Vincent/Github/generic-etc/data/Emission_cube")
OUT_DIR  = ROOT / "data" / "cubes"
OUT_IDX  = OUT_DIR / "index.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_NY = 100   # spatial pixels (along-slit)  = detector H
OUT_NX = 100   # spatial pixels (cross-slit)
OUT_NZ = 500   # spectral channels           = detector W

# SCWI instrument parameters — baked cubes target this instrument exactly.
# pixel_scale=1.5"/pix, H=100 pix → spatial_extent = 150"
# wavelength=205nm, dispersion=1.1A/pix, W=500 → band = 205±27.5nm = 177.5–232.5nm
SCWI_PIXEL_SCALE   = 1.5    # "/pix
SCWI_WAVELENGTH_NM = 205.0  # nm
SCWI_DISPERSION_A  = 1.1    # A/pix
SCWI_SPATIAL_ARCSEC = OUT_NY * SCWI_PIXEL_SCALE        # 150"
SCWI_WAVE_MIN = SCWI_WAVELENGTH_NM - (OUT_NZ/2) * SCWI_DISPERSION_A / 10  # nm
SCWI_WAVE_MAX = SCWI_WAVELENGTH_NM + (OUT_NZ/2) * SCWI_DISPERSION_A / 10  # nm

# (fits_stem, display_label)
CUBES = [
    ("lya_cube_merged_with_artificial_source_CU_1pc", "Lya CGM + artificial source"),
    ("CGM_cube",                                       "CGM cube"),
    ("galaxy_disk_cube",                               "Galaxy disk"),
    ("galaxy_and_cgm_cube",                            "Galaxy + CGM"),
    ("cube_01",                                        "cube_01"),
]

# ---------------------------------------------------------------------------
def fits_wcs_spatial(header):
    cdelt1 = abs(float(header["CDELT1"]))
    cdelt2 = abs(float(header["CDELT2"]))
    nx = int(header["NAXIS1"]); ny = int(header["NAXIS2"])
    rx = cdelt1 * (nx - 1) / 2.0 * 3600
    ry = cdelt2 * (ny - 1) / 2.0 * 3600
    return rx, ry

def fits_wcs_wave(header):
    crval = float(header["CRVAL3"]); cdelt = float(header["CDELT3"])
    crpix = float(header.get("CRPIX3", 1))
    unit  = u.Unit(header.get("CUNIT3", "m").strip())
    nz    = int(header["NAXIS3"])
    wave_m = (crval + (np.arange(nz) + 1 - crpix) * cdelt) * unit.to(u.m)
    return (wave_m * u.m).to(u.nm).value

# ---------------------------------------------------------------------------
index = {}

for stem, label in CUBES:
    src = CUBES_IN / (stem + ".fits")
    if not src.exists():
        print(f"  SKIP {stem} (not found)"); continue

    print(f"\n  {label}  ({stem})")
    with fits.open(src) as hdul:
        hdr  = hdul[0].header
        data = hdul[0].data.astype(np.float32)

    wave_nm_in = fits_wcs_wave(hdr)
    rx_in, ry_in = fits_wcs_spatial(hdr)
    nz, ny, nx = data.shape
    print(f"    input : ({nz},{ny},{nx})  λ={wave_nm_in[0]:.1f}–{wave_nm_in[-1]:.1f} nm  "
          f"FOV={2*rx_in:.1f}\"×{2*ry_in:.1f}\"")

    data -= np.nanmedian(data)
    data  = np.clip(data, 0, None)

    # Output spectral axis = SCWI detector band (same as Observation.py wave_range_nm)
    # For cube_01 whose native λ=203–205nm is inside the SCWI band, no override needed —
    # the interpolator samples it correctly with fill_value=0 outside.
    wave_nm_out = np.linspace(SCWI_WAVE_MIN, SCWI_WAVE_MAX, OUT_NZ)

    # Output spatial axis = SCWI detector FOV (spatial_extent_arcsec = 100 * pixel_scale)
    # This is EXACTLY what Observation.py passes to convert_fits_cube.
    spatial_radius_out = SCWI_SPATIAL_ARCSEC / 2.0   # 75"

    input_x = np.linspace(-rx_in, rx_in, nx)
    input_y = np.linspace(-ry_in, ry_in, ny)
    output_x = np.linspace(-spatial_radius_out, spatial_radius_out, OUT_NX)
    output_y = np.linspace(-spatial_radius_out, spatial_radius_out, OUT_NY)

    interp = RegularGridInterpolator(
        (wave_nm_in, input_x, input_y), data.astype(np.float64),
        method="linear", bounds_error=False, fill_value=0.0)
    W, X, Y = np.meshgrid(wave_nm_out, output_x, output_y, indexing="ij")
    out = interp((W, X, Y)).astype(np.float32)
    out = np.clip(out, 0, None)

    p999 = float(np.percentile(out, 99.999)) if out.max() > 0 else 1.0
    if p999 > 0: out /= p999

    print(f"    output: ({OUT_NZ},{OUT_NY},{OUT_NX})  peak={out.max():.3f}  "
          f"nonzero={np.count_nonzero(out>0.001)}/{OUT_NZ*OUT_NY*OUT_NX}")

    bin_name = f"{stem}.bin"
    (OUT_DIR / bin_name).write_bytes(out.astype("<f4").tobytes())

    index[stem] = {
        "label":              label,
        "wave_min":           float(round(wave_nm_out[0],  3)),
        "wave_max":           float(round(wave_nm_out[-1], 3)),
        "wave_n":             OUT_NZ,
        "spatial_arcsec":     float(SCWI_SPATIAL_ARCSEC),   # 150" — JS maps det pixels 1:1
        "pixel_scale_arcsec": float(SCWI_PIXEL_SCALE),
        "shape":              [OUT_NZ, OUT_NY, OUT_NX],
        "file":               bin_name,
    }

OUT_IDX.write_text(json.dumps(index, indent=2))
OUT_IDX_JS = OUT_DIR / "index.js"
OUT_IDX_JS.write_text("window.CUBE_INDEX_BAKED=" + json.dumps(index, separators=(",",":")) + ";")
print(f"\nWrote {OUT_IDX}  ({OUT_IDX.stat().st_size/1024:.1f} KB)")
for k, v in index.items():
    print(f"  {v['label']:35s}  λ={v['wave_min']:.0f}–{v['wave_max']:.0f} nm  "
          f"FOV={v['spatial_arcsec']:.0f}\"  {v['file']}")
