# Claude guide — `etc-app`

This file is loaded automatically when you start `claude` in this repo. Read it first,
then check `info.html` if you need the physics-level documentation rendered with
MathJax (same content, presented to end users).

## What this repo is

A browser-only JavaScript port of the [generic-etc](https://github.com/vpicouet/generic-etc)
Jupyter ETC + image simulator. It runs entirely client-side, hosts on GitHub Pages,
and shares the instrument database with the Python version via a public Google Sheet
loaded at startup through the `gviz/tq` CSV endpoint.

Live: <https://vpicouet.github.io/etc-app/>

## Pages

| File                  | Route                  | Purpose                                                  |
| --------------------- | ---------------------- | -------------------------------------------------------- |
| `index.html`          | `/`                    | The ETC + image simulator. ~3200 lines, all in one file. |
| `comparison.html`     | `/comparison.html`     | Instrument scatter + 2 radars (instruments / detectors). |
| `info.html`           | `/info.html`           | User manual + methodology with MathJax equations.        |
| `themes/*.css`        | —                      | UI theme palettes (default / caltech / nasa / twilight / terminal). The app currently locks to `twilight.css`. |
| `data/spectra.js`     | —                      | `window.SPECTRA_DATA_BAKED = {...}` — baked SEDs, atm and sky lines. ~1.9 MB. Loaded via `<script>` so `file://` works too. |
| `data/spectra.json`   | —                      | Same content, loadable via `fetch()` (the app prefers the `<script>` global). |
| `scripts/bake_spectra.py` | —                  | Regenerates `data/spectra.{js,json}` from CSVs/FITS under `data/sources/`. |

There is **no build step**. Edit, refresh the browser, commit, GitHub Pages picks it up.

## index.html — the main app

It's a single self-contained file with one big inline `<script>`. The structure of
the script, in order, is:

1. **PRNG + distributions** — `makeRng` (Mulberry32), `makeNormal` (Box–Muller),
   `makePoisson` (Knuth / Gaussian approx), `makeGamma` (Marsaglia–Tsang).
2. **`simulateImage(p)`** (~line 564) — builds a noisy 2D detector frame given a
   scalar parameter set `p`. Returns `{single, stack, ...}` plus diagnostics that
   the optics panel uses (`throughputCurve`, `atmCurve`, `skyLineMult`, `spectralProfile`).
   See "Image pipeline" below.
3. **`computeObservation(p)`** (~line 956) — pure SNR pipeline. `p` values can be
   scalars *or* arrays of length `N`. Arrays are broadcast pixel-wise so a sweep along
   any parameter is one call. Returns `{SNR, Total_noise_final, noises_per_exp, noises,
   electrons_per_pix, SB_lim_per_pix, ...}`.
4. **`PARAMS`** (~line 1171) — the canonical parameter table. Each entry has
   `{tab, label, unit, min, max, step, log?, default(_log)?, fmt, xable, tip}`. Adding
   a new parameter = adding an entry here. The tabs are `Source / Strategy /
   Instrument / Spectrograph / Detector`.
5. **`FLAGS`** (`{IFS, spectrograph, counting_mode}`), **`IMG_FLAGS`** (image-tab
   options: spectrum, atm_kind, sky_kind, QElambda, atmlambda, sky_lines, source_im),
   **`DEPENDENCIES`** (Nyquist locks).
6. **`STATE`** (~line 1243) — the global mutable state. **Add new fields directly to
   the literal**, do not write `STATE.foo = ...` at module top level — that's a TDZ
   trap (see "Common pitfalls" below).
7. **UI builders** — `buildUI`, `buildImageOptionsUI`, `buildDependencyUI`,
   `buildXAxisOptions`, `buildInstrumentOptions`.
8. **`drawPlot(res)`** (~line 1535) — the SNR view (4 stacked panels + draggable
   x-cursor + hover tooltip).
9. **`drawImageView()`** (~line 1954) — the Spectro image view (2 canvases + 4
   bottom subplots: spatial profile / spectral profile / histogram / optics).
10. **IFS view** — `IFS_STATE`, `buildIfsCubeFromModel`, `drawIfsView`, `drawIfsRect`,
    `drawIfsSpectrum`, plus the λ-cursor and extraction-box drag handlers.
11. **Theme + main** — `applyTheme`, `applyMode`, `initTheme`, and finally `main()`
    which: loads `spectra.js` data → builds the UI → fetches the GSheet → wires
    events → renders.

### Image pipeline (the part that confuses)

`simulateImage()` follows `Observation.SimulateFIREBallemCCDImage` from the Python
ETC. Key trick: profiles are **peak-normalised** (not Σ=1) and the source is divided
by the sum of a *narrower* Gaussian, so the source peak is correctly
`Signal_el_total / (2π σ_y σ_λ)` — i.e. proportional to the user's flux slider and
visible on the imshow. The naïve Σ=1 normalisation buries the source under read
noise; we lived through that bug, do not reintroduce it.

Sky is **gated by the slit profile** on the spatial axis. Dark current and extra
background are uniform (they originate at the detector). This is a hard physical
constraint of the simulator.

If the chosen baked atm curve is identically zero across the detector window (e.g.
`pwv_kpno` in the deep UV at 205 nm), `simulateImage` falls back to flat atm=1
with a console warning. Do not remove the fallback — without it the source
disappears for SCWI / FIREBall.

### IFS cube

`buildIfsCubeFromModel` constructs a **separable** PSF × spectrum cube. The Python
ETC uses `np.repeat` on the 2D image; that only works when the image is already a
3D cube, which it is not here. So we build it directly:

    cube[j, k, i] = signal_total · psf2D[j, k] · spectralProfile[i] + bg

with `psf2D` a 2D Gaussian (σ_y in detector pixels, σ_x in spaxels). Both axes use
`PSF_RMS_det` (the detector-level PSF), not `PSF_RMS_mask`. `Size_source` is added
in quadrature on both axes so the spot grows in both directions when the source
gets bigger.

`n3 = sqrt(60*60*FOV_size) / Slitwidth`, capped at 80 for performance.

### Common pitfalls

- **TDZ on STATE** — any `STATE.foo = ...` written at module top level above
  `const STATE = {…}` throws `Cannot access 'STATE' before initialization` and
  blocks the whole script. Always add new fields to the `STATE` literal itself.
- **Drawing too early** — the plot SVG sizes are read at draw time via
  `getBoundingClientRect`. If you call `drawPlot()` before the layout has settled,
  you get zero-size plots. The codebase defers via `requestAnimationFrame` (often
  twice). Mirror that pattern.
- **Hardcoded `#000` / `#fff` stroke** — in dark mode they become invisible. Use
  `cssVar("--plot-curve","#000")` (themed token) instead.
- **`pointer-events`** — the IFS overlay SVG is `pointer-events: none` so DS9
  right-click drag passes through to the canvas underneath. Only the rect element
  itself catches events. Mirror that pattern for any new draggable overlay.
- **EMCCD photon-counting RN** — `calculate_photon_counting_RN_noise()` uses a
  smooth analytic miscount model, **not** the lookup table the Python ETC has.
  Documented in `info.html §5.5`.

## comparison.html

Same data source as the app (instrument DB via `gviz/tq`). Three rows in a
no-scroll grid:

1. Scatter plot of all instruments with 4 dropdown-driven axes (X / Y / size /
   color), xlog/ylog/names checkboxes, hover tooltip.
2. Two pickers ("click to add" dropdowns): instruments + detectors. Chips with ×
   buttons.
3. Two radar plots: instrument performance (6 axes derived from the raw DB) and
   detector profile (5 axes, 5 hardcoded detectors mirroring the comparison sheet
   block).

Metrics are computed live by `deriveMetrics(d)` in `comparison.html`. Adding a new
metric = adding a key in the returned object and (optionally) in the `RADAR_*`
arrays.

## info.html

User-facing manual + methodology rendered with MathJax. Two columns: sticky TOC
with scrollspy on the left, content on the right. The TOC items are anchor links;
their IDs are how scrollspy and smooth-scroll find them.

The 3 screenshots embedded come from `images/`. Replace them in-place to update.

## Themes

Five CSS files under `themes/`. The app injects whichever one matches
`STATE.theme` (or the locked twilight). The themes only override **CSS variables**
on `:root` and `body[data-mode="dark"]`. Plot internals (axes, curves, colormaps)
are not themed by design — they go through dedicated `--plot-*` tokens which dark
mode overrides minimally.

To add a theme: copy `themes/twilight.css`, change variables, register the name in
`THEME_LIST` in `index.html`.

## Spectra bake

`scripts/bake_spectra.py` reads CSV/TXT/FITS files under `data/sources/Spectra`,
`Atm_transmission` and `Sky_emission_lines`, resamples them onto common grids
(SED grid 80–1100 nm × 4000; sky grid 100–400 nm × 8000), and dumps the result
to `data/spectra.json` + `data/spectra.js`.

Local source files for the heavy spectra (FITS QSO, COSMOS) live in
`/Users/Vincent/Github/generic-etc/data/Spectra` — they are not committed here to
keep the repo small. If running the bake fails because that path is missing, those
sources are skipped silently.

Re-running:

    cd /Users/Vincent/Github/etc-app
    source .venv/bin/activate   # has astropy + numpy
    python3 scripts/bake_spectra.py

## Local testing

GitHub Pages is the source of truth. For local iteration:

    python3 -m http.server 8000

then open `http://127.0.0.1:8000/`. `file://` works too for `index.html` because
spectra are loaded via `<script src=…>`, but `fetch()` of CSVs from Google Sheets
needs HTTPS.

## Deploying

Pages serves the `main` branch directly. Push to deploy. There is no CI.

## Things to avoid

- **Do not add a build step / bundler / framework.** The whole point is that a
  single push deploys instantly and anyone can read the source.
- **Do not introduce new top-level dependencies** beyond D3 (CDN) and MathJax
  (CDN, info.html only). Adding a dependency means a new CDN to trust.
- **Do not commit `.venv/`** — it was accidentally committed once; `.gitignore`
  now blocks it.
- **Do not touch the plot internals** (axis ticks, viridis LUT, curve widths)
  without a user request. They were tuned over many iterations and small changes
  break legibility in dark mode or with log axes.

## Useful greps

    grep -n "^function " index.html                 # all top-level functions
    grep -n "^const " index.html                    # all top-level consts (PARAMS, STATE, ...)
    grep -n "STATE\." index.html | head -40         # what state fields are used where
    grep -n "cssVar(" index.html                    # which strokes/fills are themed
