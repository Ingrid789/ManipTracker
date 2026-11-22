// The first screen: one synthetic demonstration, told in 3D as the page scrolls.
//
// The section (.scrolly) is tall and its content sticks, so scroll position is a number p in [0, 1]. p drives
// everything: the motion time of the robot, the camera, what is visible, and which caption shows.
//   0.00  title          a G1 humanoid with Revo2 hands stands in a laundry room, in front of a washing machine
//   0.14  Part I         grasp candidates appear around the door's rim; filtering keeps the anchors in its pull recess
//   0.32  Part II        root and right wrist paths are drawn; the robot walks to the machine and reaches the anchors
//   0.56  Combine        it pulls the door ajar, changes its grasp and opens the door while stepping back
//   0.78  ManipTracker   the motion rewinds and plays again: the reference as a ghost, the robot following it
//
// The scene is exported by tools/export_hero.py into media/hero:
//   scene.glb   robot and washer, one node per body, with the motion baked in two clips ("robot" and "door")
//   room.spz    the laundry room as Gaussian splats, cut down to the machine row, the floor and a few objects
//   scene.json  the motion's phases, the root and wrist paths, the grasp anchors on the door
// Its frame: x along the row of machines, y up from the floor, z from the machines into the room, in metres.
import * as THREE from "three";

const ASSETS = { glb: "media/hero/scene.glb", splat: "media/hero/room.spz", meta: "media/hero/scene.json" };
const CHAPTERS = [0, 0.14, 0.32, 0.56, 0.78, 1];  // where each caption starts; the last entry is the end

const section = document.querySelector(".scrolly");
const canvas = document.querySelector("#hero-canvas");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---- small helpers
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const seg = (x, a, b) => clamp01((x - a) / (b - a));
const smooth = (x) => x * x * (3 - 2 * x);
const ease = (x, a, b) => smooth(seg(x, a, b));
const mix = (a, b, t) => a + (b - a) * t;
const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);

// ---- captions, dots and scroll position (these work without WebGL too)
const chapters = [...document.querySelectorAll(".hud .chapter")];
const dots = [...document.querySelectorAll(".scrolly .dots button")];
let chapter = -1;
function setChapter(p) {
  let c = 0;
  for (let i = 0; i < CHAPTERS.length - 1; i++) if (p >= CHAPTERS[i]) c = i;
  if (c === chapter) return;
  chapter = c;
  section.dataset.chapter = String(c);
  chapters.forEach((el, i) => el.classList.toggle("on", i === c));
  dots.forEach((el, i) => { if (i === c) el.setAttribute("aria-current", "step"); else el.removeAttribute("aria-current"); });
}
const span = () => section.offsetHeight - innerHeight;
const progress = () => clamp01((scrollY - section.offsetTop) / Math.max(1, span()));
dots.forEach((el, i) => el.addEventListener("click", () => {
  const p = i === 0 ? 0 : CHAPTERS[i] + (CHAPTERS[i + 1] - CHAPTERS[i]) * 0.35;
  scrollTo({ top: section.offsetTop + span() * p, behavior: reduced ? "auto" : "smooth" });
}));
setChapter(progress());
const followScroll = () => setChapter(progress());
addEventListener("scroll", followScroll, { passive: true });  // until the 3D scene draws; then the scene sets the caption

// ---- the scene
let renderer;
try {
  // No multisampling: blending half a million splats once per sample costs most of the frame on a laptop's
  // built-in GPU (8 frames a second instead of 60, measured). The resolution below takes care of the edges.
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true });
} catch (e) {
  section.classList.add("nogl");  // the teaser image shows instead; the captions still follow the scroll
}
if (renderer) {
  start().catch((e) => {
    console.warn("hero: the 3D scene did not load; showing the teaser image", e);
    section.classList.remove("ready");
    section.classList.add("nogl");
    addEventListener("scroll", followScroll, { passive: true });
  });
}

async function start() {
  const [{ GLTFLoader }, { RoomEnvironment }, { SparkRenderer, SplatMesh }] = await Promise.all([
    import("three/addons/loaders/GLTFLoader.js"), import("three/addons/environments/RoomEnvironment.js"), import("@sparkjsdev/spark")]);
  renderer.setClearColor(0x000000, 0);  // the page's sky shows where the room has been cut away
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
  let dirty = true;

  // the room: Gaussian splats, drawn by Spark, which sorts them in a worker and asks for a new frame when it is done
  scene.add(new SparkRenderer({ renderer, onDirty: () => { dirty = true; } }));
  const room = new SplatMesh({ url: ASSETS.splat });
  const [gltf, meta] = await Promise.all([new GLTFLoader().loadAsync(ASSETS.glb), fetch(ASSETS.meta).then((r) => r.json()), room.initialized]);
  scene.add(room);

  // light for the robot and the washer: the room's ceiling lamp, soft light from all around, a shadow on the splat floor
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;
  pmrem.dispose();
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b3aa, 0.9));
  const sun = new THREE.DirectionalLight(0xfff6ea, 1.5);
  sun.target.position.set(0.4, 0, 1.4);
  sun.position.copy(sun.target.position).add(V(0.5, 5.4, 2.7));
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -2.2, right: 2.2, top: 2.2, bottom: -2.2, near: 1, far: 12 });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.01;
  sun.shadow.radius = 6;
  scene.add(sun, sun.target);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(5, 3.2).rotateX(-Math.PI / 2), new THREE.ShadowMaterial({ opacity: 0.34, depthWrite: false }));
  shadow.position.set(0.5, 0.004, 2.4);  // the floor in front of the machines
  shadow.receiveShadow = true;
  shadow.renderOrder = 2;                // after the splats
  scene.add(shadow);

  // ---- the robot and the washer
  scene.add(gltf.scene);
  const robot = gltf.scene.getObjectByName("robot"), fixture = gltf.scene.getObjectByName("fixture");
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const glass = o.material.transparent;
    o.castShadow = !glass; o.receiveShadow = !glass;
    if (glass) { o.renderOrder = 3; o.material.depthWrite = false; }
  });
  const DURATION = meta.duration, FPS = meta.fps;
  const clip = (name) => gltf.animations.find((c) => c.name === name);
  const player = (root, name) => { const m = new THREE.AnimationMixer(root); m.clipAction(clip(name)).play(); return m; };
  const robotMixer = player(robot, "robot"), doorMixer = player(fixture, "door");
  // the reference of the last chapter: the same robot once more, see-through and blue
  const ghost = robot.clone(true);
  const ghostMat = new THREE.MeshStandardMaterial({ color: 0x2f63d8, roughness: 0.5, transparent: true, opacity: 0, emissive: 0x2f63d8, emissiveIntensity: 0.25 });
  ghost.traverse((o) => { if (o.isMesh) { o.material = ghostMat; o.castShadow = o.receiveShadow = false; o.renderOrder = 4; } });
  scene.add(ghost);
  const ghostMixer = player(ghost, "robot");
  const at = (mixer, t) => mixer.setTime(Math.max(0, Math.min(DURATION - 1e-3, t)));
  const pelvis = robot.getObjectByName("pelvis");
  const T = (frame) => frame / FPS, PH = meta.phases;

  // ---- Part I: grasp candidates around the door's rim, in the door's own frame, so that they turn with the door.
  // That frame is MuJoCo's: x out of the machine, y towards the door's free edge, z up.
  const door = fixture.getObjectByName(meta.door.node);
  const GOLD = 0xe7b416, RED = 0xdc4b3e, GREEN = 0x76c043;
  const [, c1, c2] = meta.door.rim_centre, faceX = meta.door.face_x + 0.003;
  const onRim = (r, phi) => V(faceX, c1 + r * Math.cos(phi * Math.PI / 180), c2 + r * Math.sin(phi * Math.PI / 180));
  const anchors = meta.anchors.hook.map((a) => onRim(a.r, a.phi));
  const candidates = [...anchors];
  for (let phi = 52; phi < 372; phi += 13.5) candidates.push(onRim(0.262, phi));
  for (let phi = 20; phi < 380; phi += 40) candidates.push(onRim(0.2, phi + 9));
  const dot = new THREE.SphereGeometry(1, 16, 12);
  const marks = candidates.map((p, i) => {
    const kept = i < anchors.length;
    const m = new THREE.Mesh(dot, new THREE.MeshStandardMaterial({ color: kept ? GOLD : 0x8b93a5, roughness: 0.4, emissive: kept ? GOLD : 0x8b93a5, emissiveIntensity: kept ? 0.45 : 0.15 }));
    m.position.copy(p);
    door.add(m);
    return m;
  });
  // the pull recess, outlined: the stretch of the rim where the kept grasps hold the door
  const [phi0, phi1] = meta.door.recess_phi, arcPts = [];
  for (let i = 0; i <= 24; i++) arcPts.push(onRim(meta.door.rim_r + 0.012, mix(phi0, phi1, i / 24)));
  const arc = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(arcPts), 48, 0.0045, 8), new THREE.MeshBasicMaterial({ color: GOLD, transparent: true, opacity: 0 }));
  arc.renderOrder = 5;
  door.add(arc);

  // ---- Part II: the two sparse controls of this motion, the root (green) and the right wrist (red), as paths
  const every = meta.path_every, i0 = Math.floor(PH.walk_in[0] / every), i1 = Math.ceil(PH.retract[1] / every);
  const trails = [["root", GREEN, 0.012], ["right", RED, 0.01]].map(([key, color, r]) => {
    const pts = meta.paths[key].slice(i0, i1 + 1).map((p) => V(...p));
    const beads = new THREE.InstancedMesh(dot, new THREE.MeshStandardMaterial({ color, roughness: 0.5, emissive: color, emissiveIntensity: 0.35, transparent: true }), pts.length);
    const m = new THREE.Matrix4();
    pts.forEach((p, i) => beads.setMatrixAt(i, m.makeScale(r, r, r).setPosition(p)));
    beads.instanceMatrix.needsUpdate = true;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 }));
    beads.frustumCulled = line.frustumCulled = false;
    scene.add(beads, line);
    return { beads, line, n: pts.length };
  });

  // ---- the camera: positions and targets along the scroll; `follow` pulls the target toward the robot
  const DOOR = V(0.52, 0.68, 0.82), RECESS = V(0.63, 0.74, 0.8);
  const KEYS = [
    { p: 0.00, pos: V(2.75, 1.6, 4.3), tgt: V(0.5, 0.85, 1.0), follow: 0 },
    { p: 0.13, pos: V(2.45, 1.55, 4.3), tgt: V(0.5, 0.82, 1.0), follow: 0 },
    { p: 0.20, pos: V(1.42, 0.98, 1.95), tgt: RECESS.clone().add(V(-0.06, -0.04, 0)), follow: 0 },
    { p: 0.31, pos: V(1.2, 1.0, 1.72), tgt: RECESS.clone().add(V(-0.04, -0.02, 0)), follow: 0 },
    { p: 0.38, pos: V(2.7, 2.35, 4.05), tgt: V(0.55, 0.6, 1.25), follow: 0 },
    { p: 0.56, pos: V(2.05, 1.4, 1.95), tgt: V(0.45, 0.72, 1.05), follow: 0.15 },
    { p: 0.66, pos: V(1.95, 1.4, 2.5), tgt: V(0.4, 0.7, 1.1), follow: 0.2 },
    { p: 0.77, pos: V(1.75, 1.42, 3.1), tgt: V(0.3, 0.72, 1.1), follow: 0.25 },
    { p: 0.84, pos: V(2.5, 1.7, 3.7), tgt: V(0.5, 0.75, 1.2), follow: 0.2 },
    { p: 1.00, pos: V(1.6, 1.45, 3.3), tgt: V(0.25, 0.74, 1.1), follow: 0.3 },
  ];
  const camPos = V(), camTgt = V(), focus = V();
  let wide = false;
  function aim(p) {
    let i = 0;
    while (i < KEYS.length - 2 && p > KEYS[i + 1].p) i++;
    const a = KEYS[i], b = KEYS[i + 1], t = ease(p, a.p, b.p);
    camPos.lerpVectors(a.pos, b.pos, t);
    camTgt.lerpVectors(a.tgt, b.tgt, t).lerp(focus, mix(a.follow, b.follow, t));
    if (!wide) camPos.sub(camTgt).multiplyScalar(1.22).add(camTgt);  // a narrow screen stands further back
  }

  // ---- one frame at scroll position p
  const tStand = T(40), tReach = T(PH.insert_tip[1]), tReplay = T(PH.reach[0] - 40);
  function draw(p, time) {
    setChapter(p);
    // the demonstration: stands while the anchors are picked, walks in and reaches, then opens the door
    let t = p < 0.14 ? tStand * seg(p, 0, 0.14) : p < 0.36 ? tStand : p < 0.56 ? mix(tStand, tReach, seg(p, 0.36, 0.56)) : mix(tReach, DURATION, seg(p, 0.56, 0.765));
    // ManipTracker: the motion rewinds, then plays again with the robot a moment behind its reference
    const track = ease(p, 0.78, 0.83);
    let tRef = t;
    if (p >= 0.78) {
      t = p < 0.835 ? mix(DURATION, tReplay, ease(p, 0.78, 0.835)) : mix(tReplay, DURATION, seg(p, 0.845, 0.985));
      tRef = t + 0.4 * seg(p, 0.845, 0.87) * (1 - seg(p, 0.96, 0.985));
    }
    at(robotMixer, t); at(doorMixer, t);
    ghost.visible = track > 0.01;
    if (ghost.visible) { at(ghostMixer, tRef); ghostMat.opacity = 0.34 * track; }

    // Part I: candidates pop in one after another; filtering leaves the anchors in the pull recess
    const kept = ease(p, 0.25, 0.3), gone = ease(p, 0.33, 0.37);
    marks.forEach((m, i) => {
      const shown = ease(p, 0.165 + i * 0.002, 0.185 + i * 0.002) * (1 - gone);
      const s = 0.0095 * (i < anchors.length ? shown * mix(1, 1.3, kept) * (1 + 0.1 * kept * Math.sin(time * 3 + i)) : shown * (1 - kept));
      m.visible = s > 1e-4;
      m.scale.setScalar(Math.max(1e-4, s));
    });
    arc.material.opacity = kept * (1 - gone);
    arc.visible = arc.material.opacity > 0.01;

    // Part II: the paths are drawn
    const drawn = ease(p, 0.33, 0.43), fade = 1 - ease(p, 0.57, 0.61);  // gone before the camera comes close
    for (const tr of trails) {
      const n = Math.round(tr.n * drawn);
      tr.beads.count = n; tr.line.geometry.setDrawRange(0, n);
      tr.beads.visible = tr.line.visible = n > 0 && fade > 0.01;
      tr.line.material.opacity = 0.8 * fade;
      tr.beads.material.opacity = fade;
    }

    scene.updateMatrixWorld();
    pelvis.getWorldPosition(focus);
    aim(p);
    if (!reduced) camPos.x += 0.12 * Math.sin(time * 0.5) * (1 - seg(p, 0.1, 0.18));  // the title drifts a little
    camera.position.copy(camPos);
    camera.lookAt(camTgt);
    renderer.render(scene, camera);
  }

  // ---- resolution. The splats are bound by fill rate, so the drawing buffer follows what the GPU keeps up with:
  // it drops a step when frames come slower than about 40 a second, and tries the step above when they come easily.
  // A frame that stays on screen is drawn at the top step.
  const BASE = Math.min(devicePixelRatio, 2);
  const STEPS = [0.5, 0.64, 0.8, 1].map((k) => k * BASE).concat(BASE < 1.5 ? [1.5] : []);  // large pixels: oversampled
  const TOP = STEPS.length - 1, failed = STEPS.map(() => 0), spans = [];
  let step = STEPS.indexOf(BASE), ratio = 0, easy = 0;
  function setRatio(r) {
    if (r === ratio) return;
    ratio = r;
    renderer.setPixelRatio(r);
  }
  function adapt() {
    const mid = spans.sort((a, b) => a - b)[spans.length >> 1];
    spans.length = 0;
    if (mid > 24 && step > 0) { failed[step]++; step--; easy = 0; }
    else if (mid < 18 && step < TOP && failed[step + 1] < 2) { if (++easy >= 4) { step++; easy = 0; } }
    else easy = 0;
  }
  setRatio(STEPS[step]);

  // ---- size, visibility, the loop
  let visible = true, shown = progress(), last = 0, lastLive = 0;
  removeEventListener("scroll", followScroll);
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    wide = w > 900;
    // on a wide screen the captions sit on the left, so the scene's centre moves right; on a phone they sit at
    // the bottom, so it moves up and the camera takes a wider angle
    camera.fov = wide ? 38 : 52;
    if (wide) camera.setViewOffset(w, h, -w * 0.13, 0, w, h); else camera.setViewOffset(w, h, 0, h * 0.14, w, h);
    camera.updateProjectionMatrix();
    dirty = true;
  }
  new ResizeObserver(resize).observe(canvas);
  resize();
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(section);
  function loop(ms) {
    requestAnimationFrame(loop);
    if (!visible) { last = 0; return; }
    const target = progress();
    const moving = Math.abs(target - shown) > 1e-5;
    shown = reduced || !moving ? target : shown + (target - shown) * 0.14;
    const idle = !reduced && (shown < 0.18 || (shown > 0.24 && shown < 0.37));  // the title drift, the anchors' pulse
    if (moving || idle) {
      if (last && ms - last < 250 && spans.push(ms - last) >= 30) adapt();
      last = lastLive = ms;
      setRatio(STEPS[step]);
    } else {
      last = 0;
      spans.length = 0;
      const settled = ms - lastLive > 200;  // not between two notches of a wheel
      if (settled && ratio !== STEPS[TOP]) dirty = true;
      if (!dirty) return;
      if (settled) setRatio(STEPS[TOP]);
    }
    dirty = false;
    draw(shown, ms / 1000);
  }
  requestAnimationFrame(loop);
  section.classList.add("ready");
}
