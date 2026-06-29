// compute.js — pure SNR computation extracted from index.html.
// Browser: loaded via <script src="compute.js">.
// Node:    const { computeObservation } = require('./compute.js');
// Regenerate: node scripts/sync_compute.js

function lin(n,a,b){const o=new Array(n);const d=(b-a)/(n-1);for(let i=0;i<n;i++)o[i]=a+d*i;return o}
function log(n,a,b){a=Math.max(a,1e-30);const la=Math.log10(a),lb=Math.log10(Math.max(b,a*1.0001));const o=new Array(n);const d=(lb-la)/(n-1);for(let i=0;i<n;i++)o[i]=10**(la+d*i);return o}
function space(n,a,b,xlog){return (xlog && a>=0) ? log(n, a===0?1e-4:a, b) : lin(n,a,b)}
function erf(x){const s=Math.sign(x);x=Math.abs(x);const a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;const t=1/(1+p*x);const y=1-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);return s*y}
function normSf(x,scale){if(scale<=0)return x>0?0:1;const z=x/scale;return 0.5*(1-erf(z/Math.SQRT2))}
function convert_ergs2LU(flux, wave_nm){const wave=wave_nm*1e-7;const E=6.62e-27*3e10/wave;const a=Math.PI/(180*3600);return flux/(E*a*a)}
function convert_LU2ergs(LU, wave_nm){const wave=wave_nm*1e-7;const E=6.62e-27*3e10/wave;const a=Math.PI/(180*3600);return LU*E*a*a}
function calculate_photon_counting_RN_noise(RN){
  const f = r=>{
    if (r<0.3) return 2*normSf(0.5, r);
    if (r>0.5) return r;
    const noise_low = 2*normSf(0.5, 0.3);
    const t = (r-0.3)/0.2;
    return noise_low*(1-t) + 0.5*t;
  };
  return typeof RN==="number" ? f(RN) : RN.map(f);
}

function computeObservation(p){

  // ## 1 — INPUT PARAMETERS (vectorised over the x-axis sweep) ##############
  const N = p.xArr.length;
  const arrify = v => (typeof v==="number")? Array(N).fill(v) : v.slice();
  let Signal=arrify(p.Signal), Sky=arrify(p.Sky), Dark_current=arrify(p.Dark_current),
      RN=arrify(p.RN), CIC_charge=arrify(p.CIC_charge), extra_background=arrify(p.extra_background),
      EM_gain=arrify(p.EM_gain), exposure_time=arrify(p.exposure_time),
      readout_time=arrify(p.readout_time), acquisition_time=arrify(p.acquisition_time),
      QE=arrify(p.QE), Throughput=arrify(p.Throughput), Atmosphere=arrify(p.Atmosphere),
      Collecting_area=arrify(p.Collecting_area), pixel_scale=arrify(p.pixel_scale),
      Spectral_resolution=arrify(p.Spectral_resolution), dispersion=arrify(p.dispersion),
      Slitwidth=arrify(p.Slitwidth), Slitlength=arrify(p.Slitlength),
      PSF_RMS_mask=arrify(p.PSF_RMS_mask), PSF_RMS_det=arrify(p.PSF_RMS_det),
      Size_source=arrify(p.Size_source), Line_width=arrify(p.Line_width),
      wavelength=arrify(p.wavelength), cosmic_ray_loss_per_sec=arrify(p.cosmic_ray_loss_per_sec),
      Bandwidth=arrify(p.Bandwidth), Throughput_FWHM=arrify(p.Throughput_FWHM),
      lambda_stack=arrify(p.lambda_stack);

  const IFS = !!p.IFS, spectro = !!p.spectrograph, counting_mode = !!p.counting_mode;
  const SNR_res = p.SNR_res || "per pix";
  const fsr = 2.35, arcsec2str = Math.pow(Math.PI/180/3600, 2);

  // ## 2 — SOURCE FLUX → CONTINUUM UNITS + APERTURE FRACTION ###############
  // Magnitudes (Signal > 1) are interpreted as UV mAB and converted to ergs.
  // Circular fibers get a π/4 disc-vs-square geometric correction.
  Signal = Signal.map(s => s>1 ? Math.pow(10, -(s-20.08)/2.5)*2.06e-16 : s);
  for(let i=0;i<N;i++){ if (Math.abs(Slitlength[i]-Slitwidth[i])<1e-12) Signal[i] *= Math.PI/4; }

  // Slit aperture fraction — fraction of the source PSF that passes through the slit (info.html §5.3)
  let flux_fraction = new Array(N).fill(1);
  for(let i=0;i<N;i++){
    const f1 = (1+erf(Slitlength[i]/(2*Math.SQRT2*PSF_RMS_mask[i]))) - 1;
    let f = f1;
    if (!IFS) f *= ((1+erf(Slitwidth[i]/(2*Math.SQRT2*PSF_RMS_mask[i]))) - 1);
    flux_fraction[i] = isFinite(f) ? f : 1;
  }
  const ff_slit = flux_fraction;

  // ## 3 — PSF & SOURCE/RESOLUTION-ELEMENT SIZES (in detector pixels) ######
  const PSF_lambda_pix = new Array(N);
  for(let i=0;i<N;i++) PSF_lambda_pix[i] = 10*wavelength[i]/Spectral_resolution[i]/dispersion[i];

  // σ_eff: quadratic convolution of source and detector PSF — the actual image size on the detector.
  // Used everywhere except "per pix" (single pixel, PSF irrelevant) and the IFS 2λpix special mode.
  const sigma_eff = new Array(N);
  for(let i=0;i<N;i++) sigma_eff[i] = Math.sqrt(Size_source[i]**2 + PSF_RMS_det[i]**2);

  const source_size = new Array(N), elem_size = new Array(N), pixels_total_source = new Array(N);
  // pix_nx / pix_spec / pix_ny: spatial pixels along one slicer, spectral pixels, IFS slicer count.
  // pix_ny = 1 for non-IFS. Display: nx × nλ (× ny if IFS).
  const pix_spat = new Array(N), pix_spec = new Array(N), pix_ny = new Array(N).fill(1);
  for(let i=0;i<N;i++){
    if (spectro){
      const seff = sigma_eff[i];
      const sspec = Math.max(1, Math.sqrt(PSF_lambda_pix[i]**2 + Math.pow(Math.min(Line_width[i],Bandwidth[i])/dispersion[i],2)));
      const spat_src = Math.max(Math.min(seff*fsr, Slitlength[i])/pixel_scale[i], 1);
      source_size[i] = spat_src * sspec;
      const nslices_src = IFS ? Math.ceil(Math.sqrt(seff**2+PSF_RMS_mask[i]**2)*fsr/Slitwidth[i]) : 1;
      pixels_total_source[i] = source_size[i] * nslices_src;
      const spat_elem = Math.ceil(Math.min(PSF_RMS_mask[i]*fsr, Slitlength[i])/pixel_scale[i]);
      const spec_elem = Math.ceil(Math.sqrt(Math.min(PSF_RMS_det[i]/pixel_scale[i], PSF_lambda_pix[i])**2 + Math.min(Line_width[i]/dispersion[i], PSF_lambda_pix[i])**2));
      const nslices_elem = IFS ? Math.ceil(PSF_RMS_mask[i]*fsr/Slitwidth[i]) : 1;
      elem_size[i] = spat_elem * spec_elem * nslices_elem;
      // defaults = res-elem components (overwritten in section 4 for other modes)
      pix_spat[i] = spat_elem;
      pix_spec[i] = spec_elem;
      pix_ny[i]   = nslices_elem;
    } else {
      const seff = sigma_eff[i];
      source_size[i] = Math.pow(seff*fsr/pixel_scale[i], 2);
      elem_size[i]   = Math.pow(PSF_RMS_det[i]*fsr/pixel_scale[i], 2);
      pixels_total_source[i] = source_size[i];
      const side = Math.ceil(seff*fsr/pixel_scale[i]);
      pix_spat[i] = side; pix_spec[i] = side; pix_ny[i] = 1;
    }
  }

  // ## 4 — INTEGRATION MODE → N_pix (info.html §5.2) ########################
  let number_pixels_used = new Array(N);
  if (SNR_res==="per pix"){
    number_pixels_used.fill(1);
    for(let i=0;i<N;i++){ pix_spat[i]=1; pix_spec[i]=1; pix_ny[i]=1; }
  } else if (SNR_res==="per Res elem"){
    for(let i=0;i<N;i++){
      number_pixels_used[i] = Math.ceil(elem_size[i]);
      // pix_spat/pix_spec/pix_ny already set to res-elem components above
    }
  } else if (SNR_res==="per Source"){
    for(let i=0;i<N;i++){
      number_pixels_used[i] = Math.ceil(pixels_total_source[i]);
      if (spectro){
        const seff = sigma_eff[i];
        const sspec = Math.max(1, Math.sqrt(PSF_lambda_pix[i]**2 + Math.pow(Math.min(Line_width[i],Bandwidth[i])/dispersion[i],2)));
        const spat_src = Math.max(Math.min(seff*fsr, Slitlength[i])/pixel_scale[i], 1);
        const nslices_src = IFS ? Math.ceil(Math.sqrt(seff**2+PSF_RMS_mask[i]**2)*fsr/Slitwidth[i]) : 1;
        pix_spat[i] = Math.ceil(spat_src);
        pix_spec[i] = Math.ceil(sspec);
        pix_ny[i]   = nslices_src;
      } else {
        const side = Math.ceil(sigma_eff[i]*fsr/pixel_scale[i]);
        pix_spat[i] = side; pix_spec[i] = side; pix_ny[i] = 1;
      }
    }
  } else {
    if (spectro && IFS){
      for(let i=0;i<N;i++){
        // IFS 2λpix mode uses its own geometry — keep Size_source as-is here
        const spatial_pix_per_slicer = Slitwidth[i]/pixel_scale[i];
        const spectral_pix_adaptive = Math.max(2, Math.pow(2, Math.floor(Math.log2(spatial_pix_per_slicer))));
        const nslices = Math.sqrt(Size_source[i]**2 + PSF_RMS_mask[i]**2)/Slitwidth[i];
        const pixels_spat_total = (1/pixel_scale[i])*nslices;
        pixels_total_source[i] = pixels_spat_total * spectral_pix_adaptive;
        number_pixels_used[i] = pixels_total_source[i];
        source_size[i] = (pixels_spat_total/nslices) * spectral_pix_adaptive;
        pix_spat[i] = Math.ceil(1/pixel_scale[i]);
        pix_spec[i] = Math.ceil(spectral_pix_adaptive);
        pix_ny[i]   = Math.ceil(nslices);
      }
    } else {
      for(let i=0;i<N;i++){
        number_pixels_used[i] = Math.ceil(pixels_total_source[i]);
        if (spectro){
          const seff = sigma_eff[i];
          const sspec = Math.max(1, Math.sqrt(PSF_lambda_pix[i]**2 + Math.pow(Math.min(Line_width[i],Bandwidth[i])/dispersion[i],2)));
          const spat_src = Math.max(Math.min(seff*fsr, Slitlength[i])/pixel_scale[i], 1);
          pix_spat[i] = Math.ceil(spat_src); pix_spec[i] = Math.ceil(sspec); pix_ny[i] = 1;
        } else {
          const side = Math.ceil(sigma_eff[i]*fsr/pixel_scale[i]);
          pix_spat[i] = side; pix_spec[i] = side; pix_ny[i] = 1;
        }
      }
    }
  }

  // ## 5 — EXCESS NOISE FACTOR + DARK/CIC SHOT NOISE #######################
  // ENF = 1 in photon-counting mode or no EM gain, √2 otherwise.
  const ENF = new Array(N);
  for(let i=0;i<N;i++) ENF[i] = (counting_mode || EM_gain[i]<2) ? 1 : 2;

  const Dark_current_f = new Array(N), Dark_current_noise = new Array(N), CIC_noise = new Array(N);
  for(let i=0;i<N;i++){
    Dark_current_f[i] = Dark_current[i]*exposure_time[i]/3600;
    Dark_current_noise[i] = Math.sqrt(Dark_current_f[i]*ENF[i]);
    CIC_noise[i] = Math.sqrt(CIC_charge[i]*ENF[i]);
  }

  // ## 6 — EFFECTIVE AREA = QE × Throughput × Atm × A_tel #################
  const Photon_fraction_kept = new Array(N).fill(1), RN_fraction_kept = new Array(N).fill(1);
  const QE_eff = new Array(N), effective_area = new Array(N);
  for(let i=0;i<N;i++){
    QE_eff[i] = Photon_fraction_kept[i]*QE[i];
    effective_area[i] = QE_eff[i]*Throughput[i]*Atmosphere[i]*(Collecting_area[i]*100*100);
  }

  const cosmic_ray_loss = new Array(N);
  for(let i=0;i<N;i++) cosmic_ray_loss[i] = Math.min(cosmic_ray_loss_per_sec[i]*(exposure_time[i]+readout_time[i]/2), 1);

  const sourceSizeAfter = new Array(N), slitSizeAfter = new Array(N);
  for(let i=0;i<N;i++){
    if (SNR_res==="per Source per 2λpix" && IFS && spectro){
      let slicer_eff;
      if (Slitwidth[i]>=1.0) slicer_eff = 1.38;
      else if (Slitwidth[i]>=0.5) slicer_eff = Math.max(0.69, Size_source[i]);
      else slicer_eff = Size_source[i];
      sourceSizeAfter[i] = Size_source[i]*slicer_eff;
      slitSizeAfter[i]   = Size_source[i]*slicer_eff;
    } else {
      // Use σ_eff (source ⊛ PSF_det) so point sources are correctly spread over the PSF footprint.
      // fsr=2.35 converts σ → FWHM for comparison with physical slit dimensions.
      const seff = sigma_eff[i];
      const along  = Math.min(seff*fsr, Slitlength[i]);
      const across = Math.min(seff*fsr, Slitwidth[i]);
      sourceSizeAfter[i] = along * across;
      slitSizeAfter[i]   = along * (IFS ? Math.max(seff*fsr, Slitwidth[i]) : Slitwidth[i]);
    }
  }

  const factor_CU2el = new Array(N), factor_CU2el_sky = new Array(N);
  for(let i=0;i<N;i++){
    if (spectro){
      if (SNR_res==="per Source per 2λpix" && IFS){
        const spatial_pix_per_slicer = Slitwidth[i]/pixel_scale[i];
        const spectral_bin_pixels = Math.max(2, Math.pow(2, Math.floor(Math.log2(spatial_pix_per_slicer))));
        const spectral_bin_A = spectral_bin_pixels * dispersion[i]*10.0;
        factor_CU2el[i]     = effective_area[i]*arcsec2str*sourceSizeAfter[i]*spectral_bin_A/pixels_total_source[i];
        factor_CU2el_sky[i] = effective_area[i]*arcsec2str*slitSizeAfter[i]  *spectral_bin_A/pixels_total_source[i];
      } else {
        // Divide by source_size (pixels in one slicer/slit spatial×spectral footprint), NOT pixels_total_source.
        // pixels_total_source includes the IFS nslices factor which belongs only in number_pixels_used (noise),
        // not in the per-pixel flux conversion — otherwise IFS mode artificially divides the signal by nslices.
        const lw = Math.min(Line_width[i], Bandwidth[i]);
        factor_CU2el[i]     = effective_area[i]*arcsec2str*lw*sourceSizeAfter[i]/source_size[i];
        factor_CU2el_sky[i] = effective_area[i]*arcsec2str*Math.max(lw, dispersion[i])*slitSizeAfter[i]/source_size[i];
      }
    } else {
      factor_CU2el[i] = pixel_scale[i]*pixel_scale[i]*Throughput_FWHM[i];
      factor_CU2el_sky[i] = factor_CU2el[i];
    }
  }

  const N_images = new Array(N), N_images_true = new Array(N);
  for(let i=0;i<N;i++){
    N_images[i] = acquisition_time[i]*3600/(exposure_time[i]+readout_time[i]);
    N_images_true[i] = N_images[i]*(1-cosmic_ray_loss[i]);
  }

  // ## 7 — SIGNAL & SKY IN ELECTRONS, RN, ADDITIONAL BACKGROUND ############
  const sky = new Array(N), Sky_noise = new Array(N), Signal_LU = new Array(N), Signal_el = new Array(N), signal_noise = new Array(N);
  for(let i=0;i<N;i++){
    const Sky_CU_i = convert_ergs2LU(Sky[i], wavelength[i]);
    sky[i] = Sky_CU_i*factor_CU2el_sky[i]*exposure_time[i];
    Sky_noise[i] = Math.sqrt(sky[i]*ENF[i]);
    Signal_LU[i] = convert_ergs2LU(Signal[i], wavelength[i]);
    Signal_el[i] = Signal_LU[i]*factor_CU2el[i]*exposure_time[i]*ff_slit[i];
    signal_noise[i] = Math.sqrt(Signal_el[i]*ENF[i]);
  }

  // Read noise after EM-gain division + photon-counting analytic miscount model (info.html §5.5)
  const RN_after_gain = new Array(N);
  for(let i=0;i<N;i++) RN_after_gain[i] = RN[i]*RN_fraction_kept[i]/EM_gain[i];
  const RN_final = calculate_photon_counting_RN_noise(RN_after_gain);

  const Additional_background = new Array(N), Additional_background_noise = new Array(N);
  for(let i=0;i<N;i++){
    Additional_background[i] = extra_background[i]/3600*exposure_time[i];
    Additional_background_noise[i] = Math.sqrt(Additional_background[i]*ENF[i]);
  }

  // ## 8 — TOTAL SNR (info.html §5.4) ######################################
  // κ = √(N_pix × N_λ × N_stack)  ;  signal scales as κ²  ;  noise as κ·√(Σσ²)
  const N_resol_element_A = spectro ? Array(N).fill(1) : lambda_stack;
  const factor = new Array(N), Signal_resolution = new Array(N), Total_noise_final = new Array(N), SNR = new Array(N);
  for(let i=0;i<N;i++){
    factor[i] = Math.sqrt(number_pixels_used[i])*Math.sqrt(N_resol_element_A[i])*Math.sqrt(N_images_true[i]);
    Signal_resolution[i] = Signal_el[i]*factor[i]*factor[i];
    const inside = signal_noise[i]**2 + Dark_current_noise[i]**2 + Additional_background_noise[i]**2 + Sky_noise[i]**2 + CIC_noise[i]**2 + RN_final[i]**2;
    Total_noise_final[i] = factor[i]*Math.sqrt(inside);
    SNR[i] = Signal_resolution[i]/Total_noise_final[i];
  }

  const noises_per_exp = new Array(N), noises = new Array(N), electrons_per_pix = new Array(N);
  for(let i=0;i<N;i++){
    const sp = Math.sqrt(number_pixels_used[i]);
    noises_per_exp[i] = [
      sp*signal_noise[i], sp*Dark_current_noise[i], sp*Sky_noise[i],
      sp*RN_final[i], sp*CIC_noise[i], sp*Additional_background_noise[i],
      sp*Math.sqrt(Signal_el[i])
    ];
    noises[i] = [
      signal_noise[i]*factor[i], Dark_current_noise[i]*factor[i], Sky_noise[i]*factor[i],
      RN_final[i]*factor[i], CIC_noise[i]*factor[i], Additional_background_noise[i]*factor[i],
      Signal_resolution[i]
    ];
    electrons_per_pix[i] = [Signal_el[i], Dark_current_f[i], sky[i], 0*RN_final[i], CIC_charge[i], Additional_background[i]];
  }

  // ## 9 — SURFACE BRIGHTNESS LIMIT @ SNR=5 (info.html §5.6) ##############
  const n_sigma = 5;
  const SB_lim_per_pix = new Array(N), SB_lim_per_res = new Array(N), SB_lim_per_source = new Array(N);
  for(let i=0;i<N;i++){
    const sn_nf = signal_noise[i]*factor[i], Tnf = Total_noise_final[i];
    const val = (n_sigma**2 * ENF[i] + n_sigma * Math.sqrt(4*Tnf*Tnf - 4*sn_nf*sn_nf + ENF[i]**2 * n_sigma**2))/2;
    const lu_per_e = Signal_LU[i]/Signal_resolution[i];
    const sig_ergs = convert_LU2ergs(val*lu_per_e, wavelength[i]);
    SB_lim_per_pix[i] = sig_ergs;
    SB_lim_per_res[i] = sig_ergs/elem_size[i];
    SB_lim_per_source[i] = sig_ergs/source_size[i];
  }

  return { x: p.xArr, N, noises_per_exp, noises, electrons_per_pix,
    Signal_el, Dark_current_f, sky, RN_final, CIC_charge, Additional_background,
    SNR, Total_noise_final, number_pixels_used, source_size, elem_size,
    pix_spat, pix_spec, pix_ny,
    SB_lim_per_pix, SB_lim_per_res, SB_lim_per_source, factor, Signal_resolution };
}

if (typeof module !== 'undefined') module.exports = { computeObservation, erf, convert_ergs2LU, convert_LU2ergs };
