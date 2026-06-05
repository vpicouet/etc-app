"""bake_cubes.py — resample emission datacubes using physical WCS (phys=True mode from
Observation.py) so the output cube covers exactly a fixed sky FOV in arcsec.

Each cube is baked at several FOV sizes (arcsec) so the app can pick the right one
based on the current instrument's pixel_scale × detector size.

Input  : /Users/Vincent/Github/generic-etc/data/Emission_cube/*_resampled.fits
Output : data/cubes/<name>_<fov>as.bin    float32 (nz, ny, nx) little-endian
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

# Output detector size in pixels (same as simulateImage W=500, H=100)
OUT_NY = 100   # spatial pixels
OUT_NX = 100   # spatial pixels (square sky patch)
OUT_NZ = 500   # spectral channels

# FOV sizes to bake (arcsec, square patch = OUT_NX × OUT_NY pixels)
# Covers FIREBall (~50"), SCWI (~200"), KCWI-like (>500")
FOV_ARCSEC = [30, 60, 120, 300, 600]

# Cubes: (fits_stem, display_label, wave_out_override_nm_or_None)
# wave_out_override: force output wavelength range (nm) regardless of the cube's native WCS.
# Needed for cubes whose native λ (e.g. 287–293 nm) doesn't overlap with UV instruments
# (185–220 nm).  The spectral axis is simply stretched to fill the requested band — same
# trick as Observation.py which always passes wave_range_nm = detector band.
LYA_RANGE = (184.6, 222.4)   # matches other cubes and FIREBall/SCWI band

CUBES = [
    ("lya_cube_merged_with_artificial_source_CU_1pc_resampled", "Lya CGM + artificial source", None),
    ("CGM_cube_resampled",                                       "CGM cube",                    None),
    ("galaxy_disk_cube_resampled",                               "Galaxy disk",                 None),
    ("galaxy_and_cgm_cube_resampled",                            "Galaxy + CGM",                LYA_RANGE),
    ("cube_01_resampled",                                        "cube_01",                     LYA_RANGE),
]

# ---------------------------------------------------------------------------
def fits_wcs_spatial(header):
    """Return (spatial_radius_x_arcsec, spatial_radius_y_arcsec) for the cube."""
    cdelt1 = abs(float(header["CDELT1"]))  # degrees/pix
    cdelt2 = abs(float(header["CDELT2"]))
    nx = int(header["NAXIS1"])
    ny = int(header["NAXIS2"])
    rx = cdelt1 * (nx - 1) / 2.0 * 3600  # arcsec
    ry = cdelt2 * (ny - 1) / 2.0 * 3600
    return rx, ry

def fits_wcs_wave(header):
    """Return wavelength axis in nm."""
    crval = float(header["CRVAL3"])
    cdelt = float(header["CDELT3"])
    crpix = float(header.get("CRPIX3", 1))
    cunit = header.get("CUNIT3", "m").strip()
    unit  = u.Unit(cunit)
    nz    = int(header["NAXIS3"])
    pix   = np.arange(nz)
    wave_m = (crval + (pix + 1 - crpix) * cdelt) * unit.to(u.m)
    return (wave_m * u.m).to(u.nm).value

def resample_phys(data, wave_nm_in, spatial_radius_in_x, spatial_radius_in_y,
                  wave_nm_out, spatial_radius_out):
    """
    Port of Observation.py resample_cube(phys=True, mode='interp').
    data shape: (nz, ny, nx)
    Returns resampled (nz_out, ny_out, nx_out) float32, flux-conserving.
    """
    nz_in, ny_in, nx_in = data.shape
    nz_out = len(wave_nm_out)
    # ny_out = nx_out = OUT_NX (square)

    input_x = np.linspace(-spatial_radius_in_x, spatial_radius_in_x, nx_in)
    input_y = np.linspace(-spatial_radius_in_y, spatial_radius_in_y, ny_in)
    output_x = np.linspace(-spatial_radius_out, spatial_radius_out, OUT_NX)
    output_y = np.linspace(-spatial_radius_out, spatial_radius_out, OUT_NY)

    interpolator = RegularGridInterpolator(
        (wave_nm_in, input_x, input_y),
        data.astype(np.float64),
        method="linear",
        bounds_error=False,
        fill_value=0.0,
    )
    W, X, Y = np.meshgrid(wave_nm_out, output_x, output_y, indexing="ij")
    out = interpolator((W, X, Y)).astype(np.float32)

    # Flux conservation: scale by voxel-size ratio
    if nx_in > 1 and ny_in > 1 and nz_in > 1:
        scale = (
            abs((output_x[1]-output_x[0]) / (input_x[1]-input_x[0])) *
            abs((output_y[1]-output_y[0]) / (input_y[1]-input_y[0])) *
            abs((wave_nm_out[1]-wave_nm_out[0]) / (wave_nm_in[1]-wave_nm_in[0]))
        )
        out *= float(scale)

    out = np.clip(out, 0, None)
    return out

# ---------------------------------------------------------------------------
index = {}

for stem, label, wave_override in CUBES:
    src = CUBES_IN / (stem + ".fits")
    if not src.exists():
        print(f"  SKIP {stem} (not found)")
        continue

    print(f"\n  {label}  ({stem})")
    with fits.open(src) as hdul:
        hdr  = hdul[0].header
        data = hdul[0].data.astype(np.float32)   # (nz, ny, nx)

    wave_nm_in = fits_wcs_wave(hdr)
    rx_in, ry_in = fits_wcs_spatial(hdr)
    nz, ny, nx = data.shape
    print(f"    input  : ({nz}, {ny}, {nx})  λ={wave_nm_in[0]:.1f}–{wave_nm_in[-1]:.1f} nm  "
          f"FOV={2*rx_in:.0f}\"×{2*ry_in:.0f}\"")
    if wave_override:
        print(f"    → remapping spectral axis to {wave_override[0]:.1f}–{wave_override[1]:.1f} nm")

    # Subtract median background (same as Observation.py)
    data -= np.nanmedian(data)
    data  = np.clip(data, 0, None)

    # Output spectral axis: use override if the native range doesn't match instrument band
    if wave_override:
        wave_nm_out = np.linspace(wave_override[0], wave_override[1], OUT_NZ)
        # Remap input spectral axis to [0,1] and stretch — same as Observation.py phys=False
        # but only on the spectral dimension. We re-create a new wave_nm_in that spans the
        # same number of points, so the interpolator samples the full cube spectral range.
        wave_nm_in = np.linspace(wave_override[0], wave_override[1], len(wave_nm_in))
    else:
        wave_nm_out = np.linspace(wave_nm_in[0], wave_nm_in[-1], OUT_NZ)

    cube_entry = {
        "label":    label,
        "wave_min": float(round(wave_nm_out[0],  3)),
        "wave_max": float(round(wave_nm_out[-1], 3)),
        "wave_n":   OUT_NZ,
        "fov_variants": {},   # fov_arcsec → {file, shape}
    }

    for fov in FOV_ARCSEC:
        spatial_radius_out = fov / 2.0
        out = resample_phys(data, wave_nm_in, rx_in, ry_in, wave_nm_out, spatial_radius_out)

        # Peak-normalise (Observation.py uses percentile 99.999)
        p999 = float(np.percentile(out, 99.999)) if out.max() > 0 else 1.0
        if p999 > 0:
            out /= p999

        peak = float(out.max())
        n_nonzero = int(np.count_nonzero(out > 0.001))
        print(f"    FOV={fov:4d}\"  out=({OUT_NZ},{OUT_NY},{OUT_NX})  "
              f"peak={peak:.3f}  nonzero={n_nonzero}/{OUT_NZ*OUT_NY*OUT_NX}")

        bin_name = f"{stem}_{fov}as.bin"
        out_path = OUT_DIR / bin_name
        out.astype("<f4").tofile(out_path)

        cube_entry["fov_variants"][str(fov)] = {
            "file":  bin_name,
            "shape": [OUT_NZ, OUT_NY, OUT_NX],
            "fov_arcsec": fov,
        }

    index[stem] = cube_entry

OUT_IDX.write_text(json.dumps(index, indent=2))
OUT_IDX_JS = OUT_DIR / "index.js"
OUT_IDX_JS.write_text("window.CUBE_INDEX_BAKED=" + json.dumps(index, separators=(",",":")) + ";")
print(f"\nWrote {OUT_IDX}  ({OUT_IDX.stat().st_size/1024:.1f} KB)")
print(f"Wrote {OUT_IDX_JS}")
for k, v in index.items():
    fovs = list(v["fov_variants"].keys())
    print(f"  {v['label']:35s}  λ={v['wave_min']:.0f}–{v['wave_max']:.0f} nm  FOVs={fovs}")
