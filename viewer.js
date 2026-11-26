// Interactive 3D Viewer for #results ("More results"):
// One shared WebGL canvas + shared robot GLBs (smplx / g1 / h2) + lightweight per-clip props GLB & gzipped motion track.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const MANIFEST_URL = "media/viewer/manifest.json";

const host = document.querySelector("#viewer-shell");
const canvas = document.querySelector("#viewer-canvas");
const thumbGrid = document.querySelector("#viewer-thumbs");
const badgeEl = document.querySelector("#viewer-badge");
const loadingEl = document.querySelector("#viewer-loading");
const playBtn = document.querySelector("#v-play");
const scrubEl = document.querySelector("#v-scrub");
const timeEl = document.querySelector("#v-time");
const speedBtns = [...document.querySelectorAll("[data-vspeed]")];
const camBtns = [...document.querySelectorAll("[data-vcam]")];
const zoomInBtn = document.querySelector("#v-zin");
const zoomOutBtn = document.querySelector("#v-zout");
const resetBtn = document.querySelector("#v-reset");

if (host && canvas) {
  initViewer().catch((err) => {
    console.error("viewer: failed to initialize", err);
    if (loadingEl) {
      loadingEl.hidden = false;
      loadingEl.textContent = "3D viewer unavailable in this browser.";
    }
  });
}

// ---- procedural studio grid floor texture (matches Blender studio look)
function makeGridTexture() {
  const size = 512;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#f7f9fc";
  ctx.fillRect(0, 0, size, size);
  // subtle sub-grid (0.5m)
  ctx.strokeStyle = "rgba(150, 168, 196, 0.22)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(size / 2, 0); ctx.lineTo(size / 2, size);
  ctx.moveTo(0, size / 2); ctx.lineTo(size, size / 2);
  ctx.stroke();
  // primary 1m grid lines
  ctx.strokeStyle = "rgba(95, 114, 148, 0.42)";
  ctx.lineWidth = 4;
  ctx.strokeRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(40, 40);
  tex.anisotropy = 16;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// ---- fetch & decompress gzipped binary motion track
async function loadMotionBin(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  let buf;
  if (typeof DecompressionStream !== "undefined") {
    const ds = new DecompressionStream("gzip");
    buf = await new Response(res.body.pipeThrough(ds)).arrayBuffer();
  } else {
    buf = await res.arrayBuffer();
  }
  const dv = new DataView(buf);
  const magic = dv.getUint32(0, true);
  if (magic !== 0x314D544D) throw new Error(`Bad motion header in ${url}`);
  const nFrames = dv.getUint32(4, true);
  const nNodes = dv.getUint32(8, true);
  const fps = dv.getFloat32(12, true);
  let off = 16;
  const posLen = nFrames * nNodes * 3;
  const pos = new Float32Array(buf, off, posLen);
  off += posLen * 4;
  const quatLen = nFrames * nNodes * 4;
  const quats = new Int16Array(buf, off, quatLen);
  off += quatLen * 2;
  const focusLen = nFrames * 3;
  const rootFocus = new Float32Array(buf, off, focusLen);
  off += focusLen * 4;
  const handFocus = new Float32Array(buf, off, focusLen);
  return { nFrames, nNodes, fps, duration: (nFrames - 1) / fps, pos, quats, rootFocus, handFocus };
}

async function initViewer() {
  const manifest = await fetch(MANIFEST_URL).then((r) => {
    if (!r.ok) throw new Error(`manifest: ${r.status}`);
    return r.json();
  });

  // ---- Three.js renderer, studio lighting, tiled floor
  const captureMode = new URLSearchParams(location.search).has("capture");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance", preserveDrawingBuffer: captureMode });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.06;

  const scene = new THREE.Scene();
  const BG = new THREE.Color(0xedf2f9);
  scene.background = BG;
  scene.fog = new THREE.Fog(BG, 14, 34);

  const camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 80);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.62;
  pmrem.dispose();

  scene.add(new THREE.HemisphereLight(0xffffff, 0xc7d2e4, 0.85));

  const sun = new THREE.DirectionalLight(0xfff9f0, 1.55);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -4.2, right: 4.2, top: 4.2, bottom: -4.2, near: 0.5, far: 18 });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.014;
  sun.shadow.radius = 4;
  scene.add(sun, sun.target);

  const rim = new THREE.DirectionalLight(0xdce8ff, 0.45);
  rim.position.set(-4, 5, -5);
  scene.add(rim);

  const floorGeo = new THREE.PlaneGeometry(40, 40).rotateX(-Math.PI / 2);
  const floorMat = new THREE.MeshStandardMaterial({ map: makeGridTexture(), roughness: 0.9, metalness: 0.0 });
  const floorMesh = new THREE.Mesh(floorGeo, floorMat);
  floorMesh.receiveShadow = true;
  scene.add(floorMesh);

  // ---- asset caches
  const gltfLoader = new GLTFLoader();
  const robotCache = new Map();
  const clipCache = new Map();

  async function getRobot(name) {
    if (robotCache.has(name)) return robotCache.get(name);
    const p = gltfLoader.loadAsync(manifest.robots[name]).then((gltf) => {
      const root = gltf.scene;
      const nodes = [];
      root.traverse((o) => {
        if (o.isMesh) {
          o.castShadow = true;
          o.receiveShadow = true;
          o.frustumCulled = false;
          if (o.material) o.material.side = THREE.DoubleSide;
        }
      });
      for (let i = 0; i < 200; i++) {
        const n = root.getObjectByName(`r${String(i).padStart(2, "0")}`);
        if (!n) break;
        nodes.push(n);
      }
      return { root, nodes };
    });
    robotCache.set(name, p);
    return p;
  }

  async function getClipAssets(meta) {
    if (clipCache.has(meta.id)) return clipCache.get(meta.id);
    const propsUrl = `media/viewer/clips/${meta.id}_props.glb`;
    const motUrl = `media/viewer/clips/${meta.id}_motion.bin.gz`;
    const p = Promise.all([
      meta.has_props ? gltfLoader.loadAsync(propsUrl) : Promise.resolve(null),
      loadMotionBin(motUrl),
    ]).then(([propsGltf, motion]) => {
      let propsRoot = null;
      const objNodes = [];
      if (propsGltf) {
        propsRoot = propsGltf.scene;
        propsRoot.traverse((o) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
            o.frustumCulled = false;
            if (o.material) o.material.side = THREE.DoubleSide;
          }
        });
        for (let i = 0; i < meta.n_obj; i++) {
          const n = propsRoot.getObjectByName(`o${String(i).padStart(2, "0")}`);
          if (n) objNodes.push(n);
        }
      }
      return { propsRoot, objNodes, motion };
    });
    clipCache.set(meta.id, p);
    return p;
  }

  // ---- active scene state
  const stageGroup = new THREE.Group();
  scene.add(stageGroup);

  let activeTab = "human";
  let activeMeta = null;
  let activeRobot = null;
  let activeClip = null;
  let loadSeq = 0;

  let playing = true;
  let speed = 1.0;
  let simTime = 0.0;
  let camMode = "follow"; // "follow" | "hand" | "overview"
  let canvasInteracted = false;

  // ---- damped spherical orbit camera (works smoothly on top of Follow / Hand / Overview!)
  const camState = {
    az: -0.9, el: 0.34, radius: 3.4,
    tAz: -0.9, tEl: 0.34, tRadius: 3.4,
    pan: new THREE.Vector3(), tPan: new THREE.Vector3(),
    anchor: new THREE.Vector3(0, 0.9, 0),
    tAnchor: new THREE.Vector3(0, 0.9, 0),
    snap: true,
  };

  function defaultCamFor(meta, mode) {
    const azRad = ((meta.azimuth ?? -50) * Math.PI) / 180;
    const [bmin, bmax] = meta.bounds;
    const cx = 0.5 * (bmin[0] + bmax[0]);
    const cy = 0.5 * (bmin[1] + bmax[1]);
    const cz = 0.5 * (bmin[2] + bmax[2]);
    const dx = bmax[0] - bmin[0], dy = bmax[1] - bmin[1], dz = bmax[2] - bmin[2];
    const span = Math.hypot(dx, dy, dz);

    if (mode === "hand") {
      return {
        az: azRad,
        el: 0.36,
        radius: meta.robot === "smplx" ? 1.05 : 1.35,
        anchor: null,
      };
    }
    if (mode === "overview") {
      return {
        az: azRad,
        el: 0.42,
        radius: Math.max(2.6, Math.min(9.5, span * 1.10)),
        anchor: new THREE.Vector3(cx, Math.max(0.65, Math.min(1.6, cy)), cz),
      };
    }
    // follow
    const tallH = dy > 2.2 ? dy * 1.65 : (meta.robot === "h2" ? 3.9 : 3.2);
    return {
      az: azRad,
      el: 0.34,
      radius: Math.max(2.6, tallH),
      anchor: null,
    };
  }

  function applyCamPreset(mode, snap = false) {
    camMode = mode;
    for (const b of camBtns) b.setAttribute("aria-pressed", String(b.dataset.vcam === mode));
    if (!activeMeta) return;
    const p = defaultCamFor(activeMeta, mode);
    camState.tAz = p.az;
    camState.tEl = p.el;
    camState.tRadius = p.radius;
    camState.tPan.set(0, 0, 0);
    if (p.anchor) camState.tAnchor.copy(p.anchor);
    if (snap) camState.snap = true;
  }

  // ---- pointer & wheel controls
  let dragMode = 0; // 0 none, 1 orbit, 2 pan
  let lastX = 0, lastY = 0;
  const activePointers = new Map();
  let lastPinchDist = 0;

  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointerdown", (e) => {
    canvasInteracted = true;
    canvas.setPointerCapture(e.pointerId);
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (activePointers.size === 1) {
      dragMode = (e.button === 2 || e.shiftKey) ? 2 : 1;
      lastX = e.clientX; lastY = e.clientY;
    } else if (activePointers.size === 2) {
      dragMode = 0;
      const pts = [...activePointers.values()];
      lastPinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!activePointers.has(e.pointerId)) return;
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (activePointers.size === 2) {
      const pts = [...activePointers.values()];
      const d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (lastPinchDist > 0) {
        camState.tRadius = Math.max(0.45, Math.min(20, camState.tRadius * (lastPinchDist / Math.max(1, d))));
      }
      lastPinchDist = d;
      return;
    }
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    if (dragMode === 1) {
      camState.tAz -= dx * 0.007;
      camState.tEl = Math.max(0.04, Math.min(1.48, camState.tEl + dy * 0.006));
    } else if (dragMode === 2) {
      const scale = camState.tRadius * 0.0016;
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
      camState.tPan.addScaledVector(right, -dx * scale).addScaledVector(up, dy * scale);
    }
  });
  const endPtr = (e) => {
    activePointers.delete(e.pointerId);
    if (activePointers.size === 0) { dragMode = 0; lastPinchDist = 0; }
  };
  canvas.addEventListener("pointerup", endPtr);
  canvas.addEventListener("pointercancel", endPtr);
  canvas.addEventListener("dblclick", () => applyCamPreset(camMode, false));
  canvas.addEventListener("wheel", (e) => {
    if (!canvasInteracted && !e.ctrlKey) return; // avoid trapping normal page scroll until user clicks viewer
    e.preventDefault();
    const factor = Math.exp(e.deltaY * 0.0012);
    camState.tRadius = Math.max(0.45, Math.min(20, camState.tRadius * factor));
  }, { passive: false });

  // Reset wheel-capture if user clicks outside the viewer
  document.addEventListener("pointerdown", (e) => {
    if (!host.contains(e.target)) canvasInteracted = false;
  });

  // ---- playback & toolbar controls
  function updatePlayUI() {
    if (!playBtn) return;
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    playBtn.innerHTML = playing
      ? `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2.5" width="3.2" height="11" rx="0.8" fill="currentColor"/><rect x="9.3" y="2.5" width="3.2" height="11" rx="0.8" fill="currentColor"/></svg>`
      : `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5L13 8l-9 5.5z" fill="currentColor"/></svg>`;
  }
  playBtn?.addEventListener("click", () => { playing = !playing; updatePlayUI(); });
  scrubEl?.addEventListener("input", () => {
    if (!activeClip) return;
    simTime = parseFloat(scrubEl.value) * activeClip.motion.duration;
  });
  for (const b of speedBtns) {
    b.addEventListener("click", () => {
      speed = parseFloat(b.dataset.vspeed);
      for (const x of speedBtns) x.setAttribute("aria-pressed", String(x === b));
    });
  }
  for (const b of camBtns) {
    b.addEventListener("click", () => applyCamPreset(b.dataset.vcam, false));
  }
  zoomInBtn?.addEventListener("click", () => { camState.tRadius = Math.max(0.45, camState.tRadius * 0.78); });
  zoomOutBtn?.addEventListener("click", () => { camState.tRadius = Math.min(20, camState.tRadius * 1.28); });
  resetBtn?.addEventListener("click", () => applyCamPreset(camMode, false));

  // ---- apply motion frame at time `t` with smooth linear pos + quaternion slerp
  const _q0 = new THREE.Quaternion(), _q1 = new THREE.Quaternion();
  const _rf = new THREE.Vector3(), _hf = new THREE.Vector3();

  function applyFrame(t) {
    if (!activeClip || !activeRobot) return;
    const m = activeClip.motion;
    const fExact = Math.max(0, Math.min(m.nFrames - 1, t * m.fps));
    const i0 = Math.floor(fExact);
    const i1 = Math.min(m.nFrames - 1, i0 + 1);
    const alpha = fExact - i0;
    const nNodes = m.nNodes;
    const rNodes = activeRobot.nodes;
    const oNodes = activeClip.objNodes;
    const nRob = rNodes.length;
    const INV = 1 / 32767;

    const pOff0 = i0 * nNodes * 3, pOff1 = i1 * nNodes * 3;
    const qOff0 = i0 * nNodes * 4, qOff1 = i1 * nNodes * 4;

    for (let j = 0; j < nNodes; j++) {
      const node = j < nRob ? rNodes[j] : oNodes[j - nRob];
      if (!node) continue;
      const p0 = pOff0 + j * 3, p1 = pOff1 + j * 3;
      node.position.set(
        m.pos[p0] + (m.pos[p1] - m.pos[p0]) * alpha,
        m.pos[p0 + 1] + (m.pos[p1 + 1] - m.pos[p0 + 1]) * alpha,
        m.pos[p0 + 2] + (m.pos[p1 + 2] - m.pos[p0 + 2]) * alpha
      );
      const q0 = qOff0 + j * 4, q1 = qOff1 + j * 4;
      _q0.set(m.quats[q0] * INV, m.quats[q0 + 1] * INV, m.quats[q0 + 2] * INV, m.quats[q0 + 3] * INV).normalize();
      _q1.set(m.quats[q1] * INV, m.quats[q1 + 1] * INV, m.quats[q1 + 2] * INV, m.quats[q1 + 3] * INV).normalize();
      node.quaternion.copy(_q0).slerp(_q1, alpha);
    }

    // Focus targets for camera & shadow frustum
    const f0 = i0 * 3, f1 = i1 * 3;
    _rf.set(
      m.rootFocus[f0] + (m.rootFocus[f1] - m.rootFocus[f0]) * alpha,
      m.rootFocus[f0 + 1] + (m.rootFocus[f1 + 1] - m.rootFocus[f0 + 1]) * alpha,
      m.rootFocus[f0 + 2] + (m.rootFocus[f1 + 2] - m.rootFocus[f0 + 2]) * alpha
    );
    _hf.set(
      m.handFocus[f0] + (m.handFocus[f1] - m.handFocus[f0]) * alpha,
      m.handFocus[f0 + 1] + (m.handFocus[f1 + 1] - m.handFocus[f0 + 1]) * alpha,
      m.handFocus[f0 + 2] + (m.handFocus[f1 + 2] - m.handFocus[f0 + 2]) * alpha
    );

    // Keep floor tiles and shadow frustum centered under the robot
    floorMesh.position.set(Math.round(_rf.x), 0, Math.round(_rf.z));
    sun.target.position.set(_rf.x, 0, _rf.z);
    sun.position.set(_rf.x + 3.2, 7.5, _rf.z + 3.8);

    if (camMode === "follow") {
      camState.tAnchor.copy(_rf);
    } else if (camMode === "hand") {
      camState.tAnchor.copy(_hf);
    }
  }

  // ---- clip selection & tab rendering
  async function selectClip(meta) {
    const seq = ++loadSeq;
    activeMeta = meta;
    if (thumbGrid) {
      for (const btn of thumbGrid.querySelectorAll("button")) {
        btn.setAttribute("aria-selected", String(btn.dataset.cid === meta.id));
      }
    }
    if (badgeEl) {
      const emb = meta.robot === "smplx" ? "SMPL-X" : meta.robot === "g1" ? "G1 + REVO2" : "H2 + SHARPA WAVE";
      badgeEl.innerHTML = `<b>${emb}</b><i>·</i><span>${meta.kind}</span><i>·</i>${meta.title}`;
    }
    if (loadingEl) {
      loadingEl.hidden = false;
      loadingEl.textContent = `Loading 3D scene…`;
    }

    const [robot, clip] = await Promise.all([getRobot(meta.robot), getClipAssets(meta)]);
    if (seq !== loadSeq) return; // superseded by another click

    stageGroup.clear();
    stageGroup.add(robot.root);
    if (clip.propsRoot) stageGroup.add(clip.propsRoot);

    activeRobot = robot;
    activeClip = clip;
    simTime = 0.0;
    playing = true;
    updatePlayUI();
    applyCamPreset(meta.default_cam || "follow", true);
    applyFrame(0.0);
    if (loadingEl) loadingEl.hidden = true;
  }

  function renderTab(tabId) {
    const tab = manifest.tabs[tabId];
    if (!tab) return;
    activeTab = tabId;
    const setNote = document.querySelector("#setnote");
    if (setNote) setNote.textContent = tab.note;
    if (thumbGrid) {
      thumbGrid.replaceChildren(...tab.clips.map((c) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "vthumb";
        b.dataset.cid = c.id;
        b.setAttribute("role", "tab");
        b.setAttribute("aria-selected", "false");
        const img = new Image();
        img.src = c.thumb;
        img.alt = c.title;
        img.loading = "lazy";
        const metaDiv = document.createElement("div");
        metaDiv.className = "vthumb-meta";
        const kindEl = document.createElement("span");
        kindEl.textContent = c.kind;
        const titleEl = document.createElement("strong");
        titleEl.textContent = c.title;
        metaDiv.append(kindEl, titleEl);
        b.append(img, metaDiv);
        b.addEventListener("click", () => selectClip(c));
        return b;
      }));
    }
    if (tab.clips.length > 0) selectClip(tab.clips[0]);
  }

  // Expose tab hook so site.js can switch smoothly between 3D tabs & legacy video tab ("body")
  window.__resultsViewer = {
    manifest,
    hasTab: (id) => Boolean(manifest.tabs[id]),
    showTab: (id) => {
      host.hidden = false;
      renderTab(id);
      resize();
    },
    hide: () => {
      host.hidden = true;
    },
    captureClip: async (tabId, clipId, frac = 0.45) => {
      const tab = manifest.tabs[tabId];
      const meta = tab?.clips.find((c) => c.id === clipId);
      if (!meta) throw new Error(`Unknown clip ${tabId}/${clipId}`);
      host.hidden = false;
      resize();
      await selectClip(meta);
      playing = false;
      updatePlayUI();
      simTime = Math.max(0, Math.min(activeClip.motion.duration, frac * activeClip.motion.duration));
      camState.snap = true;
      applyFrame(simTime);
      // Force one synchronous render with snapped camera
      camState.az = camState.tAz;
      camState.el = camState.tEl;
      camState.radius = camState.tRadius;
      camState.pan.copy(camState.tPan);
      camState.anchor.copy(camState.tAnchor);
      _tgt.copy(camState.anchor).add(camState.pan);
      const cosEl = Math.cos(camState.el);
      camera.position.set(
        _tgt.x + camState.radius * cosEl * Math.cos(camState.az),
        _tgt.y + camState.radius * Math.sin(camState.el),
        _tgt.z + camState.radius * cosEl * Math.sin(camState.az)
      );
      camera.lookAt(_tgt);
      renderer.render(scene, camera);
      return canvas.toDataURL("image/jpeg", 0.88);
    },
  };

  // ---- resize & visibility (pauses loop when scrolled off-screen)
  let inView = true;
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([e]) => { inView = e.isIntersecting; }, { threshold: 0.02 }).observe(host);
  resize();

  // ---- main 60fps animation loop
  let prevMs = 0;
  const _tgt = new THREE.Vector3();

  function tick(ms) {
    requestAnimationFrame(tick);
    if (host.hidden || !inView) { prevMs = 0; return; }
    const dt = prevMs ? Math.min(0.08, (ms - prevMs) / 1000) : 0;
    prevMs = ms;

    if (activeClip) {
      const dur = Math.max(0.01, activeClip.motion.duration);
      if (playing) {
        simTime = (simTime + dt * speed) % dur;
      }
      applyFrame(simTime);
      if (scrubEl && document.activeElement !== scrubEl) {
        scrubEl.value = String(simTime / dur);
      }
      if (timeEl) {
        timeEl.textContent = `${simTime.toFixed(1)}s / ${dur.toFixed(1)}s`;
      }
    }

    // Smooth camera damping
    const damp = camState.snap ? 1.0 : Math.min(1.0, dt * 8.0);
    camState.az += (camState.tAz - camState.az) * damp;
    camState.el += (camState.tEl - camState.el) * damp;
    camState.radius += (camState.tRadius - camState.radius) * damp;
    camState.pan.lerp(camState.tPan, damp);
    camState.anchor.lerp(camState.tAnchor, camState.snap ? 1.0 : Math.min(1.0, dt * 5.0));
    camState.snap = false;

    _tgt.copy(camState.anchor).add(camState.pan);
    const cosEl = Math.cos(camState.el);
    camera.position.set(
      _tgt.x + camState.radius * cosEl * Math.cos(camState.az),
      _tgt.y + camState.radius * Math.sin(camState.el),
      _tgt.z + camState.radius * cosEl * Math.sin(camState.az)
    );
    camera.lookAt(_tgt);
    renderer.render(scene, camera);
  }
  requestAnimationFrame(tick);

  // Start on whichever tab is currently selected in DOM
  const initialTab = document.querySelector(".tabs [aria-selected='true']")?.dataset.set || "human";
  if (manifest.tabs[initialTab]) {
    window.__resultsViewer.showTab(initialTab);
  }
}
