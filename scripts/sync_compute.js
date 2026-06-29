#!/usr/bin/env node
// sync_compute.js — regenerate compute.js from index.html.
// Run after editing the SNR computation in index.html:
//   node scripts/sync_compute.js
"use strict";
const fs = require("fs"), path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const lines = html.split("\n");

// Find the script open tag line index
const scriptOpen = lines.findIndex(l => l.trim() === "<script>");
if (scriptOpen < 0) { console.error("No <script> found"); process.exit(1); }

// Find helpers block: look for 'function lin(' line
const helpersStart = lines.findIndex((l, i) => i > scriptOpen && l.startsWith("function lin("));
// find calculate_photon_counting_RN_noise end (next blank line after its closing })
let helpersEnd = helpersStart;
let braces = 0, inFunc = false;
for (let i = helpersStart; i < lines.length; i++) {
  const l = lines[i];
  for (const c of l) { if (c==='{') { braces++; inFunc=true; } else if (c==='}') braces--; }
  // calculate_photon_counting_RN_noise ends when braces return to 0 after opening
  if (inFunc && braces === 0) {
    // keep going until we hit fmtNum (first non-compute helper)
    if (lines[i+1] && lines[i+1].startsWith("function fmtNum")) { helpersEnd = i; break; }
  }
}

// Find computeObservation block
const computeStart = lines.findIndex(l => l.startsWith("function computeObservation("));
braces = 0; inFunc = false;
let computeEnd = computeStart;
for (let i = computeStart; i < lines.length; i++) {
  const l = lines[i];
  for (const c of l) { if (c==='{') { braces++; inFunc=true; } else if (c==='}') braces--; }
  if (inFunc && braces === 0) { computeEnd = i; break; }
}

const helpers = lines.slice(helpersStart, helpersEnd + 1).join("\n");
const compute  = lines.slice(computeStart,  computeEnd  + 1).join("\n");

const out =
  "// compute.js — pure SNR computation extracted from index.html.\n" +
  "// Browser: loaded via <script src=\"compute.js\">.\n" +
  "// Node:    const { computeObservation } = require('./compute.js');\n" +
  "// Regenerate: node scripts/sync_compute.js\n\n" +
  helpers + "\n\n" +
  compute + "\n\n" +
  "if (typeof module !== 'undefined') " +
  "module.exports = { computeObservation, erf, convert_ergs2LU, convert_LU2ergs };\n";

fs.writeFileSync(path.join(ROOT, "compute.js"), out);
console.log(`compute.js written (${out.length} chars, helpers L${helpersStart+1}–${helpersEnd+1}, compute L${computeStart+1}–${computeEnd+1})`);
