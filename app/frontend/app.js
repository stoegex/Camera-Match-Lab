/**
 * app.js – Camera Match Lab frontend orchestration
 * Manages all 6 workflow steps and communicates with Flask backend.
 */
const App = (() => {
  // ── State ──────────────────────────────────────────────
  const state = {
    mode: null,          // 'single' | 'master'
    sourceLog: null,
    targetLog: null,
    allProfiles: [],

    // pairs: [{sourceImgId, targetImgId, sourceWarpedId, targetWarpedId,
    //          sourcePatches, targetPatches, sourceName, targetName}]
    pairs: [],
    currentPairIdx: 0,    // which pair we're configuring right now
    currentRole: null,    // 'source' | 'target' (within corner/patch step)

    // corner marking per image
    // cornerState[img_id] = {corners: [[x,y]*4], imgSrc, displayW, displayH}
    cornerState: {},
    currentCornerImg: null,   // img_id being marked

    // patch tuning
    currentPatchWarpedId: null,
    currentPatchCenters: [],
    defaultPatchCenters: [],
    draggingIdx: -1,

    lutName: 'CameraMatch',
    step: 1,
  };

  // ── Helpers ────────────────────────────────────────────
  function $ (id) { return document.getElementById(id); }
  function show (el) { if (typeof el === 'string') el = $(el); el?.classList.remove('hidden'); }
  function hide (el) { if (typeof el === 'string') el = $(el); el?.classList.add('hidden'); }

  async function api (method, path, body) {
    const opts = { method, headers: {} };
    if (body instanceof FormData) {
      opts.body = body;
    } else if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || res.statusText);
    return json;
  }

  // ── Navigation ─────────────────────────────────────────
  function goStep (n) {
    state.step = n;
    document.querySelectorAll('.step-panel').forEach(p => p.classList.remove('active'));
    $(`step-${n}`)?.classList.add('active');
    updateStepNav(n);
  }

  function updateStepNav (current) {
    document.querySelectorAll('.step-dot').forEach(dot => {
      const s = parseInt(dot.dataset.step);
      dot.classList.remove('active', 'done');
      if (s < current) dot.classList.add('done');
      else if (s === current) dot.classList.add('active');
    });
  }

  // ── STEP 1 ─────────────────────────────────────────────
  function selectMode (m) {
    state.mode = m;
    state.pairs = [];
    state.currentPairIdx = 0;
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    $(m === 'single' ? 'btnSingle' : 'btnMaster').classList.add('selected');

    setTimeout(() => {
      buildImageSlots();
      goStep(2);
    }, 180);
  }

  // ── STEP 2 ─────────────────────────────────────────────
  function buildImageSlots () {
    const container = $('imageSlots');
    container.innerHTML = '';

    // Ensure at least 1 pair
    if (state.pairs.length === 0) state.pairs.push(makePair());

    state.pairs.forEach((pair, idx) => {
      const group = document.createElement('div');
      group.className = 'pair-group';
      group.dataset.pairIdx = idx;

      const label = state.mode === 'master'
        ? `<div class="pair-group-label"><span class="pair-num">${idx + 1}</span>Szenenpaar ${idx + 1}</div>`
        : '';

      group.innerHTML = `${label}<div class="pair-slots-row">
        ${makeSlotHTML(idx, 'source')}
        ${makeSlotHTML(idx, 'target')}
      </div>`;
      container.appendChild(group);
    });

    $('masterAddBtn')?.classList.toggle('hidden', state.mode !== 'master');
    wireDropSlots();
    checkStep2Next();
  }

  function makePair () {
    return { sourceImgId: null, targetImgId: null,
             sourceWarpedId: null, targetWarpedId: null,
             sourcePatches: null, targetPatches: null,
             sourceName: '', targetName: '' };
  }

  function makeSlotHTML (pairIdx, role) {
    const label = role === 'source' ? 'QUELL-Bild (Source)' : 'ZIEL-Bild (Target)';
    const hint = role === 'source' ? 'z.B. Leica, BMPCC …' : 'z.B. Lumix, RED …';
    return `
      <div class="drop-slot" id="slot-${pairIdx}-${role}"
           data-pair="${pairIdx}" data-role="${role}"
           onclick="App._slotClick(${pairIdx},'${role}')">
        <div class="drop-slot-inner">
          <div class="drop-slot-role ${role}">${label}</div>
          <svg class="drop-slot-icon" width="32" height="32" viewBox="0 0 32 32" fill="none">
            <path d="M16 4v16M8 12l8-8 8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.5"/>
            <rect x="4" y="22" width="24" height="6" rx="2" stroke="currentColor" stroke-width="1.5" opacity="0.3"/>
          </svg>
          <span class="drop-slot-label" id="slot-lbl-${pairIdx}-${role}">Klicken oder ziehen</span>
          <span style="font-size:11px;color:var(--text-3)">${hint}</span>
        </div>
        <img class="drop-slot-thumb" id="slot-thumb-${pairIdx}-${role}" src="" style="display:none" alt="" draggable="false"/>
      </div>`;
  }

  function wireDropSlots () {
    document.querySelectorAll('.drop-slot').forEach(slot => {
      slot.addEventListener('dragover', e => { e.preventDefault(); slot.classList.add('dragover'); });
      slot.addEventListener('dragleave', () => slot.classList.remove('dragover'));
      slot.addEventListener('drop', e => {
        e.preventDefault();
        slot.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) uploadToSlot(parseInt(slot.dataset.pair), slot.dataset.role, file);
      });
    });
  }

  function _slotClick (pairIdx, role) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.tif,.tiff,.jpg,.jpeg,.png';
    input.onchange = () => { if (input.files[0]) uploadToSlot(pairIdx, role, input.files[0]); };
    input.click();
  }

  async function uploadToSlot (pairIdx, role, file) {
    const slotEl = $(`slot-${pairIdx}-${role}`);
    const lblEl = $(`slot-lbl-${pairIdx}-${role}`);
    const thumbEl = $(`slot-thumb-${pairIdx}-${role}`);

    lblEl.textContent = '⏳ Wird geladen…';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await api('POST', '/api/upload', fd);

      const pair = state.pairs[pairIdx];
      if (role === 'source') {
        pair.sourceImgId = res.img_id;
        pair.sourceName = res.filename;
      } else {
        pair.targetImgId = res.img_id;
        pair.targetName = res.filename;
      }

      // Store display metadata in cornerState
      state.cornerState[res.img_id] = {
        corners: [],
        imgSrc: res.preview,
        displayW: res.width,
        displayH: res.height,
      };

      // Show preview
      thumbEl.src = res.preview;
      thumbEl.style.display = 'block';
      slotEl.classList.add('loaded');
      lblEl.textContent = file.name;

    } catch (err) {
      lblEl.textContent = `Fehler: ${err.message}`;
    }
    checkStep2Next();
  }

  function checkStep2Next () {
    const allLoaded = state.pairs.every(p => p.sourceImgId && p.targetImgId);
    $('step2Next').disabled = !allLoaded;
  }

  function addMasterPair () {
    state.pairs.push(makePair());
    buildImageSlots();
  }

  function step2Next () {
    loadLogProfiles();
    goStep(3);
  }

  // ── STEP 3 ─────────────────────────────────────────────
  async function loadLogProfiles () {
    if (state.allProfiles.length) { renderLogLists(); return; }
    try {
      const profiles = await api('GET', '/api/log-profiles');
      state.allProfiles = profiles;
      renderLogLists();
    } catch (e) {
      console.error('Could not load log profiles', e);
    }
  }

  function renderLogLists () {
    renderList('sourceList', state.allProfiles, 'source');
    renderList('targetList', state.allProfiles, 'target');
  }

  function renderList (listId, items, role) {
    const ul = $(listId);
    ul.innerHTML = '';
    const selected = role === 'source' ? state.sourceLog : state.targetLog;
    items.forEach(name => {
      const li = document.createElement('li');
      li.textContent = name;
      if (name === selected) li.classList.add('selected');
      li.onclick = () => selectLog(role, name);
      ul.appendChild(li);
    });
  }

  function filterLog (role, query) {
    const filtered = state.allProfiles.filter(p =>
      p.toLowerCase().includes(query.toLowerCase()));
    const listId = role === 'source' ? 'sourceList' : 'targetList';
    renderListFiltered(listId, filtered, role);
  }

  function renderListFiltered (listId, items, role) {
    const ul = $(listId);
    ul.innerHTML = '';
    const selected = role === 'source' ? state.sourceLog : state.targetLog;
    items.forEach(name => {
      const li = document.createElement('li');
      li.textContent = name;
      if (name === selected) li.classList.add('selected');
      li.onclick = () => selectLog(role, name);
      ul.appendChild(li);
    });
  }

  function selectLog (role, name) {
    if (role === 'source') {
      state.sourceLog = name;
      $('sourceSelected').textContent = name;
      $('sourceSelected').classList.add('set');
    } else {
      state.targetLog = name;
      $('targetSelected').textContent = name;
      $('targetSelected').classList.add('set');
    }
    renderLogLists();
    $('step3Next').disabled = !(state.sourceLog && state.targetLog);
  }

  function step3Next () {
    // Build lut name from first pair
    const p = state.pairs[0];
    const sn = p.sourceName ? p.sourceName.replace(/\.[^.]+$/, '') : 'Source';
    const tn = p.targetName ? p.targetName.replace(/\.[^.]+$/, '') : 'Target';
    state.lutName = `${sn}_to_${tn}_Match`;

    // Reset corner progress for all pairs
    state.pairs.forEach(p => { p.sourceWarpedId = null; p.targetWarpedId = null; });
    startCornerFlow();
  }

  // ── STEP 4 – CORNER MARKING ────────────────────────────
  // We step through: pair[0].source → pair[0].target → pair[1].source → ...
  // After all images are done, go to patch tuning flow.

  let cornerQueue = [];  // [{pairIdx, role, imgId}]
  let cornerQueuePos = 0;

  function startCornerFlow () {
    cornerQueue = [];
    state.pairs.forEach((p, i) => {
      cornerQueue.push({ pairIdx: i, role: 'source', imgId: p.sourceImgId });
      cornerQueue.push({ pairIdx: i, role: 'target', imgId: p.targetImgId });
    });
    cornerQueuePos = 0;
    loadCornerStep();
  }

  function loadCornerStep () {
    if (cornerQueuePos >= cornerQueue.length) {
      startPatchFlow();
      return;
    }
    const { pairIdx, role, imgId } = cornerQueue[cornerQueuePos];
    const cs = state.cornerState[imgId];
    cs.corners = [];

    const roleName = role === 'source' ? 'Quell' : 'Ziel';
    const pairName = state.mode === 'master' ? ` (Paar ${pairIdx + 1})` : '';
    $('step4Title').textContent = `${roleName}-Bild Ecken markieren${pairName}`;
    $('step4Next').disabled = true;
    state.currentCornerImg = imgId;

    goStep(4);
    setupCornerCanvas(cs);
  }

  function setupCornerCanvas (cs) {
    const img = $('cornerImg');
    const canvas = $('cornerCanvas');
    img.src = cs.imgSrc;
    img.onload = () => { resizeCanvas(canvas, img); drawCorners(canvas, cs.corners); };
    // Reset dot indicators
    for (let i = 0; i < 4; i++) {
      const d = $(`cdot${i}`);
      d.classList.remove('set', 'active');
      if (i === 0) d.classList.add('active');
    }

    canvas.onclick = (e) => {
      if (cs.corners.length >= 4) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (e.clientX - rect.left) * scaleX;
      const y = (e.clientY - rect.top) * scaleY;

      // Map canvas px → Normalized fraction (0.0 to 1.0) relative to image
      const imgEl = $('cornerImg');
      const rendered = getRenderedImageRect(imgEl);
      if (!rendered) return;

      const normX = (x - rendered.x) / rendered.rw;
      const normY = (y - rendered.y) / rendered.rh;

      // Clamp to image edges
      const cx = Math.max(0, Math.min(1, normX));
      const cy = Math.max(0, Math.min(1, normY));

      cs.corners.push([cx, cy]);

      const idx = cs.corners.length - 1;
      const d = $(`cdot${idx}`);
      d.classList.replace('active', 'set');
      if (idx < 3) $(`cdot${idx + 1}`)?.classList.add('active');

      if (cs.corners.length === 4) $('step4Next').disabled = false;
      drawCorners(canvas, cs.corners, rendered);
    };
  }

  function getRenderedImageRect (imgEl) {
    const nw = imgEl.naturalWidth, nh = imgEl.naturalHeight;
    if (!nw || !nh) return null;
    const ew = imgEl.clientWidth, eh = imgEl.clientHeight;
    const scale = Math.min(ew / nw, eh / nh);
    const rw = nw * scale, rh = nh * scale;
    const x = (ew - rw) / 2, y = (eh - rh) / 2;
    return { x, y, scale, rw, rh };
  }

  function resizeCanvas (canvas, imgEl) {
    canvas.width = imgEl.clientWidth;
    canvas.height = imgEl.clientHeight;
  }

  function drawCorners (canvas, corners, rendered) {
    if (!rendered) {
      const imgEl = $('cornerImg');
      rendered = getRenderedImageRect(imgEl);
    }
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!corners.length || !rendered) return;

    // Map normalized fraction (0.0 - 1.0) → canvas px
    const toCanvas = ([nx, ny]) => [
      nx * rendered.rw + rendered.x,
      ny * rendered.rh + rendered.y,
    ];

    const pts = corners.map(toCanvas);
    ctx.strokeStyle = '#52d48a';
    ctx.lineWidth = 2;
    ctx.fillStyle = '#52d48a';

    ctx.beginPath();
    pts.forEach(([cx, cy], i) => i === 0 ? ctx.moveTo(cx, cy) : ctx.lineTo(cx, cy));
    if (corners.length === 4) ctx.closePath();
    ctx.stroke();

    pts.forEach(([cx, cy], i) => {
      ctx.beginPath();
      ctx.arc(cx, cy, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#000';
      ctx.font = 'bold 9px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(i + 1, cx, cy);
      ctx.fillStyle = '#52d48a';
    });
  }

  function resetCorners () {
    const cs = state.cornerState[state.currentCornerImg];
    cs.corners = [];
    for (let i = 0; i < 4; i++) {
      const d = $(`cdot${i}`);
      d.classList.remove('set', 'active');
      if (i === 0) d.classList.add('active');
    }
    $('step4Next').disabled = true;
    const canvas = $('cornerCanvas');
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  }

  async function step4Next () {
    $('step4Next').disabled = true;
    $('step4Next').textContent = '⏳ Wird verarbeitet…';

    const { pairIdx, role, imgId } = cornerQueue[cornerQueuePos];
    const cs = state.cornerState[imgId];

    try {
      const res = await api('POST', '/api/warp', { img_id: imgId, corners: cs.corners });
      const pair = state.pairs[pairIdx];
      if (role === 'source') {
        pair.sourceWarpedId = res.warped_id;
        pair.sourceDefaultPatches = res.patch_centers;
        pair.sourceWarpedSrc = res.preview;
        pair.sourceWarpedW = res.width;
        pair.sourceWarpedH = res.height;
      } else {
        pair.targetWarpedId = res.warped_id;
        pair.targetDefaultPatches = res.patch_centers;
        pair.targetWarpedSrc = res.preview;
      }
    } catch (err) {
      alert(`Warp-Fehler: ${err.message}`);
      $('step4Next').disabled = false;
      $('step4Next').textContent = 'Ecken bestätigen →';
      return;
    }

    $('step4Next').textContent = 'Ecken bestätigen →';
    cornerQueuePos++;
    loadCornerStep();
  }

  function cornerBack () {
    if (cornerQueuePos > 0) {
      cornerQueuePos--;
      loadCornerStep();
    } else {
      goStep(3);
    }
  }

  // ── STEP 5 – PATCH TUNING ──────────────────────────────
  let patchQueue = []; // [{pairIdx, role, warpedId, warpedSrc, defaultPatches}]
  let patchQueuePos = 0;

  function startPatchFlow () {
    patchQueue = [];
    state.pairs.forEach((p, i) => {
      patchQueue.push({ pairIdx: i, role: 'source', warpedId: p.sourceWarpedId,
                        warpedSrc: p.sourceWarpedSrc, defaultPatches: p.sourceDefaultPatches });
      patchQueue.push({ pairIdx: i, role: 'target', warpedId: p.targetWarpedId,
                        warpedSrc: p.targetWarpedSrc, defaultPatches: p.targetDefaultPatches });
    });
    patchQueuePos = 0;
    loadPatchStep();
  }

  function loadPatchStep () {
    if (patchQueuePos >= patchQueue.length) {
      generateLUT();
      return;
    }
    const { pairIdx, role, warpedId, warpedSrc, defaultPatches } = patchQueue[patchQueuePos];
    const roleName = role === 'source' ? 'Quell' : 'Ziel';
    const pairName = state.mode === 'master' ? ` (Paar ${pairIdx + 1})` : '';
    $('step5Title').textContent = `${roleName}-Bild Patches feinjustieren${pairName}`;

    const isLast = patchQueuePos === patchQueue.length - 1;
    $('step5NextLabel').textContent = isLast ? 'LUT generieren →' : 'Weiter →';

    state.currentPatchWarpedId = warpedId;
    state.defaultPatchCenters = defaultPatches.map(([x, y]) => [x, y]);
    state.currentPatchCenters = defaultPatches.map(([x, y]) => [x, y]);

    goStep(5);
    setupPatchCanvas(warpedSrc, state.currentPatchCenters);
  }

  function setupPatchCanvas (imgSrc, centers) {
    const img = $('patchImg');
    const canvas = $('patchCanvas');
    img.src = imgSrc;
    img.onload = () => {
      resizeCanvas(canvas, img);
      drawPatches(canvas, centers);
    };

    let dragging = -1;
    canvas.onmousedown = (e) => {
      const pos = getCanvasPos(canvas, e);
      const rendered = getRenderedImageRect(img);
      if (!rendered) return;
      // convert canvas pos → image-space
      const ix = (pos.x - rendered.x) / rendered.scale;
      const iy = (pos.y - rendered.y) / rendered.scale;
      dragging = -1;
      // Find nearest patch (within 15px image-space)
      let minD = 20;
      centers.forEach(([cx, cy], i) => {
        const d = Math.hypot(cx - ix, cy - iy);
        if (d < minD) { minD = d; dragging = i; }
      });
    };
    canvas.onmousemove = (e) => {
      if (dragging < 0) return;
      const pos = getCanvasPos(canvas, e);
      const rendered = getRenderedImageRect(img);
      if (!rendered) return;
      const ix = Math.round((pos.x - rendered.x) / rendered.scale);
      const iy = Math.round((pos.y - rendered.y) / rendered.scale);
      centers[dragging] = [ix, iy];
      state.currentPatchCenters[dragging] = [ix, iy];
      drawPatches(canvas, centers);
    };
    canvas.onmouseup = () => { dragging = -1; };
    canvas.onmouseleave = () => { dragging = -1; };

    // Touch support
    canvas.ontouchstart = (e) => { e.preventDefault(); canvas.onmousedown(e.touches[0]); };
    canvas.ontouchmove  = (e) => { e.preventDefault(); canvas.onmousemove(e.touches[0]); };
    canvas.ontouchend   = () => { dragging = -1; };
  }

  function getCanvasPos (canvas, e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function drawPatches (canvas, centers) {
    const img = $('patchImg');
    const rendered = getRenderedImageRect(img);
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!rendered) return;

    const ROI_PX = 20; // display size of square
    centers.forEach(([ix, iy], idx) => {
      const cx = ix * rendered.scale + rendered.x;
      const cy = iy * rendered.scale + rendered.y;
      const half = ROI_PX / 2;
      ctx.strokeStyle = idx >= 28 ? '#c8a96e' : '#e05252';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(cx - half, cy - half, ROI_PX, ROI_PX);
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.beginPath();
      ctx.arc(cx, cy, 2, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function resetPatches () {
    state.currentPatchCenters = state.defaultPatchCenters.map(([x, y]) => [x, y]);
    patchQueue[patchQueuePos].defaultPatches.forEach(([x, y], i) => {
      state.currentPatchCenters[i] = [x, y];
    });
    drawPatches($('patchCanvas'), state.currentPatchCenters);
  }

  function step5Next () {
    // Save current patch centers into pair
    const { pairIdx, role } = patchQueue[patchQueuePos];
    const pair = state.pairs[pairIdx];
    if (role === 'source') pair.sourcePatches = state.currentPatchCenters.map(p => [...p]);
    else pair.targetPatches = state.currentPatchCenters.map(p => [...p]);

    patchQueuePos++;
    loadPatchStep();
  }

  function patchBack () {
    if (patchQueuePos > 0) patchQueuePos--;
    else { cornerQueuePos = cornerQueue.length - 1; loadCornerStep(); return; }
    loadPatchStep();
  }

  // ── STEP 6 – GENERATE LUT ─────────────────────────────
  // Stores the last generated LUT temp filename for save dialog
  let _lastLutFilename = null;

  async function generateLUT () {
    goStep(6);
    show('stateGenerating');
    hide('stateSuccess');
    hide('stateError');

    const pairs = state.pairs.map(p => ({
      source_warped_id: p.sourceWarpedId,
      target_warped_id: p.targetWarpedId,
      source_patches: p.sourcePatches,
      target_patches: p.targetPatches,
    }));

    try {
      const res = await api('POST', '/api/generate-lut', {
        pairs,
        source_log: state.sourceLog,
        target_log: state.targetLog,
        lut_name: state.lutName,
        mode: state.mode,
      });

      _lastLutFilename = res.filename;

      hide('stateGenerating');
      show('stateSuccess');

      $('resultMeta').innerHTML = `
        <b>Datei:</b> ${res.filename}<br/>
        <b>Modus:</b> ${state.mode === 'master' ? 'Master LUT' : 'Single LUT'} – ${state.pairs.length} Paar(e)<br/>
        <b>Abweichung (MSE):</b> ${res.mse.toFixed(6)}<br/>
        <b>Quell-Log:</b> ${state.sourceLog}<br/>
        <b>Ziel-Log:</b> ${state.targetLog}
      `;

      if (state.mode === 'master') $('addSceneBtn').style.display = '';
      else $('addSceneBtn').style.display = 'none';

    } catch (err) {
      hide('stateGenerating');
      show('stateError');
      $('errorMsg').textContent = err.message;
    }
  }

  /**
   * Called by the "Speichern unter..." button.
   * Uses the native pywebview Save-As dialog when running inside the app,
   * or falls back to an HTTP download in browser dev mode.
   */
  async function saveLut () {
    if (!_lastLutFilename) return;
    const btn = $('btnSaveLut');
    btn.disabled = true;
    btn.textContent = '⏳ Speichern…';

    try {
      // pywebview exposes api on window.pywebview.api
      if (window.pywebview && window.pywebview.api) {
        const result = await window.pywebview.api.save_lut(_lastLutFilename, _lastLutFilename);
        if (result.success) {
          btn.textContent = '✓ Gespeichert';
          // Show open-folder button
          const ofBtn = $('btnOpenFolder');
          ofBtn.dataset.folder = result.folder;
          show(ofBtn);
        } else {
          // User cancelled dialog or error
          btn.disabled = false;
          btn.textContent = 'Speichern unter…';
        }
      } else {
        // Dev mode fallback: trigger HTTP download
        const a = document.createElement('a');
        a.href = `/api/download/${_lastLutFilename}`;
        a.download = _lastLutFilename;
        a.click();
        btn.disabled = false;
        btn.textContent = 'Speichern unter…';
      }
    } catch (err) {
      alert('Speichern fehlgeschlagen: ' + err.message);
      btn.disabled = false;
      btn.textContent = 'Speichern unter…';
    }
  }

  async function openFolder (folder) {
    if (!folder) return;
    if (window.pywebview && window.pywebview.api) {
      await window.pywebview.api.open_folder(folder);
    } else {
      await api('POST', '/api/open-folder', { folder });
    }
  }

  function addAnotherScene () {
    state.pairs.push(makePair());
    buildImageSlots();
    goStep(2);
  }

  function restart () {
    state.mode = null;
    state.sourceLog = null;
    state.targetLog = null;
    state.pairs = [];
    state.cornerState = {};
    cornerQueue = [];
    patchQueue = [];
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    $('sourceSelected').textContent = 'Kein Profil gewählt';
    $('sourceSelected').classList.remove('set');
    $('targetSelected').textContent = 'Kein Profil gewählt';
    $('targetSelected').classList.remove('set');
    $('sourceSearch').value = '';
    $('targetSearch').value = '';
    goStep(1);
  }

  // ── Public API ─────────────────────────────────────────
  return {
    selectMode, goStep,
    step2Next, addMasterPair, _slotClick,
    filterLog, step3Next,
    resetCorners, step4Next, cornerBack,
    resetPatches, step5Next, patchBack,
    saveLut, openFolder,
    addAnotherScene, restart,
  };
})();
