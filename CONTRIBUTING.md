# Contributing to etc-app

Thanks for adding data for your instrument! The app is **browser-only** (no server), so all spectra and throughput curves are pre-baked into a single JSON file (`data/spectra.json`) that the page fetches at startup. Contributing boils down to:

1. Drop one or more CSV files into the right folder
2. Run the bake script (Python, ~5 s)
3. Open `index.html` locally to verify
4. Submit a Pull Request

---

## Quick-start: adding throughput for a new instrument

### 1 — Create a folder under `data/sources/Instruments/`

The folder name **must exactly match** the instrument name in the Google Sheet (spaces replaced by underscores, dashes preserved). Examples: `SCWI_SPEC`, `FIREBall-2_2025`, `My_Instrument`.

```
data/sources/Instruments/
└── My_Instrument/
    ├── Throughput.csv               ← required
    ├── Atmosphere_transmission.csv  ← optional
    └── Sky_emission_lines.csv       ← optional
```

### 2 — Format of each CSV

All files use the **same two-column format**: `wavelength, value`. A one-line header (any text) is fine and is auto-skipped. The bake script auto-detects whether wavelengths are in **Å, nm, or µm** from the median value.

**`Throughput.csv`** — end-to-end system throughput (QE × optics × detector), 0–1:

```csv
wave_nm, throughput
190.0,   0.00
195.0,   0.08
200.0,   0.12
210.0,   0.15
...
```

**`Atmosphere_transmission.csv`** — atmospheric transmission at your site/altitude, 0–1:

```csv
wave_nm, transmission
180.0, 0.0
190.0, 0.0
200.0, 0.35
210.0, 0.82
...
```

**`Sky_emission_lines.csv`** — sky background spectrum (airglow, zodiacal, etc.), arbitrary units (auto-normalised to peak = 1):

```csv
wave_nm, flux
190.0, 0.0
195.5, 1.2
196.0, 0.0
...
```

> **Units:** wavelengths in Å (> 2000), nm (50–2000), or µm (< 50) — all auto-detected.
> Values are clipped to [0, 1.5] for throughput/atmosphere, and peak-normalised for sky lines.

### 3 — Run the bake script

Requires Python ≥ 3.9 and numpy. No other dependencies for just the instrument curves.

```bash
cd etc-app
python scripts/bake_spectra.py
```

Output: `data/spectra.json` and `data/spectra.js` are overwritten in place (~2.7 MB each). You should see your instrument listed:

```
--- Instrument-specific (from data/sources/Instruments) ---
  My_Instrument            → th(120), atm(4000)
```

### 4 — Verify in the browser

Just open `index.html` directly (no server needed):

```bash
open index.html      # macOS
xdg-open index.html  # Linux
```

Select your instrument from the dropdown. Go to tab **Spectro image** and check:
- The **Optics** panel shows your throughput curve (labelled "instrument (My_Instrument)")
- The **Atm** curve is yours if you provided `Atmosphere_transmission.csv`
- Sky lines are visible in the image if you provided `Sky_emission_lines.csv` and enabled *Sky emission lines*

### 5 — Submit a Pull Request

Commit the CSV files and the regenerated `data/spectra.json` + `data/spectra.js`:

```bash
git add data/sources/Instruments/My_Instrument/
git add data/spectra.json data/spectra.js
git commit -m "feat(data): add throughput curves for My_Instrument"
git push origin my-branch
```

Then open a PR. The JSON is committed so the app works immediately on GitHub Pages without any build step.

---

## Adding a global atmosphere curve

Place a two-column CSV in `data/sources/Atm_transmission/` and register it in `bake_spectra.py` in the section "Global atmosphere transmission curves" (a one-liner):

```python
("my_site_atm.csv", "my site (ground)"),
```

After baking, it appears in the *Atm curve* dropdown under *Image Options*.

---

## Adding a sky-line catalogue

The two existing catalogues live in `generic-etc/data/Sky_emission_lines/` (a sibling repo, not committed here because of size). To add a new one, point the bake script at your file in the same section, or add it as `data/sources/Sky_emission_lines/my_catalogue.csv` and register it in the bake script. It will then appear in the *Sky-line catalogue* dropdown.

---

## Instrument name matching

The app matches the Google Sheet instrument name to a folder by replacing spaces with underscores. So "FIREBall 2025" in the sheet → looks for `FIREBall_2025` in `data/sources/Instruments/`. If the names don't match nothing breaks — the app just falls back to the generic (Gaussian) throughput curve.

The UV instruments (FIREBall, GALEX, UVEX, SCWI) also automatically default the sky catalogue to `UV_atm_lines` when selected.

---

## File size tips

The baked JSON is ~2.7 MB. A single instrument's throughput curve typically adds < 5 KB. If your curve has more points than needed, downsample before committing — 50–200 points is plenty for a smooth curve.

---

## bake_spectra.py dependencies

| Package | Purpose |
|---------|---------|
| `numpy` | resampling and normalisation |
| `astropy` | reading FITS source SEDs (optional — only needed for the HST/FOS QSO spectra, not for instrument curves) |

```bash
pip install numpy          # minimum
pip install numpy astropy  # full build with all source SEDs
```
