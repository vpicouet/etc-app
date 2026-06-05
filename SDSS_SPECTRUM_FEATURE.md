# Fetch SDSS spectrum by object name — implementation notes

## Concept

User types an object name (e.g. "NGC 1068", "Mrk 421") in a new input field in the
Source accordion. The app resolves the name via SIMBAD, searches SDSS for a spectrum,
downloads it as JSON, resamples it onto the detector wavelength grid, and injects it
as the active source spectrum — exactly like the baked SEDs but fetched live.

Coverage: **~3800–9200 Å** (SDSS optical). Not suitable for UV instruments (FIREBall,
SCWI). Falls back to "Baseline emission line" if no SDSS spectrum is found.

---

## Step 1 — Name resolution via SIMBAD TAP

SIMBAD TAP is CORS-enabled and returns JSON.

```
GET https://simbad.u-strasbg.fr/simbad/sim-tap/sync
  ?REQUEST=doQuery
  &LANG=ADQL
  &FORMAT=json
  &QUERY=SELECT ra,dec,rvz_redshift,sp_type FROM basic JOIN ident ON ident.oidref=basic.oid WHERE ident.id='NGC 1068'
```

Response (JSON):
```json
{
  "data": [[40.6696, -0.0133, 0.00379, "Sy2"]]
}
```

Fields used:
- `ra`, `dec` → passed to SDSS query
- `rvz_redshift` → stored as `p.Redshift` so the spectrum is shifted correctly
- `sp_type` → shown in the UI as info

---

## Step 2 — SDSS spectrum search by coordinates

SDSS SkyServer `specobjrad` endpoint: finds the nearest spectrum within a radius.

```
GET https://skyserver.sdss.org/dr18/SkyServerWS/SpectroQuery/GetSpecByPos
  ?ra=40.6696
  &dec=-0.0133
  &radius=0.02       ← degrees (~1.2 arcmin)
  &limit=1
  &format=json
```

Response: list of `{plate, mjd, fiberid, z, class, subClass, ...}`.
If empty → no SDSS spectrum → show a "not found in SDSS" message and stop.

---

## Step 3 — Download the spectrum as JSON

Once we have `plate`, `mjd`, `fiberid`:

```
GET https://skyserver.sdss.org/dr18/SkyServerWS/SpectroQuery/GetSpectrumByFiber
  ?plate=PLATE
  &mjd=MJD
  &fiber=FIBERID
  &format=json
```

Response: array of `{wavelength, flux, ivar, model}` — wavelength in Å, flux in
10⁻¹⁷ erg/cm²/s/Å.

Alternative (direct CSV from SAS, also CORS-OK):
```
https://dr18.sdss.org/sas/dr18/spectro/redux/v5_13_2/spectra/lite/PLATE/spec-PLATE-MJD-FIBER.fits
```
This is a FITS file — requires a minimal FITS parser in JS (see below).

The JSON endpoint is simpler and preferred.

---

## Step 4 — Resample onto detector wavelength grid

The detector wavelength grid is already computed in `simulateImage()`:
```js
const wave_min = 10*wavelength - (W/2)*dispersion;  // Å
const wave_max = 10*wavelength + (W/2)*dispersion;
```

Resampling (linear interpolation, same as `interpCurve`):
```js
function resampleSpectrum(sdssWave, sdssFlux, detectorWave) {
  // sdssWave: Float64Array in Å (log-spaced, ~3800–9200 Å)
  // detectorWave: Float64Array in Å (linear, instrument window)
  const out = new Float64Array(detectorWave.length);
  for (let i = 0; i < detectorWave.length; i++) {
    const lam = detectorWave[i];
    // binary search in sdssWave
    let lo = 0, hi = sdssWave.length - 1;
    while (hi - lo > 1) { const m = (lo+hi)>>1; sdssWave[m] <= lam ? lo=m : hi=m; }
    const t = (lam - sdssWave[lo]) / (sdssWave[hi] - sdssWave[lo]);
    out[i] = sdssWave[lo] <= lam && lam <= sdssWave[hi]
      ? sdssFlux[lo]*(1-t) + sdssFlux[hi]*t
      : 0;
  }
  return out;
}
```

Then normalise by the mean over the detector window (same as the baked SED path in
`simulateImage`, line ~930):
```js
const mean = out.reduce((s,v) => s+v, 0) / out.length || 1;
for (let i = 0; i < out.length; i++) out[i] /= mean;
```

---

## Step 5 — Inject as active spectrum

Store the fetched+resampled spectrum in `STATE`:
```js
STATE.fetchedSpectrum = {
  name: "NGC 1068 (SDSS)",
  wave: sdssWave,   // original SDSS grid
  flux: sdssFlux,
  redshift: z,
};
```

In `simulateImage()`, add a branch in the spectral profile section:
```js
if (STATE.fetchedSpectrum) {
  // already on the SDSS grid; resample to detector wavelengths
  spectralProfile = resampleSpectrum(
    STATE.fetchedSpectrum.wave,
    STATE.fetchedSpectrum.flux,
    wavelengths   // detector Å grid
  );
} else if (wantedSpec === "Baseline emission line" || ...) {
  // existing paths
}
```

---

## UI changes

In `buildImageOptionsUI()`, add a text input + button above the spectrum dropdown:

```html
<div class="fetch-row">
  <input type="text" id="obj-name" placeholder="e.g. NGC 1068" />
  <button id="obj-fetch">Fetch SDSS</button>
  <span id="obj-status"></span>
</div>
```

Event handler (sketch):
```js
document.getElementById("obj-fetch").addEventListener("click", async () => {
  const name = document.getElementById("obj-name").value.trim();
  if (!name) return;
  const status = document.getElementById("obj-status");
  status.textContent = "Resolving…";
  try {
    const { ra, dec, z } = await simbadResolve(name);       // Step 1
    status.textContent = `RA=${ra.toFixed(4)} Dec=${dec.toFixed(4)} z=${z?.toFixed(4)||"?"} — searching SDSS…`;
    const { plate, mjd, fiberid } = await sdssFind(ra, dec); // Step 2
    const { wave, flux } = await sdssSpectrum(plate, mjd, fiberid); // Step 3
    STATE.fetchedSpectrum = { name, wave, flux, redshift: z || 0 };
    status.textContent = `✓ ${name} loaded (${wave.length} pts)`;
    scheduleUpdate();
  } catch (e) {
    status.textContent = `✗ ${e.message}`;
    STATE.fetchedSpectrum = null;
  }
});
```

---

## Limitations

| Issue | Impact |
|---|---|
| SDSS footprint ~14 000 deg² (no full sky) | ~30% of objects won't be found |
| Coverage 3800–9200 Å only | UV instruments (FIREBall, SCWI, GALEX, UVEX) get nothing |
| SDSS fibre diameter 3″ | Extended sources may be truncated |
| `rvz_redshift` absent for some SIMBAD entries | Redshift must be entered manually |
| SDSS flux unit is 10⁻¹⁷ erg/cm²/s/Å | Needs conversion when comparing to ETC Signal slider |

---

## UV alternative (not implemented — CORS uncertain)

For UV coverage, IUE spectra (1150–3350 Å) are on MAST:
```
https://archive.stsci.edu/ssap/search2.php?id=IUE&targetname=NGC1068&SIZE=0.1&FORMAT=votable
```
Returns a VOTable with download links to FITS files. Would require:
1. VOTable XML parser in JS
2. Minimal FITS binary table parser in JS (~150 lines)
3. CORS verification (unknown — would need a live test)
