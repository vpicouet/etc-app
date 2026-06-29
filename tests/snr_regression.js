#!/usr/bin/env node
/**
 * SNR regression test for the ETC app.
 * Uses compute.js (synced from index.html via scripts/sync_compute.js).
 * Checks that SNR_max is within 10% of the baseline values captured 2026-06-06.
 *
 * Run:  node tests/snr_regression.js
 * Exit: 0 = all pass, 1 = regression detected.
 */
"use strict";
const fs   = require("fs");
const path = require("path");
const { computeObservation } = require("../compute.js");

// ---------------------------------------------------------------------------
// Reference parameters — SCWI SPEC and SCWI qccd2 (from saved JSON 2026-06-06)
// ---------------------------------------------------------------------------
const BASE = {
  Signal: 5.6e-19, Size_source: 9, Sky: 2.28e-19, Line_width: 0.85,
  Atmosphere: 0.4, acquisition_time: 90, wavelength: 205, lambda_stack: 1,
  Collecting_area: 0.177, pixel_scale: 1.5, Throughput: 0.23,
  PSF_RMS_det: 1.3, PSF_RMS_mask: 0.2, Throughput_FWHM: 400,
  Spectral_resolution: 1500, Slitwidth: 5, Slitlength: 120,
  dispersion: 0.7, Bandwidth: 160, QE: 0.7,
  IFS: true, spectrograph: true, counting_mode: false,
  SNR_res: "per Res elem",
};

const INSTRUMENTS = [
  {
    name: "SCWI SPEC",
    params: {
      ...BASE,
      RN: 33, Dark_current: 0.7, extra_background: 0.1,
      cosmic_ray_loss_per_sec: 0.005, EM_gain: 1500, CIC_charge: 0.015,
      readout_time: 5, exposure_time: 50,
    },
    // Baseline captured 2026-06-06 — update only after deliberate code change
    expected_snr_max: 0.364,
  },
  {
    name: "SCWI qccd2",
    params: {
      ...BASE,
      RN: 0.0124, Dark_current: 0.1182, extra_background: 0.01,
      cosmic_ray_loss_per_sec: 0.0001, EM_gain: 1, CIC_charge: 0.01,
      readout_time: 13, exposure_time: 120,
    },
    expected_snr_max: 1.417,
  },
];

const TOLERANCE = 0.10; // 10%
const N_POINTS  = 60;

function logspace(n, a, b) {
  const la = Math.log10(a), lb = Math.log10(b);
  return Array.from({length: n}, (_, i) => Math.pow(10, la + (lb - la) * i / (n - 1)));
}

// ---------------------------------------------------------------------------
// Run tests
// ---------------------------------------------------------------------------
let allPassed = true;
const results = [];

for (const { name, params, expected_snr_max } of INSTRUMENTS) {
  // x-axis = exposure_time, swept from 1 to 3005s (matching app defaults)
  const xKey = "exposure_time";
  const xArr = logspace(N_POINTS, 1, 3005);
  // Mirror the app: the swept parameter becomes an array, all others stay scalar
  const p = { ...params, Signal_in: params.Signal };
  for (const k of Object.keys(params)) p[k] = (k === xKey) ? xArr : params[k];
  p.xArr = xArr;

  let res;
  try {
    res = computeObservation(p);
  } catch (e) {
    console.error(`[FAIL] ${name}: computeObservation threw: ${e.message}`);
    allPassed = false;
    results.push({ instrument: name, error: e.message, pass: false });
    continue;
  }

  let snrMax = -Infinity, snrMaxX = null;
  for (let i = 0; i < res.SNR.length; i++) {
    if (isFinite(res.SNR[i]) && res.SNR[i] > snrMax) {
      snrMax = res.SNR[i];
      snrMaxX = res.x[i];
    }
  }

  const ratio = snrMax / expected_snr_max;
  const pass  = Math.abs(ratio - 1) <= TOLERANCE;
  if (!pass) allPassed = false;

  console.log(
    `[${pass ? "PASS" : "FAIL"}] ${name}: SNR_max=${snrMax.toFixed(3)}` +
    ` (expected ${expected_snr_max}, ratio=${ratio.toFixed(3)}, at t_exp=${snrMaxX?.toFixed(1)}s)`
  );
  results.push({ instrument: name, snr_max: Math.round(snrMax*1000)/1000,
                 expected: expected_snr_max, ratio: Math.round(ratio*1000)/1000, pass });
}

// Write machine-readable result for the GitHub Action
fs.writeFileSync(
  path.join(__dirname, "snr_regression_result.json"),
  JSON.stringify(results, null, 2)
);

if (!allPassed) {
  console.error("\nREGRESSION DETECTED — SNR changed by more than 10%");
  process.exit(1);
} else {
  console.log("\nAll SNR regression checks passed.");
  process.exit(0);
}
