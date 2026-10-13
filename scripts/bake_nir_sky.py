"""bake_nir_sky.py — extend the sky-emission catalogues of data/spectra.json beyond 400 nm.

* spectra_0.2A  : UVES sky atlas, now baked over its full 300-1100 nm range
                  (before: only the 314-400 nm part survived on the 100-400 nm sky grid).
* Gemini_MK_NIR : Gemini Mauna Kea near/mid-IR sky background (0.9-5.6 um; zenith,
                  PWV = 1.6 mm, airmass 1.0; https://www.gemini.edu/observing/telescopes-and-sites/sites).

Each catalogue now has its own wavelength grid in  sky_grids[name]  (the global `sky_grid`
is kept for backward compatibility). Catalogues are stored as the *relative excess over the
local continuum*, e(lambda) = max(0, S/S_cont - 1), which is what index.html expects
(sky(lambda) = Sky_continuum * (1 + e(lambda)) after convolution with the spectral resolution).

Run:  python3 scripts/bake_nir_sky.py
"""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
JSON = ROOT / "data" / "spectra.json"
JS   = ROOT / "data" / "spectra.js"
UVES = Path("/Users/Vincent/Github/generic-etc/data/Sky_emission_lines/spectra_0.2A.csv")
GEM  = ROOT / "data" / "sources" / "Sky_emission_lines" / "Gemini_MK_NIR_pwv1.6_am1.0.csv"

def read2(p):
    d = np.genfromtxt(p, delimiter=",", comments="#", skip_header=0, invalid_raise=False)
    d = d[np.isfinite(d).all(axis=1)] if d.ndim == 2 else d
    return d[:, 0], d[:, 1]

def resample(w, f, g):
    o = np.argsort(w); return np.interp(g, w[o], f[o], left=0.0, right=0.0)

def rolling_pct(y, win, q):
    pad = win // 2
    yp = np.pad(y, pad, mode="edge")
    from numpy.lib.stride_tricks import sliding_window_view
    return np.percentile(sliding_window_view(yp, win)[: y.size], q, axis=1)

payload = json.loads(JSON.read_text())
payload.setdefault("sky_grids", {})

# --- UVES, full range -------------------------------------------------------
w, f = read2(UVES)
g = np.linspace(300.0, 1100.0, 8000)                  # 0.1 nm
u = np.clip(resample(w, f, g), 0, None)
u = u / u.max()
payload["sky_lines"]["spectra_0.2A"] = [round(float(x), 4) for x in u]
payload["sky_grids"]["spectra_0.2A"] = {"min_nm": 300.0, "max_nm": 1100.0, "n": 8000}

# --- Gemini NIR / MIR --------------------------------------------------------
w, s = read2(GEM)                                      # nm, ph/s/arcsec^2/nm/m^2
g = np.linspace(w.min(), w.max(), int(round((w.max() - w.min()) / 0.2)) + 1)
s = resample(w, s, g)
cont = np.maximum(rolling_pct(s, 801, 10), 1e-12)      # +-40 nm window, 10th percentile
e = np.clip(s / cont - 1.0, 0.0, 200.0)
payload["sky_lines"]["Gemini_MK_NIR"] = [round(float(x), 2) for x in e]
payload["sky_grids"]["Gemini_MK_NIR"] = {"min_nm": float(g[0]), "max_nm": float(g[-1]), "n": int(g.size)}

JSON.write_text(json.dumps(payload, separators=(",", ":")))
JS.write_text("window.SPECTRA_DATA_BAKED = " + json.dumps(payload, separators=(",", ":")) + ";")
print("sky_grids:", payload["sky_grids"])
print(f"{JSON.name}: {JSON.stat().st_size/1024:.0f} KB")
