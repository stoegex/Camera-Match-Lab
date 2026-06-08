/**
 * app.js – Camera Match Lab frontend orchestration
 * Manages all 6 workflow steps and communicates with Flask backend.
 */
const App = (() => {
  // ── State ──────────────────────────────────────────────
  const state = {
    mode: null,          // 'single' | 'master' | 'reference'
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

    // ── Reference mode ──
    refImgId: null,
    refWarpedId: null,
    refPatches: null,
    refDefaultPatches: null,
    refName: '',
    refWarpedSrc: '',
    refWarpedW: 0,
    refWarpedH: 0,
    displayGamma: null,
    allDisplayGammas: [],
    sourceCameras: [],  // [{imgId, warpedId, patches, defaultPatches, log, name, warpedSrc}]
  };

  // ── Helpers ────────────────────────────────────────────
  function $ (id) { return document.getElementById(id); }
  function show (el) { if (typeof el === 'string') el = $(el); el?.classList.remove('hidden'); }
  function hide (el) { if (typeof el === 'string') el = $(el); el?.classList.add('hidden'); }

  // Capture original step-3 HTML so we can restore it after reference mode
  let _originalStep3GridHTML = null;
  (function _captureStep3() {
    const grid = document.getElementById('logSelectGrid');
    if (grid) _originalStep3GridHTML = grid.innerHTML;
  })();

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
    state.sourceCameras = [];
    state.refImgId = null;
    state.refWarpedId = null;
    state.refPatches = null;
    state.displayGamma = null;
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    const btnMap = { single: 'btnSingle', master: 'btnMaster', reference: 'btnReference' };
    const btnId = btnMap[m];
    if (btnId) $(btnId).classList.add('selected');

    setTimeout(() => {
      if (m === 'reference') {
        loadRefProfilesForStep2().then(() => buildRefImageSlots());
      } else {
        buildImageSlots();
      }
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

  let _globalFileInput = null;
  function getFileInput(onchangeHandler) {
    if (!_globalFileInput) {
      _globalFileInput = document.createElement('input');
      _globalFileInput.type = 'file';
      _globalFileInput.accept = '.tif,.tiff,.jpg,.jpeg,.png,.mp4,.mov';
      _globalFileInput.style.display = 'none';
      document.body.appendChild(_globalFileInput);
    }
    _globalFileInput.value = ''; // clear previous selection
    _globalFileInput.onchange = onchangeHandler;
    return _globalFileInput;
  }

  function _slotClick (pairIdx, role) {
    const input = getFileInput(() => {
      if (input.files[0]) uploadToSlot(pairIdx, role, input.files[0]);
    });
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

      // Auto-detect camera model + suggest log profile
      fetchMetadata(res.img_id);

      // Video frame picker
      if (/\.(mp4|mov|mxf|mts|m2ts|avi)$/i.test(file.name)) {
        _addVideoBadge(`slot-${pairIdx}-${role}`, res.img_id, role, pairIdx);
        openVideoPicker(res.img_id, role, pairIdx);
      }

    } catch (err) {
      lblEl.textContent = `Fehler: ${err.message}`;
    }
    checkStep2Next();
  }

  function _addVideoBadge (containerId, imgId, role, pairIdx, idx) {
    const container = $(containerId);
    if (!container) return;
    let badge = container.querySelector('.video-badge');
    if (!badge) {
      badge = document.createElement('button');
      badge.className = 'video-badge';
      badge.textContent = '🎬 Frame wählen';
      badge.onclick = (e) => { e.stopPropagation(); openVideoPicker(imgId, role, pairIdx, idx); };
      container.appendChild(badge);
    }
  }

  function checkStep2Next () {
    if (state.mode === 'reference') {
      const refReady = state.refImgId && state.displayGamma;
      const sourcesReady = state.sourceCameras.length > 0 && state.sourceCameras.every(c => c.imgId && c.log);
      $('step2Next').disabled = !(refReady && sourcesReady);
      return;
    }
    const allLoaded = state.pairs.every(p => p.sourceImgId && p.targetImgId);
    $('step2Next').disabled = !allLoaded;
  }

  // ── Reference-mode image slots ─────────────────
  function buildRefImageSlots () {
    const container = $('imageSlots');
    if (!container) return;
    container.innerHTML = '';

    let html = '<div class="ref-section"><h3 class="ref-section-title">🔘 REFERENZ-Bild (Display, fertiger Look)</h3>';
    html += `<div class="pair-slots-row">
      <div class="drop-slot ${state.refImgId ? 'loaded' : ''}" id="slot-ref-reference"
           data-role="ref-reference" style="flex:1"
           onclick="App._refSlotClick('reference')">
        <div class="drop-slot-inner">
          <div class="drop-slot-role reference-label">REFERENZ (Display Look)</div>
          <svg class="drop-slot-icon" width="32" height="32" viewBox="0 0 32 32" fill="none">
            <path d="M16 4v16M8 12l8-8 8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.5"/>
            <rect x="4" y="22" width="24" height="6" rx="2" stroke="currentColor" stroke-width="1.5" opacity="0.3"/>
          </svg>
          <span class="drop-slot-label" id="slot-lbl-ref-reference">Klicken oder ziehen</span>
          <span style="font-size:11px;color:var(--text-3)">z.B. S1II Screengrab mit LUT</span>
        </div>
        <img class="drop-slot-thumb" id="slot-thumb-ref-reference" src="${state.refImgId ? state.cornerState[state.refImgId]?.imgSrc || '' : ''}" style="${state.refImgId ? '' : 'display:none'}" alt="" draggable="false"/>
      </div>
      <div class="ref-gamma-box" id="refGammaBox">
        <div class="log-label target-label"><span class="log-dot target"></span> Referenz Kennzeichnung</div>
        <select class="ref-select" id="refGammaSelect" onchange="App.selectDisplayGamma(this.value)">
          <option value="">-- Projektstandard wählen --</option>
          ${(state.allDisplayGammas.length ? state.allDisplayGammas : ['Rec709 (BT.709)','sRGB','Gamma 2.4','Gamma 2.2']).map(g => {
            return `<option value="${g}" ${state.displayGamma === g ? 'selected' : ''}>${g}</option>`;
          }).join('')}
        </select>
      </div>
    </div></div>`;

    html += '<div class="ref-section"><h3 class="ref-section-title">📷 SOURCE-Kameras (Log)</h3>';

    if (state.sourceCameras.length === 0) state.sourceCameras.push({ imgId: null, warpedId: null, patches: null, defaultPatches: null, log: null, name: '', warpedSrc: '' });

    state.sourceCameras.forEach((cam, idx) => {
      html += `<div class="pair-slots-row" id="ref-source-row-${idx}">
        <div class="drop-slot ${cam.imgId ? 'loaded' : ''}" id="slot-ref-source-${idx}"
             data-role="ref-source-${idx}" style="flex:1"
             onclick="App._refSlotClick('source', ${idx})">
          <div class="drop-slot-inner">
            <div class="drop-slot-role source">SOURCE ${idx + 1}</div>
            <svg class="drop-slot-icon" width="32" height="32" viewBox="0 0 32 32" fill="none">
              <path d="M16 4v16M8 12l8-8 8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.5"/>
              <rect x="4" y="22" width="24" height="6" rx="2" stroke="currentColor" stroke-width="1.5" opacity="0.3"/>
            </svg>
            <span class="drop-slot-label" id="slot-lbl-ref-source-${idx}">Klicken oder ziehen</span>
            <span style="font-size:11px;color:var(--text-3)">z.B. S5IIX, Mavic4, ZX-V, GoPro</span>
          </div>
          <img class="drop-slot-thumb" id="slot-thumb-ref-source-${idx}" src="${cam.imgId ? state.cornerState[cam.imgId]?.imgSrc || '' : ''}" style="${cam.imgId ? '' : 'display:none'}" alt="" draggable="false"/>
        </div>
        <div class="ref-source-controls">
          <div class="log-label source-label"><span class="log-dot source"></span> Log-Profil</div>
          <input type="text" class="search-input ref-search" id="refSourceSearch-${idx}" placeholder="Suche... z.B. V-Log" oninput="App.filterRefSourceLog(${idx}, this.value)" autocomplete="off"/>
          <div class="log-list-wrap" id="refSourceLogList-${idx}" style="max-height:120px">`;
      (state.allProfiles.length ? state.allProfiles : []).forEach(p => {
        const sel = cam.log === p ? ' selected' : '';
        html += `<div class="log-item${sel}" onclick="App.selectRefSourceLog(${idx}, '${p}')">${p}</div>`;
      });
      html += `</div>
          <div class="log-selected ${cam.log ? 'set' : ''}" id="refSourceLogSelected-${idx}">${cam.log || 'Kein Profil'}</div>
        </div>
        <button class="btn-ghost small ref-delete-btn" onclick="App.removeRefSource(${idx})" title="Source entfernen">✕</button>
      </div>`;
    });

    html += '</div>';

    container.innerHTML = html;

    $('masterAddBtn')?.classList.remove('hidden');
    const addBtn = $('masterAddBtn');
    if (addBtn) {
      addBtn.innerHTML = `<button class="btn-secondary" onclick="App.addRefSource()">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        Weitere Source-Kamera hinzufügen
      </button>`;
    }

    wireRefDropSlots();
    checkStep2Next();
  }

  function wireRefDropSlots () {
    document.querySelectorAll('.drop-slot[id^="slot-ref-"]').forEach(slot => {
      slot.addEventListener('dragover', e => { e.preventDefault(); slot.classList.add('dragover'); });
      slot.addEventListener('dragleave', () => slot.classList.remove('dragover'));
      slot.addEventListener('drop', e => {
        e.preventDefault();
        slot.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (!file) return;
        const role = slot.dataset.role;
        if (role === 'ref-reference') uploadRefImage('reference', file);
        else if (role.startsWith('ref-source-')) {
          const idx = parseInt(role.replace('ref-source-', ''));
          uploadRefImage('source', file, idx);
        }
      });
    });
  }

  function _refSlotClick (role, idx) {
    const input = getFileInput(() => {
      if (input.files[0]) {
        if (role === 'reference') uploadRefImage('reference', input.files[0]);
        else uploadRefImage('source', input.files[0], idx);
      }
    });
    input.click();
  }

  async function uploadRefImage (role, file, idx) {
    let lblEl, thumbEl;
    if (role === 'reference') {
      lblEl = $('slot-lbl-ref-reference');
      thumbEl = $('slot-thumb-ref-reference');
    } else {
      lblEl = $(`slot-lbl-ref-source-${idx}`);
      thumbEl = $(`slot-thumb-ref-source-${idx}`);
    }
    lblEl.textContent = '⏳ Wird geladen…';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await api('POST', '/api/upload', fd);

      if (role === 'reference') {
        state.refImgId = res.img_id;
        state.refName = res.filename;
      } else {
        if (!state.sourceCameras[idx]) state.sourceCameras[idx] = { imgId: null, warpedId: null, patches: null, defaultPatches: null, log: null, name: '', warpedSrc: '' };
        state.sourceCameras[idx].imgId = res.img_id;
        state.sourceCameras[idx].name = res.filename;
      }

      state.cornerState[res.img_id] = {
        corners: [],
        imgSrc: res.preview,
        displayW: res.width,
        displayH: res.height,
      };

      thumbEl.src = res.preview;
      thumbEl.style.display = 'block';
      const slotEl = role === 'reference' ? $('slot-ref-reference') : $(`slot-ref-source-${idx}`);
      if (slotEl) slotEl.classList.add('loaded');
      lblEl.textContent = file.name;

      // Auto-detect camera model + suggest log profile
      fetchMetadata(res.img_id);

      // Video frame picker
      if (/\.(mp4|mov|mxf|mts|m2ts|avi)$/i.test(file.name)) {
        const slotId = role === 'reference' ? 'slot-ref-reference' : `slot-ref-source-${idx}`;
        _addVideoBadge(slotId, res.img_id, role, undefined, idx);
        openVideoPicker(res.img_id, role, undefined, idx);
      }

    } catch (err) {
      lblEl.textContent = `Fehler: ${err.message}`;
    }
    checkStep2Next();
  }

  async function fetchMetadata (imgId) {
    const promise = (async () => {
      try {
        const meta = await api('POST', '/api/metadata', { img_id: imgId });
        if (meta.make || meta.model) {
          if (!state.imgMeta) state.imgMeta = {};
          state.imgMeta[imgId] = meta;
          if (meta.suggested_log) {
            console.log(`Camera detected: ${meta.make} ${meta.model} → ${meta.suggested_log}`);
          }
        }
      } catch (e) {
        // Metadata extraction is optional — silently fail
      }
    })();
    if (!state._metaPending) state._metaPending = {};
    state._metaPending[imgId] = promise;
    return promise;
  }

  // ── Video frame picker modal ──────────────────────────
  let _vpImgId = null;
  let _vpRole = null;
  let _vpIdx = null;
  let _vpPairIdx = null;
  let _vpTotal = 0;
  let _vpCurrent = 0;

  function openVideoPicker (imgId, role, pairIdx, idx) {
    _vpImgId = imgId;
    _vpRole = role;
    _vpPairIdx = pairIdx !== undefined ? pairIdx : null;
    _vpIdx = idx !== undefined ? idx : null;

    const modal = $('videoPickerModal');
    if (!modal) return;
    modal.style.display = 'flex';

    $('videoPickerLabel').textContent = 'Lade Video-Info…';
    $('videoPickerPreview').src = '';
    $('videoPickerConfirm').disabled = true;

    api('GET', `/api/video-info/${imgId}`).then(info => {
      _vpTotal = info.frame_count;
      _vpCurrent = 0;
      $('videoPickerSlider').max = _vpTotal - 1;
      $('videoPickerSlider').value = 0;
      $('videoPickerLabel').textContent = `Frame 1 / ${_vpTotal}`;
      $('videoPickerConfirm').disabled = false;
      _loadVpFrame(0);
    }).catch(e => {
      $('videoPickerLabel').textContent = 'Fehler beim Laden';
      console.warn('Video info failed:', e);
    });
  }

  function closeVideoPicker () {
    $('videoPickerModal').style.display = 'none';
  }

  function _vpScrub (frame) {
    _vpCurrent = frame;
    $('videoPickerLabel').textContent = `Frame ${frame + 1} / ${_vpTotal}`;
    _loadVpFrame(frame);
  }

  function _vpSeek (delta) {
    const newFrame = Math.max(0, Math.min(_vpTotal - 1, _vpCurrent + delta));
    _vpCurrent = newFrame;
    $('videoPickerSlider').value = newFrame;
    $('videoPickerLabel').textContent = `Frame ${newFrame + 1} / ${_vpTotal}`;
    _loadVpFrame(newFrame);
  }

  async function _loadVpFrame (frame) {
    try {
      const res = await api('POST', '/api/video-frame', { img_id: _vpImgId, frame });
      $('videoPickerPreview').src = res.preview;
    } catch (e) { console.warn('Frame load failed:', e); }
  }

  async function _vpConfirm () {
    $('videoPickerConfirm').disabled = true;
    $('videoPickerConfirm').textContent = '⏳ Speichere…';
    try {
      const res = await api('POST', '/api/select-video-frame', { img_id: _vpImgId, frame: _vpCurrent });

      // Update state based on mode
      if (_vpPairIdx !== null) {
        // Single/Master mode
        const pair = state.pairs[_vpPairIdx];
        if (_vpRole === 'source') pair.sourceImgId = res.img_id;
        else pair.targetImgId = res.img_id;
        state.cornerState[res.img_id] = {
          corners: [], imgSrc: res.preview,
          displayW: res.width, displayH: res.height,
        };
        const thumbEl = $(`slot-thumb-${_vpPairIdx}-${_vpRole}`);
        if (thumbEl) thumbEl.src = res.preview;
      } else if (_vpRole === 'reference') {
        state.refImgId = res.img_id;
        state.cornerState[res.img_id] = {
          corners: [], imgSrc: res.preview,
          displayW: res.width, displayH: res.height,
        };
        const thumbEl = $('slot-thumb-ref-reference');
        if (thumbEl) thumbEl.src = res.preview;
      } else {
        // Reference mode - source camera
        if (state.sourceCameras[_vpIdx]) state.sourceCameras[_vpIdx].imgId = res.img_id;
        state.cornerState[res.img_id] = {
          corners: [], imgSrc: res.preview,
          displayW: res.width, displayH: res.height,
        };
        const thumbEl = $(`slot-thumb-ref-source-${_vpIdx}`);
        if (thumbEl) thumbEl.src = res.preview;
      }

      closeVideoPicker();
    } catch (err) {
      console.warn('Frame selection failed:', err.message);
      $('videoPickerConfirm').textContent = '✅ Diesen Frame verwenden';
      $('videoPickerConfirm').disabled = false;
    }
  }

  function addRefSource () {
    state.sourceCameras.push({ imgId: null, warpedId: null, patches: null, defaultPatches: null, log: null, name: '', warpedSrc: '' });
    buildRefImageSlots();
  }

  function removeRefSource (idx) {
    if (state.sourceCameras.length <= 1) return;
    const cam = state.sourceCameras[idx];
    if (cam.imgId) delete state.cornerState[cam.imgId];
    state.sourceCameras.splice(idx, 1);
    buildRefImageSlots();
  }

  function addMasterPair () {
    state.pairs.push(makePair());
    buildImageSlots();
  }

  function step2Next () {
    if (state.mode === 'reference') {
      state.lutName = 'RefMatch';
      state.refWarpedId = null;
      state.sourceCameras.forEach(c => { c.warpedId = null; });
      startRefCornerFlow();
      return;
    }
    if (state.mode === 'single' || state.mode === 'master') {
      loadLogProfiles();
      goStep(3);
    }
  }

  // ── STEP 3 ─────────────────────────────────────────────
  async function loadLogProfiles () {
    // Restore original step-3 layout for single/master mode
    const grid = $('logSelectGrid');
    if (grid && _originalStep3GridHTML) grid.innerHTML = _originalStep3GridHTML;

    // Reset step-3 header for single/master mode
    const title = $('step3Title');
    const sub = $('step3Sub');
    if (title) title.textContent = 'Kamera Log-Profile';
    if (sub) sub.textContent = 'Wähle das Log-Profil für Quelle und Ziel.';

    if (!state.allProfiles.length) {
      try {
        state.allProfiles = await api('GET', '/api/log-profiles');
      } catch (e) { console.error('Could not load log profiles', e); }
    }

    // Await any pending metadata fetches before auto-select
    if (state._metaPending) {
      const promises = [];
      state.pairs.forEach(p => {
        if (p.sourceImgId && state._metaPending[p.sourceImgId]) promises.push(state._metaPending[p.sourceImgId]);
        if (p.targetImgId && state._metaPending[p.targetImgId]) promises.push(state._metaPending[p.targetImgId]);
      });
      if (promises.length) await Promise.all(promises);
    }

    renderLogLists();
  }

  function renderLogLists () {
    // Auto-select log profiles based on already-loaded metadata
    if (state.imgMeta) {
      state.pairs.forEach(pair => {
        if (pair.sourceImgId && !state.sourceLog) {
          const meta = state.imgMeta[pair.sourceImgId];
          if (meta && meta.suggested_log && state.allProfiles.includes(meta.suggested_log)) {
            selectLog('source', meta.suggested_log);
          }
        }
        if (pair.targetImgId && !state.targetLog) {
          const meta = state.imgMeta[pair.targetImgId];
          if (meta && meta.suggested_log && state.allProfiles.includes(meta.suggested_log)) {
            selectLog('target', meta.suggested_log);
          }
        }
      });
    }
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
    if (state.mode === 'reference') {
      if (!state.displayGamma || state.sourceCameras.some(c => !c.log)) {
        $('step3Next').disabled = true;
        return;
      }
      state.lutName = 'RefMatch';
      // Reset warp data
      state.refWarpedId = null;
      state.sourceCameras.forEach(c => { c.warpedId = null; });
      startRefCornerFlow();
      return;
    }
    // Build lut name from first pair
    const p = state.pairs[0];
    const sn = p.sourceName ? p.sourceName.replace(/\.[^.]+$/, '') : 'Source';
    const tn = p.targetName ? p.targetName.replace(/\.[^.]+$/, '') : 'Target';
    state.lutName = `${sn}_to_${tn}_Match`;

    // Reset corner progress for all pairs
    state.pairs.forEach(p => { p.sourceWarpedId = null; p.targetWarpedId = null; });
    startCornerFlow();
  }

  // ── Reference-mode step 2 profile loading ────
  async function loadRefProfilesForStep2 () {
    try {
      if (!state.allProfiles.length) state.allProfiles = await api('GET', '/api/log-profiles');
      if (!state.allDisplayGammas.length) state.allDisplayGammas = await api('GET', '/api/display-gammas');
    } catch (e) { console.error('Failed to load profiles', e); }
  }

  // ── Reference-mode step 3 (profiles) ──────────
  // (kept for backward compat, step 3 is now skipped in reference mode)
  async function loadRefProfiles () {
    try {
      if (!state.allProfiles.length) state.allProfiles = await api('GET', '/api/log-profiles');
      if (!state.allDisplayGammas.length) state.allDisplayGammas = await api('GET', '/api/display-gammas');
    } catch (e) { console.error('Failed to load profiles', e); }
  }

  function renderRefProfileStep () {
    const grid = $('logSelectGrid');
    if (!grid) return;
    grid.innerHTML = '';

    // Auto-select source camera log profiles from metadata
    if (state.imgMeta) {
      state.sourceCameras.forEach((cam, idx) => {
        if (cam.imgId && !cam.log) {
          const meta = state.imgMeta[cam.imgId];
          if (meta && meta.suggested_log) {
            cam.log = meta.suggested_log;
          }
        }
      });
    }

    // Update step header for reference mode
    const title = $('step3Title');
    const sub = $('step3Sub');
    if (title) title.textContent = 'Referenz & Camera Profile';
    if (sub) sub.textContent = 'Die Profile dokumentieren den Workflow. Das Display-Reference-Matching arbeitet direkt mit den gespeicherten Bildwerten.';

    // Reference display metadata
    let html = `<div class="log-select-card">
      <div class="log-label target-label">
        <span class="log-dot target"></span> REFERENZ Projektstandard
      </div>
      <p class="log-hint">Kennzeichnung für den Export; es wird keine zusätzliche Gamma-Konvertierung angewendet.</p>
      <div class="log-list-wrap">`;
    state.allDisplayGammas.forEach(g => {
      const sel = state.displayGamma === g ? ' selected' : '';
      html += `<div class="gamma-option${sel}" onclick="App.selectDisplayGamma('${g}')">${g}</div>`;
    });
    html += `</div>
      <div class="log-selected ${state.displayGamma ? 'set' : ''}" id="refGammaSelected">${state.displayGamma || 'Kein Gamma gewählt'}</div>
    </div>`;

    // Source log profiles (one per source camera)
    state.sourceCameras.forEach((cam, idx) => {
      html += `<div class="log-select-card">
        <div class="log-label source-label">
          <span class="log-dot source"></span> SOURCE ${idx + 1}: ${cam.name || '(kein Bild)'}
        </div>
        <p class="log-hint">Log-Profil dieser Kamera (z.B. V-Log, D-Log, S-Log3)</p>
        <input type="text" class="search-input" placeholder="Suche..." oninput="App.filterRefSourceLog(${idx}, this.value)" autocomplete="off"/>
        <div class="log-list-wrap" id="refSourceLogList-${idx}">`;
      state.allProfiles.forEach(p => {
        const sel = cam.log === p ? ' selected' : '';
        html += `<div class="log-item${sel}" onclick="App.selectRefSourceLog(${idx}, '${p}')">${p}</div>`;
      });
      html += `</div>
        <div class="log-selected ${cam.log ? 'set' : ''}" id="refSourceLogSelected-${idx}">${cam.log || 'Kein Profil gewählt'}</div>
      </div>`;
    });

    grid.innerHTML = html;
    $('step3Next').disabled = !(state.displayGamma && state.sourceCameras.every(c => c.log));
  }

  function selectDisplayGamma (gammaOrVal) {
    state.displayGamma = gammaOrVal;
    checkStep2Next();
  }

  function selectRefSourceLog (idx, logName) {
    if (!state.sourceCameras[idx]) return;
    state.sourceCameras[idx].log = logName;
    $('refSourceLogSelected-' + idx).textContent = logName;
    $('refSourceLogSelected-' + idx).classList.add('set');
    checkStep2Next();
    // Update list selection
    const listEl = $(`refSourceLogList-${idx}`);
    if (listEl) {
      listEl.innerHTML = '';
      state.allProfiles.forEach(p => {
        const sel = state.sourceCameras[idx]?.log === p ? ' selected' : '';
        listEl.innerHTML += `<div class="log-item${sel}" onclick="App.selectRefSourceLog(${idx}, '${p}')">${p}</div>`;
      });
    }
  }

  function filterRefSourceLog (idx, query) {
    const filtered = state.allProfiles.filter(p => p.toLowerCase().includes(query.toLowerCase()));
    const listEl = $(`refSourceLogList-${idx}`);
    if (!listEl) return;
    listEl.innerHTML = '';
    filtered.forEach(p => {
      const sel = state.sourceCameras[idx]?.log === p ? ' selected' : '';
      listEl.innerHTML += `<div class="log-item${sel}" onclick="App.selectRefSourceLog(${idx}, '${p}')">${p}</div>`;
    });
  }

  // ── Reference-mode corner flow ─────────────────
  let refCornerQueue = [];
  let refCornerPos = 0;

  function startRefCornerFlow () {
    refCornerQueue = [];
    // Reference first
    if (state.refImgId) refCornerQueue.push({ type: 'reference', imgId: state.refImgId });
    // Then each source
    state.sourceCameras.forEach((cam, i) => {
      if (cam.imgId) refCornerQueue.push({ type: 'source', idx: i, imgId: cam.imgId });
    });
    refCornerPos = 0;
    loadRefCornerStep();
  }

  function loadRefCornerStep () {
    if (refCornerPos >= refCornerQueue.length) {
      startRefPatchFlow();
      return;
    }
    const { type, idx, imgId } = refCornerQueue[refCornerPos];
    const cs = state.cornerState[imgId];
    if (cs) cs.corners = [];

    const label = type === 'reference' ? 'REFERENZ-Bild' : `SOURCE ${idx + 1}: ${state.sourceCameras[idx]?.name || ''}`;
    $('step4Title').textContent = `${label} — Ecken markieren (${refCornerPos + 1}/${refCornerQueue.length})`;
    $('step4Next').disabled = true;
    state.currentCornerImg = imgId;

    goStep(4);
    if (cs) setupCornerCanvas(cs);
  }

  async function refStep4Next () {
    $('step4Next').disabled = true;
    $('step4Next').textContent = '⏳ Wird verarbeitet…';

    const { type, idx, imgId } = refCornerQueue[refCornerPos];
    const cs = state.cornerState[imgId];

    try {
      const res = await api('POST', '/api/warp', { img_id: imgId, corners: cs.corners });
      if (type === 'reference') {
        state.refWarpedId = res.warped_id;
        state.refDefaultPatches = res.patch_centers;
        state.refWarpedSrc = res.preview;
        state.refWarpedW = res.width;
        state.refWarpedH = res.height;
      } else {
        state.sourceCameras[idx].warpedId = res.warped_id;
        state.sourceCameras[idx].defaultPatches = res.patch_centers;
        state.sourceCameras[idx].warpedSrc = res.preview;
      }
    } catch (err) {
      alert(`Warp-Fehler: ${err.message}`);
      $('step4Next').disabled = false;
      $('step4Next').textContent = 'Ecken bestätigen →';
      return;
    }

    $('step4Next').textContent = 'Ecken bestätigen →';
    refCornerPos++;
    loadRefCornerStep();
  }

  function refCornerBack () {
    if (refCornerPos > 0) { refCornerPos--; loadRefCornerStep(); }
    else goStep(3);
  }

  // ── Reference-mode patch flow ──────────────────
  let refPatchQueue = [];
  let refPatchPos = 0;

  function startRefPatchFlow () {
    refPatchQueue = [];
    // Reference first
    refPatchQueue.push({ type: 'reference', warpedId: state.refWarpedId, warpedSrc: state.refWarpedSrc, defaultPatches: state.refDefaultPatches });
    // Then each source
    state.sourceCameras.forEach((cam, i) => {
      refPatchQueue.push({ type: 'source', idx: i, warpedId: cam.warpedId, warpedSrc: cam.warpedSrc, defaultPatches: cam.defaultPatches });
    });
    refPatchPos = 0;
    loadRefPatchStep();
  }

  function loadRefPatchStep () {
    if (refPatchPos >= refPatchQueue.length) {
      generateRefLUTs();
      return;
    }
    const { type, idx, warpedId, warpedSrc, defaultPatches } = refPatchQueue[refPatchPos];
    const label = type === 'reference' ? 'REFERENZ-Bild' : `SOURCE ${idx + 1}: ${state.sourceCameras[idx]?.name || ''}`;
    $('step5Title').textContent = `${label} — Patches feinjustieren (${refPatchPos + 1}/${refPatchQueue.length})`;
    $('step5NextLabel').textContent = refPatchPos === refPatchQueue.length - 1 ? 'LUTs generieren →' : 'Weiter →';

    state.currentPatchWarpedId = warpedId;
    state.defaultPatchCenters = defaultPatches.map(([x, y]) => [x, y]);
    state.currentPatchCenters = defaultPatches.map(([x, y]) => [x, y]);

    goStep(5);
    setupPatchCanvas(warpedSrc, state.currentPatchCenters);
  }

  function refStep5Next () {
    const { type, idx } = refPatchQueue[refPatchPos];
    const centers = state.currentPatchCenters.map(p => [...p]);
    if (type === 'reference') state.refPatches = centers;
    else state.sourceCameras[idx].patches = centers;

    refPatchPos++;
    loadRefPatchStep();
  }

  function refPatchBack () {
    if (refPatchPos > 0) refPatchPos--;
    else { refCornerPos = refCornerQueue.length - 1; loadRefCornerStep(); return; }
    loadRefPatchStep();
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
    $('step4Title').textContent = `${roleName}-Bild Ecken markieren${pairName} (${cornerQueuePos + 1}/${cornerQueue.length})`;
    $('step4Next').disabled = true;
    state.currentCornerImg = imgId;

    goStep(4);
    setupCornerCanvas(cs);
  }

  function setupCornerCanvas (cs) {
    const img = $('cornerImg');
    const canvas = $('cornerCanvas');
    img.src = cs.imgSrc;
    img.onload = () => {
      // Wait for CSS layout to complete before reading client dimensions
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          resizeCanvas(canvas, img);
          drawCorners(canvas, cs.corners);
        });
      });
    };
    // Reset dot indicators
    _syncCornerDots(cs.corners.length);

    let draggingCorner = -1;

    canvas.onmousedown = (e) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (e.clientX - rect.left) * scaleX;
      const y = (e.clientY - rect.top) * scaleY;
      const imgEl = $('cornerImg');
      const rendered = getRenderedImageRect(imgEl);
      if (!rendered) return;

      const normX = (x - rendered.x) / rendered.rw;
      const normY = (y - rendered.y) / rendered.rh;

      // If all 4 are set, check for drag
      if (cs.corners.length === 4) {
        let minD = 0.04; // threshold in normalized coords
        cs.corners.forEach(([cx, cy], i) => {
          const d = Math.hypot(cx - normX, cy - normY);
          if (d < minD) { minD = d; draggingCorner = i; }
        });
        if (draggingCorner >= 0) return; // start drag, don't add new point
      }

      // Otherwise add new point
      if (cs.corners.length >= 4) return;
      const cx = Math.max(0, Math.min(1, normX));
      const cy = Math.max(0, Math.min(1, normY));
      cs.corners.push([cx, cy]);
      _syncCornerDots(cs.corners.length);
      if (cs.corners.length === 4) $('step4Next').disabled = false;
      drawCorners(canvas, cs.corners, rendered);
    };

    canvas.onmousemove = (e) => {
      if (draggingCorner < 0) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (e.clientX - rect.left) * scaleX;
      const y = (e.clientY - rect.top) * scaleY;
      const imgEl = $('cornerImg');
      const rendered = getRenderedImageRect(imgEl);
      if (!rendered) return;
      cs.corners[draggingCorner] = [
        Math.max(0, Math.min(1, (x - rendered.x) / rendered.rw)),
        Math.max(0, Math.min(1, (y - rendered.y) / rendered.rh)),
      ];
      drawCorners(canvas, cs.corners, rendered);
    };

    canvas.onmouseup = () => { draggingCorner = -1; };
    canvas.onmouseleave = () => { draggingCorner = -1; };

    // Right-click = undo last corner
    canvas.oncontextmenu = (e) => {
      e.preventDefault();
      undoLastCorner();
    };
  }

  function _syncCornerDots (count) {
    for (let i = 0; i < 4; i++) {
      const d = $(`cdot${i}`);
      d.classList.remove('set', 'active');
      if (i < count) d.classList.add('set');
      else if (i === count) d.classList.add('active');
    }
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
    _syncCornerDots(0);
    $('step4Next').disabled = true;
    const canvas = $('cornerCanvas');
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  }

  async function autoDetectCorners () {
    const btn = $('btnAutoDetect');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '⏳ Suche…';

    const cs = state.cornerState[state.currentCornerImg];
    if (!cs) {
      btn.disabled = false;
      btn.textContent = '🎯 Auto-Detect';
      return;
    }

    try {
      const res = await api('POST', '/api/detect-chart', { img_id: state.currentCornerImg });
      if (res.corners && res.corners.length === 4) {
        cs.corners = res.corners;
        _syncCornerDots(4);
        $('step4Next').disabled = false;
        const canvas = $('cornerCanvas');
        drawCorners(canvas, cs.corners);
        btn.textContent = '✓ Gefunden';
      }
    } catch (err) {
      btn.textContent = '🎯 Auto-Detect';
      console.warn('Auto-detect failed:', err.message);
    }
    btn.disabled = false;
  }

  function undoLastCorner () {
    const cs = state.cornerState[state.currentCornerImg];
    if (!cs || cs.corners.length === 0) return;
    cs.corners.pop();
    _syncCornerDots(cs.corners.length);
    $('step4Next').disabled = cs.corners.length < 4;
    const canvas = $('cornerCanvas');
    drawCorners(canvas, cs.corners);
  }

  async function step4Next () {
    if (state.mode === 'reference') { await refStep4Next(); return; }
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
    if (state.mode === 'reference') { refCornerBack(); return; }
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
    $('step5Title').textContent = `${roleName}-Bild Patches feinjustieren${pairName} (${patchQueuePos + 1}/${patchQueue.length})`;

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
    if (state.mode === 'reference') { refStep5Next(); return; }
    // Save current patch centers into pair
    const { pairIdx, role } = patchQueue[patchQueuePos];
    const pair = state.pairs[pairIdx];
    if (role === 'source') pair.sourcePatches = state.currentPatchCenters.map(p => [...p]);
    else pair.targetPatches = state.currentPatchCenters.map(p => [...p]);

    patchQueuePos++;
    loadPatchStep();
  }

  function patchBack () {
    if (state.mode === 'reference') { refPatchBack(); return; }
    if (patchQueuePos > 0) patchQueuePos--;
    else { cornerQueuePos = cornerQueue.length - 1; loadCornerStep(); return; }
    loadPatchStep();
  }

  // ── Reference-mode LUT generation ──────────────
  let _lastRefResults = [];

  async function generateRefLUTs () {
    goStep(6);
    show('stateGenerating');
    hide('stateSuccess');
    hide('stateError');

    const sources = state.sourceCameras.map(cam => ({
      source_warped_id: cam.warpedId,
      source_patches: cam.patches,
      source_log: cam.log,
      camera_name: cam.name ? cam.name.replace(/\.[^.]+$/, '') : 'Source',
    }));

    try {
      const res = await api('POST', '/api/generate-reference-luts', {
        reference_warped_id: state.refWarpedId,
        reference_patches: state.refPatches,
        display_transform: state.displayGamma || "Rec709 (BT.709)",
        sources,
      });

      _lastRefResults = res.results;
      _lastLutFilename = res.results[0]?.filename || null;

      hide('stateGenerating');
      show('stateSuccess');

      const lines = res.results.map(r =>
        `<b>${r.camera_name}</b> (${r.source_log}): ${r.filename} — MSE: ${r.mse.toFixed(6)}`
      ).join('<br/>');

      $('resultMeta').innerHTML = `
        <b>Modus:</b> Display-Reference Match — ${res.results.length} Kamera(s)<br/>
        <b>Referenz Projektstandard:</b> ${state.displayGamma}<br/><br/>
        ${lines}
      `;

      $('addSceneBtn').style.display = 'none';
      // Add a button to save all
      const saveAllBtn = document.createElement('button');
      saveAllBtn.className = 'btn-primary';
      saveAllBtn.style.marginTop = '12px';
      saveAllBtn.id = 'btnSaveAllLuts';
      saveAllBtn.innerHTML = '💾 Alle LUTs speichern';
      saveAllBtn.onclick = saveAllRefLuts;
      const actionsDiv = document.querySelector('.result-actions');
      if (actionsDiv && !$('btnSaveAllLuts')) {
        actionsDiv.insertBefore(saveAllBtn, actionsDiv.firstChild);
      }

    } catch (err) {
      hide('stateGenerating');
      show('stateError');
      $('errorMsg').textContent = err.message;
    }
  }

  async function saveAllRefLuts () {
    if (!_lastRefResults.length) return;
    const btn = $('btnSaveAllLuts');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '⏳ Ordner wählen…';

    const filenames = _lastRefResults.map(r => r.filename);

    try {
      if (window.pywebview && window.pywebview.api) {
        // Single folder dialog → all files saved at once
        const result = await window.pywebview.api.save_all_luts(filenames);
        if (result.success) {
          btn.textContent = `✓ ${result.count}/${filenames.length} gespeichert`;
          // Show open-folder button
          const ofBtn = $('btnOpenFolder');
          if (ofBtn && result.folder) {
            ofBtn.dataset.folder = result.folder;
            show(ofBtn);
          }
        } else {
          btn.disabled = false;
          btn.textContent = '💾 Alle LUTs speichern';
        }
      } else {
        // Dev mode fallback: trigger HTTP downloads
        let saved = 0;
        for (const r of _lastRefResults) {
          const a = document.createElement('a');
          a.href = `/api/download/${r.filename}`;
          a.download = r.filename;
          a.click();
          saved++;
          await new Promise(resolve => setTimeout(resolve, 300));
        }
        btn.textContent = `✓ ${saved}/${filenames.length} gespeichert`;
      }
    } catch (e) {
      console.error('Save all failed', e);
      btn.disabled = false;
      btn.textContent = '💾 Alle LUTs speichern';
    }
  }

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
    state.refImgId = null;
    state.refWarpedId = null;
    state.refPatches = null;
    state.displayGamma = null;
    state.sourceCameras = [];
    _lastRefResults = [];
    cornerQueue = [];
    patchQueue = [];
    refCornerQueue = [];
    refPatchQueue = [];

    // Restore original step-3 grid
    const grid = $('logSelectGrid');
    if (grid && _originalStep3GridHTML) grid.innerHTML = _originalStep3GridHTML;
    const title = $('step3Title');
    const sub = $('step3Sub');
    if (title) title.textContent = 'Kamera Log-Profile';
    if (sub) sub.textContent = 'Wähle das Log-Profil für Quelle und Ziel.';

    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    $('sourceSelected').textContent = 'Kein Profil gewählt';
    $('sourceSelected').classList.remove('set');
    $('targetSelected').textContent = 'Kein Profil gewählt';
    $('targetSelected').classList.remove('set');
    $('sourceSearch').value = '';
    $('targetSearch').value = '';
    const saveAllBtn = $('btnSaveAllLuts');
    if (saveAllBtn) saveAllBtn.remove();
    goStep(1);
  }

  // ── Public API ─────────────────────────────────────────
  return {
    selectMode, goStep,
    step2Next, addMasterPair, _slotClick,
    filterLog, step3Next,
    resetCorners, undoLastCorner, autoDetectCorners, step4Next, cornerBack,
    resetPatches, step5Next, patchBack,
    saveLut, openFolder,
    addAnotherScene, restart,
    // Reference mode
    _refSlotClick, addRefSource, removeRefSource,
    selectDisplayGamma, selectRefSourceLog, filterRefSourceLog,
    saveAllRefLuts,
    // Video frame picker
    closeVideoPicker, openVideoPicker, _vpScrub, _vpSeek, _vpConfirm,
  };
})();
