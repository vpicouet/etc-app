# etc-app

A JavaScript / D3 port of the Generic ETC ([vpicouet/generic-etc](https://github.com/vpicouet/generic-etc)) that runs entirely in the browser.

**Live app:** https://vpicouet.github.io/etc-app/

Loads the instrument database directly from the shared [Google Sheet](https://docs.google.com/spreadsheets/d/1Ox0uxEm2TfgzYA6ivkTpU4xrmN5vO5kmnUPdCSt73uU/edit). All physics is computed client-side.

## What this includes

- SNR calculator with the same 4-panel plot as the notebook (noise budget, contributions stack, SNR stack, surface-brightness limits)
- All instrument parameters as sliders, grouped in accordions
- Any parameter usable as the x-axis to study SNR evolution
- 4 SNR modes: per pixel / per resolution element / per source / per source × 2λpix

## What this does **not** include

This is the SNR calculator only. The image / IFU cube simulator and the data pipeline (spectra, cubes, λ-dependent throughput and atmospheric curves) are **not** ported — use the original notebook for those.

## Local dev

```
git clone https://github.com/vpicouet/etc-app.git
cd etc-app
python3 -m http.server 8000
# open http://127.0.0.1:8000/
```

`file://` won't work because Google Sheets CORS doesn't echo `Origin: null`.

## License

Same as the upstream notebook.
