import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js';

const API_BASE = window.location.port === '5173' ? 'http://127.0.0.1:8000' : '';

const stlFile = document.getElementById('stlFile');
const optimizeBtn = document.getElementById('optimizeBtn');
const runInfo = document.getElementById('runInfo');
const logBox = document.getElementById('logBox');
const candidateGrid = document.getElementById('candidateGrid');
const layerSlider = document.getElementById('layerSlider');
const layerLabel = document.getElementById('layerLabel');
const chooseBtn = document.getElementById('chooseBtn');
const viewerEl = document.getElementById('viewer');

let runId = null;
let selectedCand = null;
let previewData = null;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf8fafc);
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
camera.position.set(0, -220, 180);
const renderer = new THREE.WebGLRenderer({ antialias: true });
viewerEl.appendChild(renderer.domElement);
const group = new THREE.Group();
scene.add(group);
const grid = new THREE.GridHelper(240, 24);
scene.add(grid);
const light = new THREE.DirectionalLight(0xffffff, 1);
light.position.set(0, -120, 160);
scene.add(light);
scene.add(new THREE.AmbientLight(0xffffff, 0.6));

function api(path) {
  return `${API_BASE}${path}`;
}

function resize() {
  const w = viewerEl.clientWidth;
  const h = viewerEl.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();

const colors = { MODEL: 0xff8a00, SUPPORT: 0x1db954, BRIM: 0x1e40af, TRAVEL: 0x8b8b8b };

function log(msg) {
  logBox.textContent += `${msg}\n`;
  logBox.scrollTop = logBox.scrollHeight;
}

async function startRun() {
  const file = stlFile.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch(api('/api/runs'), { method: 'POST', body: form });
  const data = await resp.json();
  runId = data.run_id;
  runInfo.textContent = `Run: ${runId}`;
  connectEvents();
  pollStatus();
}

function connectEvents() {
  const es = new EventSource(api(`/api/runs/${runId}/events`));
  es.onmessage = (e) => {
    const evt = JSON.parse(e.data);
    log(`[${evt.level}] ${evt.message}`);
  };
}

async function pollStatus() {
  if (!runId) return;
  const resp = await fetch(api(`/api/runs/${runId}`));
  const data = await resp.json();
  runInfo.textContent = `Run ${runId} | ${data.status} | ${data.stage} | sliced ${data.sliced_candidates}/${data.total_candidates}`;
  if (data.status === 'done' || data.status === 'error') {
    loadCandidates();
    return;
  }
  setTimeout(pollStatus, 1500);
}

async function loadCandidates() {
  const resp = await fetch(api(`/api/runs/${runId}/candidates`));
  const list = await resp.json();
  candidateGrid.innerHTML = '';
  list.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  for (const c of list) {
    const d = document.createElement('div');
    d.className = 'card';
    d.innerHTML = `<b>#${c.rank ?? '-'} Candidate ${c.idx}</b><br/>score: ${(c.score ?? 0).toFixed(3)}<br/>support: ${(c.stage2.support_extrusion_mm ?? 0).toFixed(2)} mm<br/>time: ${c.stage2.total_time_sec ?? 'n/a'} s`;
    d.onclick = () => selectCandidate(c, d);
    candidateGrid.appendChild(d);
  }
}

async function selectCandidate(cand, el) {
  [...candidateGrid.querySelectorAll('.card')].forEach((c) => c.classList.remove('active'));
  el.classList.add('active');
  selectedCand = cand.id;
  chooseBtn.disabled = false;
  const resp = await fetch(api(`/api/runs/${runId}/candidates/${cand.id}/preview`));
  previewData = await resp.json();
  layerSlider.max = Math.max(0, previewData.layers.length - 1);
  layerSlider.value = layerSlider.max;
  drawLayer();
}

function drawLayer() {
  while (group.children.length) group.remove(group.children[0]);
  if (!previewData) return;
  const maxIdx = Number(layerSlider.value);
  layerLabel.textContent = `${maxIdx + 1} / ${previewData.layers.length}`;
  const enabled = {
    MODEL: document.getElementById('toggleMODEL').checked,
    SUPPORT: document.getElementById('toggleSUPPORT').checked,
    BRIM: document.getElementById('toggleBRIM').checked,
    TRAVEL: document.getElementById('toggleTRAVEL').checked,
  };

  for (let i = 0; i <= maxIdx; i++) {
    const layer = previewData.layers[i];
    for (const path of layer.paths) {
      if (!enabled[path.type]) continue;
      const pts = path.pts.map(([x, y]) => new THREE.Vector3(x - 110, y - 110, layer.z));
      const geom = new THREE.BufferGeometry().setFromPoints(pts);
      const mat = new THREE.LineBasicMaterial({
        color: colors[path.type] ?? 0x000000,
        transparent: path.type === 'TRAVEL',
        opacity: path.type === 'TRAVEL' ? 0.2 : 0.95,
      });
      group.add(new THREE.Line(geom, mat));
    }
  }
}

for (const id of ['layerSlider', 'toggleMODEL', 'toggleSUPPORT', 'toggleBRIM', 'toggleTRAVEL']) {
  document.getElementById(id).addEventListener('input', drawLayer);
}

chooseBtn.addEventListener('click', async () => {
  if (!selectedCand) return;
  const resp = await fetch(api(`/api/runs/${runId}/choose`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cand_id: selectedCand }),
  });
  const data = await resp.json();
  window.location.href = api(data.download_url);
});

optimizeBtn.addEventListener('click', startRun);
