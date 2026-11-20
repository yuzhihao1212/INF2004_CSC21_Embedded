/* "People" map view: the classroom in real 3D, with people acting out each
 * area's sensed state. Presentation only, like the rest of the page: app.js
 * hands it the same zone states the Flat and 3D views draw, and nothing here
 * feeds back into a decision. The nodes don't track individuals, so the
 * figures illustrate an area's state (who is talking, standing, walking) rather
 * than real positions.
 *
 * three.js r160 is bundled next to this file (three.module.min.js and two
 * addons, MIT, see three.LICENSE.txt) because the demo hotspot has no internet.
 * The page's import map points the bare "three" specifier at it.
 */
import * as THREE from "three";
import { OrbitControls } from "./three-OrbitControls.js";
import { RoundedBoxGeometry } from "./three-RoundedBoxGeometry.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const MOTION = reduce ? .35 : 1;
const ROOM_L = 12, ROOM_W = 8, FRONT = 2.62;   // metres; the lecturer's band is at x < FRONT

// ---------- small helpers ----------
let seed = 11;
const rnd = () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const damp = (a, b, k, dt) => a + (b - a) * (1 - Math.exp(-k * dt));
const dampAngle = (a, b, k, dt) => { const d = ((((b - a + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI; return a + d * (1 - Math.exp(-k * dt)); };
const easeOut = (x) => 1 - Math.pow(1 - x, 3);
const cssColor = (name) => new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888");

const PALETTE = {
  light: { slab: 0xd5dae1, floor: 0xeef0f3, wall: 0xf8f9fb, wall2: 0xeceff3, board: 0xffffff, frame: 0xaeb5bf, desk: 0xffffff, leg: 0x9aa1ab,
           chair: 0xd3d9e0, chairLeg: 0x7f8792, door: 0xc8b49a, puck: 0x3a3f48, unit: 0xf6f7f9, grille: 0xc3c9d1, fan: 0x939aa5,
           hemi: [0xffffff, 0xd3d8df, 1.15], sun: [0xfff4e6, 2.3], exposure: 1.05, tint: .14, pool: 0, glow: 0, haze: 0xa9a28f },
  dark:  { slab: 0x0d1117, floor: 0x161c25, wall: 0x273040, wall2: 0x2e3848, board: 0x3a4454, frame: 0x4a5466, desk: 0x2a3240, leg: 0x12161d,
           chair: 0x232a36, chairLeg: 0x0f1218, door: 0x4a3f33, puck: 0x2a3240, unit: 0x2c3442, grille: 0x1d232d, fan: 0x4b5566,
           hemi: [0x9fb2d8, 0x0b0d12, .7], sun: [0xa9b8ff, .85], exposure: 1.3, tint: .22, pool: 5, glow: .55, haze: 0x8691a6 },
};
const SKIN = [0xf1c9a5, 0xe0ac86, 0xc68642, 0x8d5524, 0xffdbac, 0xa86b45, 0xd9a07c];
const SHIRT = [0x6c8ebf, 0xd98b6c, 0x7fb59a, 0xe6c86e, 0x9b86c9, 0xf0ece4, 0x4f5d75, 0xc96d7a, 0x88a2a8, 0xd6a77a, 0x5e8c7f, 0xb8c4d6];
const PANTS = [0x3b4252, 0x5a4a42, 0x2f3e46, 0x6b705c, 0x4a4e69, 0x2d3142, 0x7a6a58];
const HAIR = [0x2b1d16, 0x4a3426, 0x7a5230, 0x141414, 0xb08b57, 0x5c5c5c, 0x3a2418];

// ---------- shared geometry ----------
const G = {
  pelvis: new THREE.CapsuleGeometry(.14, .07, 4, 12), torso: new THREE.CapsuleGeometry(.17, .3, 6, 16), neck: new THREE.CylinderGeometry(.05, .056, .1, 10),
  skull: new THREE.SphereGeometry(.125, 22, 16), hairCap: new THREE.SphereGeometry(.132, 22, 12, 0, Math.PI * 2, 0, Math.PI * .55),
  hairLong: new THREE.CapsuleGeometry(.105, .14, 4, 12), nose: new THREE.SphereGeometry(.022, 8, 6),
  upper: new THREE.CapsuleGeometry(.055, .2, 4, 10), fore: new THREE.CapsuleGeometry(.047, .18, 4, 10), hand: new THREE.SphereGeometry(.055, 10, 8),
  thigh: new THREE.CapsuleGeometry(.075, .28, 4, 10), shin: new THREE.CapsuleGeometry(.062, .3, 4, 10), foot: new RoundedBoxGeometry(.1, .07, .24, 2, .03),
  ring: new THREE.RingGeometry(.9, 1, 72),
};
const std = (color, roughness = .8, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness, metalness: 0, ...extra });

function softTexture(size, inner = .45) {
  const c = document.createElement("canvas"); c.width = c.height = size; const g = c.getContext("2d");
  const gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(.5, `rgba(255,255,255,${inner})`); gr.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = gr; g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const HAZE_TEX = softTexture(128), AIR_TEX = softTexture(64, .2);

// ---------- people ----------
const KEYS = ["hipsY", "thighL", "kneeL", "thighR", "kneeR", "spYaw", "spLean", "hdYaw", "hdPitch", "Lx", "Lz", "Le", "Rx", "Rz", "Re", "rootX"];
const standPose = () => ({ hipsY: .93, thighL: 0, kneeL: .04, thighR: 0, kneeR: .04, spYaw: 0, spLean: .02, hdYaw: 0, hdPitch: .02, Lx: .05, Lz: .1, Le: -.2, Rx: .05, Rz: .1, Re: -.2 });

function makePerson(parent, look, scale = 1) {
  const mats = { skin: std(look.skin, .62), shirt: std(look.shirt, .8), pants: std(look.pants, .85), hair: std(look.hair, .75), shoe: std(0x2a2a2d, .55) };
  const root = new THREE.Group(); root.scale.setScalar(scale);
  const grp = (p, x, y, z) => { const g = new THREE.Group(); g.position.set(x, y, z); p.add(g); return g; };
  const add = (p, geo, mat, x, y, z, cast = true) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = cast; p.add(m); return m; };
  const hips = grp(root, 0, .93, 0);
  add(hips, G.pelvis, mats.pants, 0, .02, 0, false).rotation.z = Math.PI / 2;
  const spine = grp(hips, 0, .06, 0);
  add(spine, G.torso, mats.shirt, 0, .3, 0).scale.set(1, 1, .74);
  const neck = grp(spine, 0, .58, 0);
  add(neck, G.neck, mats.skin, 0, .04, 0, false);
  const head = grp(neck, 0, .09, 0);
  add(head, G.skull, mats.skin, 0, .11, 0).scale.set(.9, 1.04, .98);
  add(head, G.hairCap, mats.hair, 0, .125, -.012, false).rotation.x = -.35;
  if (look.long) add(head, G.hairLong, mats.hair, 0, .02, -.085, false).scale.set(1, 1, .6);
  add(head, G.nose, mats.skin, 0, .1, .118, false);
  const arm = (side) => {
    const sh = grp(spine, side * .215, .47, 0); add(sh, G.upper, mats.shirt, 0, -.14, 0);
    const el = grp(sh, 0, -.29, 0); add(el, G.fore, mats.skin, 0, -.12, 0, false);
    add(el, G.hand, mats.skin, 0, -.255, .005, false).scale.set(.85, 1, .62);
    return { sh, el };
  };
  const leg = (side) => {
    const hp = grp(hips, side * .095, -.02, 0); add(hp, G.thigh, mats.pants, 0, -.2, 0);
    const kn = grp(hp, 0, -.43, 0); add(kn, G.shin, mats.pants, 0, -.2, 0); add(kn, G.foot, mats.shoe, 0, -.445, .05, false);
    return { hp, kn };
  };
  parent.add(root);
  return { root, hips, spine, neck, head, arms: [arm(1), arm(-1)], legs: [leg(1), leg(-1)], mats, all: Object.values(mats), pres: 0, opacity: 1, cur: null };
}
function applyPose(p, T, dt, k = 16) {
  if (!p.cur) p.cur = { ...T };
  const c = p.cur;
  for (const key of KEYS) if (T[key] !== undefined) c[key] = damp(c[key] ?? T[key], T[key], k, dt);
  p.hips.position.y = c.hipsY;
  if (T.rootX !== undefined) p.root.position.x = c.rootX;
  const seated = clamp(-c.thighL / 1.5, 0, 1);
  p.legs[0].hp.rotation.set(c.thighL, 0, .07 * seated); p.legs[0].kn.rotation.set(c.kneeL, 0, 0);
  p.legs[1].hp.rotation.set(c.thighR, 0, -.07 * seated); p.legs[1].kn.rotation.set(c.kneeR, 0, 0);
  p.spine.rotation.set(c.spLean, c.spYaw, 0);
  p.neck.rotation.set(c.hdPitch * .4, c.hdYaw * .45, 0);
  p.head.rotation.set(c.hdPitch * .6, c.hdYaw * .55, 0);
  p.arms[0].sh.rotation.set(c.Lx, 0, c.Lz); p.arms[0].el.rotation.set(c.Le, 0, 0);
  p.arms[1].sh.rotation.set(c.Rx, 0, -c.Rz); p.arms[1].el.rotation.set(c.Re, 0, 0);
}
function walkInto(T, phi) {
  const s = Math.sin(phi), c = Math.cos(phi);
  T.thighL = -.5 * s; T.thighR = .5 * s;
  T.kneeL = .1 + .85 * Math.max(0, c); T.kneeR = .1 + .85 * Math.max(0, -c);
  T.Lx = .42 * s; T.Rx = -.42 * s; T.Le = -.32; T.Re = -.32; T.Lz = .07; T.Rz = .07;
  T.hipsY = .945 - .03 * Math.abs(s); T.spYaw = .1 * s; T.spLean = .05;
}
function setPresence(p, target, dt, k = 2.6) {
  p.pres = damp(p.pres, target, k, dt);
  const o = p.pres < .004 ? 0 : p.pres;
  p.root.visible = o > 0;
  if (Math.abs(o - p.opacity) > .001) {
    for (const m of p.all) { const tr = o < .995; if (m.transparent !== tr) { m.transparent = tr; m.needsUpdate = true; } m.opacity = o; }
    p.opacity = o;
  }
}

/* createRoom(host, { onZoneClick }) -> { update(data), start(), stop() }
 * data: { dark, occupied, mode, walkers, ventilation (null = no fan unit), zones: [
 *   { id, name, node, word, look, lecturer, talking, loud, offline, haze 0..1, warm } ] } */
export function createRoom(host, { onZoneClick } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.setClearColor(0x000000, 0);
  const overlay = document.createElement("div"); overlay.className = "r3-overlay"; overlay.setAttribute("aria-hidden", "true");
  const note = document.createElement("p"); note.className = "r3-note";
  note.textContent = "Figures act out each area's sensed state. The nodes don't track individual people.";
  host.replaceChildren(renderer.domElement, overlay, note);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, 1.6, .1, 200);
  const TARGET = new THREE.Vector3(6.5, -.1, 4.7);
  const HOME = { az: Math.PI / 4 + .04, polar: .94, r: 21 };
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(TARGET);
  Object.assign(controls, { enableDamping: true, dampingFactor: .06, enablePan: false, rotateSpeed: .5, zoomSpeed: .6,
    minPolarAngle: .45, maxPolarAngle: 1.22, minDistance: 13, maxDistance: 42, minAzimuthAngle: HOME.az - .75, maxAzimuthAngle: HOME.az + .6, enabled: false });
  controls.enableZoom = false;   // The page scrolls under the wheel; dragging still orbits
  const placeCamera = (az, polar, r) => { camera.position.setFromSpherical(new THREE.Spherical(r, polar, az)).add(TARGET); camera.lookAt(TARGET); };

  const hemi = new THREE.HemisphereLight(0xffffff, 0xd9cfc1, 1.1);
  const sun = new THREE.DirectionalLight(0xfff1e0, 2.4);
  sun.position.set(13, 19, 12); sun.target.position.set(6, 0, 4);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -11, right: 11, top: 11, bottom: -11, near: 2, far: 50 });
  sun.shadow.bias = -.0004; sun.shadow.normalBias = .025;
  scene.add(hemi, sun, sun.target);

  const M = {
    slab: std(0), floor: std(0, .95), wall: std(0, 1), wall2: std(0, 1), board: std(0, .35), frame: std(0, .5), desk: std(0, .55), leg: std(0, .45, { metalness: .3 }),
    chair: std(0, .7), chairLeg: std(0, .4, { metalness: .4 }), paper: std(0xf6f4ef, .9), laptop: std(0x9aa0a8, .35, { metalness: .5 }),
    screen: std(0x1c2230, .3, { emissive: 0x3a5a8a, emissiveIntensity: .25 }), door: std(0, .6), handle: std(0xb9b2a6, .3, { metalness: .8 }),
    puck: std(0, .5), pot: std(0xcdbfae, .8), leaf: std(0x6f9a6a, .7), unit: std(0, .45), grille: std(0, .6), fan: std(0, .5),
    ring: std(0x2f7fe0, .3, { emissive: 0x2f7fe0, emissiveIntensity: 0 }),
  };

  let world = null, sig = "", zones = [], students = [], lec = null, walkers = [], rings = [], haze = [], airBits = [], pools = [];
  let doorPivot, fan, fanUnit, fanLight, doorAuto = 0, wasOccupied = null;
  const cur = { door: 0, fan: 0, fanAngle: 0 };
  const pairPhase = {};
  let data = null, dark = null;

  const box = (parent, w, h, d, mat, x, y, z, opts = {}) => {
    const m = new THREE.Mesh(opts.round ? new RoundedBoxGeometry(w, h, d, 2, opts.round) : new THREE.BoxGeometry(w, h, d), mat);
    m.position.set(x, y, z); m.castShadow = opts.cast !== false; m.receiveShadow = true; parent.add(m); return m;
  };
  function rrect(w, h, r) {
    const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
    s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
    s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
  }
  function disposeWorld() {
    if (!world) return;
    scene.remove(world);
    world.traverse((o) => {
      if (o.geometry && !Object.values(G).includes(o.geometry)) o.geometry.dispose();
      if (o.material && !Object.values(M).includes(o.material)) o.material.dispose();
    });
    overlay.replaceChildren();
  }

  // Build the room for this set of areas: the lecturer's band at the front,
  // the student areas front to back, desks in rows of four.
  function build(zs) {
    disposeWorld();
    seed = 11;
    world = new THREE.Group(); scene.add(world);
    box(world, 12.6, .36, 8.6, M.slab, 6, -.18, 4, { round: .14, cast: false });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_L, ROOM_W), M.floor);
    floor.rotation.x = -Math.PI / 2; floor.position.set(6, .002, 4); floor.receiveShadow = true; world.add(floor);
    box(world, 12.14, 2.5, .14, M.wall, 5.93, 1.25, -.07);
    box(world, .14, 2.5, 8, M.wall2, -.07, 1.25, 4);
    box(world, .03, 1.25, 3.5, M.frame, .005, 1.5, 4.45, { cast: false });
    box(world, .03, 1.15, 3.38, M.board, .02, 1.5, 4.45, { cast: false });
    box(world, .12, .03, 3.2, M.frame, .07, .9, 4.45);
    // Door at the front of the side wall; it opens when people arrive or leave
    box(world, 1.14, 2.14, .04, M.frame, 1.1, 1.07, .005, { cast: false });
    doorPivot = new THREE.Group(); doorPivot.position.set(.55, 0, .05); world.add(doorPivot);
    box(doorPivot, 1.06, 2.06, .05, M.door, .53, 1.03, 0);
    box(doorPivot, .04, .04, .14, M.handle, .95, 1.0, .04);
    // Lecturer's desk and a plant
    box(world, .75, .06, 1.5, M.desk, 1.85, .76, 6.95, { round: .02 });
    box(world, .7, .72, .05, M.leg, 1.85, .37, 6.25); box(world, .7, .72, .05, M.leg, 1.85, .37, 7.65);
    box(world, .24, .015, .32, M.laptop, 1.85, .8, 6.8); box(world, .012, .2, .32, M.screen, 1.72, .9, 6.8).rotation.z = .28;
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(.2, .15, .38, 20), M.pot); pot.position.set(.45, .19, 7.5); pot.castShadow = true; world.add(pot);
    [[0, .62, 0, .24], [.12, .78, .05, .18], [-.1, .8, -.06, .17], [.03, .95, -.02, .15], [-.05, .7, .12, .16]].forEach(([x, y, z, r]) => {
      const s = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 1), M.leaf); s.position.set(.45 + x, y, 7.5 + z); s.castShadow = true; world.add(s);
    });
    // Fresh-air fan unit in the back corner (simulation only)
    fanUnit = new THREE.Group(); fanUnit.position.set(11.45, 0, .5); world.add(fanUnit);
    box(fanUnit, .44, 1.0, .44, M.unit, 0, .5, 0, { round: .08 });
    const grille = new THREE.Mesh(new THREE.CylinderGeometry(.17, .17, .02, 32), M.grille); grille.position.y = 1.005; fanUnit.add(grille);
    fan = new THREE.Group(); fan.position.y = 1.02; fanUnit.add(fan);
    for (let i = 0; i < 5; i++) {
      const b = new THREE.Mesh(new THREE.BoxGeometry(.13, .008, .045), M.fan); b.position.x = .07; b.rotation.x = .5;
      const arm = new THREE.Group(); arm.rotation.y = i * Math.PI * 2 / 5; arm.add(b); fan.add(arm);
    }
    const ring = new THREE.Mesh(new THREE.TorusGeometry(.19, .012, 8, 48), M.ring); ring.rotation.x = Math.PI / 2; ring.position.y = 1.01; fanUnit.add(ring);
    box(fanUnit, .2, .05, .01, M.ring, 0, .78, .222, { cast: false });
    fanLight = new THREE.PointLight(0x5aa0ff, 0, 3.5, 1.8); fanLight.position.set(0, 1.3, .1); fanUnit.add(fanLight);
    airBits = Array.from({ length: 26 }, (_, i) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: AIR_TEX, color: 0x7fb6ff, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
      s.userData = { t: i / 26, a: rnd() * Math.PI * 2, sp: .7 + rnd() * .6 }; world.add(s); return s;
    });

    // Areas: bands along the room, each with a tile, outline, node puck and labels
    const lecturerZone = zs.find((z) => z.lecturer);
    const studentsZ = zs.filter((z) => !z.lecturer);
    const band = (ROOM_L - FRONT) / Math.max(1, studentsZ.length);
    zones = zs.map((z) => {
      const i = studentsZ.indexOf(z);
      const [a, b] = z.lecturer ? [0, FRONT] : [FRONT + i * band, FRONT + (i + 1) * band];
      const shape = rrect(b - a - .14, 7.86, .22);
      const tile = new THREE.Mesh(new THREE.ShapeGeometry(shape, 8), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
      tile.rotation.x = -Math.PI / 2; tile.position.set((a + b) / 2, .006, 4); world.add(tile);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(shape.getPoints(24)),
        new THREE.LineDashedMaterial({ transparent: true, opacity: 0, dashSize: 100, gapSize: 0 }));
      line.computeLineDistances(); line.rotation.x = -Math.PI / 2; line.position.set((a + b) / 2, .01, 4); world.add(line);
      const px = z.lecturer ? 2.15 : b - .5;
      box(world, .26, .09, .18, M.puck, px, .045, 7.7, { round: .03 });
      const led = new THREE.Mesh(new THREE.SphereGeometry(.024, 12, 8), std(0x3ddc84, .3, { emissive: 0x3ddc84, emissiveIntensity: 2 }));
      led.position.set(px - .06, .095, 7.7); world.add(led);
      const label = document.createElement("div"); label.className = "r3-zl"; label.innerHTML = "<span></span><b></b>";
      label.firstChild.textContent = z.name;
      const tag = document.createElement("div"); tag.className = "r3-tag"; tag.innerHTML = "<i></i><span></span>";
      tag.lastChild.textContent = z.node;
      overlay.append(label, tag);
      return { id: z.id, lecturer: !!z.lecturer, a, b, cx: (a + b) / 2, tile, line, led, label, tag, color: new THREE.Color(0x888888),
               anchor: new THREE.Vector3(px, .1, 7.7),
               // The lecturer's label sits on the front wall over the whiteboard's
               // centre; the others sit on the side wall above their own band.
               labelAnchor: z.lecturer ? new THREE.Vector3(-.07, 2.5, 4.45) : new THREE.Vector3((a + b) / 2, 2.72, .05) };
    });
    pools = zones.map((z) => { const l = new THREE.PointLight(0xffd7a8, 0, 7, 1.6); l.position.set(z.cx, 2.3, 4); world.add(l); return l; });

    // Students: one per desk, facing the board
    students = [];
    studentsZ.forEach((z, si) => {
      const zone = zones[zs.indexOf(z)];
      for (let x = zone.a + .72; x + .82 <= zone.b + .01; x += 1.5) for (let c = 0; c < 4; c++) {
        const dz = 1.25 + c * 1.72;
        box(world, .62, .05, 1.1, M.desk, x, .75, dz, { round: .02 });
        box(world, .5, .72, .04, M.leg, x, .37, dz - .5, { cast: false }); box(world, .5, .72, .04, M.leg, x, .37, dz + .5, { cast: false });
        box(world, .03, .38, 1.0, M.leg, x - .28, .52, dz, { cast: false });
        if (rnd() < .45) { box(world, .24, .015, .32, M.laptop, x + .02, .785, dz, { cast: false }); box(world, .012, .2, .32, M.screen, x - .11, .88, dz, { cast: false }).rotation.z = .28; }
        else box(world, .22, .012, .3, M.paper, x + .05, .781, dz + .12, { cast: false }).rotation.y = (rnd() - .5) * .5;
        const cx = x + .52;
        box(world, .42, .05, .44, M.chair, cx, .45, dz, { round: .02 });
        box(world, .05, .44, .42, M.chair, cx + .22, .72, dz, { round: .02 });
        const col = new THREE.Mesh(new THREE.CylinderGeometry(.025, .025, .42, 8), M.chairLeg); col.position.set(cx, .22, dz); world.add(col);
        const base = new THREE.Mesh(new THREE.CylinderGeometry(.2, .22, .025, 20), M.chairLeg); base.position.set(cx, .013, dz); world.add(base);
        const p = makePerson(world, { skin: pick(SKIN), shirt: pick(SHIRT), pants: pick(PANTS), hair: pick(HAIR), long: rnd() < .42 }, .94 + rnd() * .08);
        Object.assign(p, { zi: zs.indexOf(z), base: { x: cx - .04, z: dz }, side: c % 2 === 0 ? 1 : -1, pair: `${si}${x.toFixed(1)}${c >> 1}`,
          writer: rnd() < .45, fanner: rnd() < .4, rowdy: rnd() < .45, phase: rnd() * 10, rate: .8 + rnd() * .5, stand: 0 });
        pairPhase[p.pair] ??= rnd() * 5;
        p.root.position.set(p.base.x, 0, p.base.z); p.root.rotation.y = -Math.PI / 2;
        students.push(p);
      }
    });
    lec = { p: makePerson(world, { skin: 0xe0ac86, shirt: 0x2f4a8a, pants: 0x2b2f3a, hair: 0x2b1d16 }, 1.04), zi: lecturerZone ? zs.indexOf(lecturerZone) : -1,
            mode: "talk", timer: 2.5, target: 3.2, phi: 0, yaw: Math.PI / 2, act: 0 };
    lec.p.root.position.set(1.05, 0, 4.6);
    walkers = [
      { p: makePerson(world, { skin: pick(SKIN), shirt: pick(SHIRT), pants: pick(PANTS), hair: pick(HAIR), long: rnd() < .4 }), z: 7.25, x0: 3.0, x1: 11.2, x: 6, dir: 1, phi: 0, yaw: Math.PI / 2 },
      { p: makePerson(world, { skin: pick(SKIN), shirt: pick(SHIRT), pants: pick(PANTS), hair: pick(HAIR), long: rnd() < .4 }), z: .42, x0: 2.9, x1: 10.9, x: 9, dir: -1, phi: 1, yaw: -Math.PI / 2 },
    ];
    walkers.forEach((w) => w.p.root.position.set(w.x, 0, w.z));
    rings = Array.from({ length: 2 + 2 * zones.length }, () => {
      const m = new THREE.Mesh(G.ring, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.y = .015; world.add(m); return m;
    });
    haze = Array.from({ length: 18 }, () => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: HAZE_TEX, transparent: true, opacity: 0, depthWrite: false }));
      s.userData = { x: FRONT + .4 + rnd() * (ROOM_L - FRONT - .8), z: .7 + rnd() * 6.6, y: 1.1 + rnd() * 1.1, ph: rnd() * 6 };
      s.scale.setScalar(2.6 + rnd() * 1.6); world.add(s); return s;
    });
    bubbles = Array.from({ length: 16 }, () => { const b = document.createElement("div"); b.className = "r3-bub"; b.innerHTML = "<i></i><i></i><i></i>"; b.style.opacity = 0; overlay.append(b); return b; });
    fanTag = document.createElement("div"); fanTag.className = "r3-fan"; overlay.append(fanTag);
    applyPalette();
  }
  let bubbles = [], fanTag = null;

  function applyPalette() {
    const P = PALETTE[dark ? "dark" : "light"];
    for (const k of ["slab", "floor", "wall", "wall2", "board", "frame", "desk", "leg", "chair", "chairLeg", "door", "puck", "unit", "grille", "fan"]) M[k].color.setHex(P[k]);
    hemi.color.setHex(P.hemi[0]); hemi.groundColor.setHex(P.hemi[1]); hemi.intensity = P.hemi[2];
    sun.color.setHex(P.sun[0]); sun.intensity = P.sun[1];
    renderer.toneMappingExposure = P.exposure;
    pools.forEach((l) => { l.intensity = P.pool; });
    haze.forEach((s) => s.material.color.setHex(P.haze));
  }

  // ---------- size ----------
  function resize() {
    const w = host.clientWidth, h = host.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    HOME.r = w / h < 1.2 ? 32 : w / h < 1.5 ? 24 : 22.5;
  }
  new ResizeObserver(resize).observe(host);

  // ---------- clicking an area opens its details ----------
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit = new THREE.Vector3();
  let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6 || !onZoneClick) return;
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    if (!ray.ray.intersectPlane(ground, hit) || hit.z < 0 || hit.z > ROOM_W) return;
    const z = zones.find((q) => hit.x >= q.a && hit.x < q.b);
    if (z) onZoneClick(z.id);
  });

  // ---------- per-frame ----------
  const v3 = new THREE.Vector3(), headPos = new THREE.Vector3();
  function place(el, world3, dx = "-50%", dy = "-100%") {
    v3.copy(world3).project(camera);
    if (v3.z > 1) { el.style.visibility = "hidden"; return; }
    el.style.visibility = "";
    const x = (v3.x * .5 + .5) * host.clientWidth, y = (-v3.y * .5 + .5) * host.clientHeight;
    el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(${dx}, ${dy})`;
  }

  // The room's outline on screen: the convex hull of the floor slab and the two
  // walls. Everything else in the room is lower than the 2.5 m walls and sits
  // on the slab, so a label kept outside this outline never covers the model.
  const BOUNDS = [[-.3, 12.3, -.36, 0, -.3, 8.3], [-.14, 0, 0, 2.5, 0, 8], [-.14, 12, 0, 2.5, -.14, 0]]
    .flatMap(([x0, x1, y0, y1, z0, z1]) => [x0, x1].flatMap((x) => [y0, y1].flatMap((y) => [z0, z1].map((z) => new THREE.Vector3(x, y, z)))));
  function roomOutline() {
    const pts = BOUNDS.map((p) => { v3.copy(p).project(camera); return { x: (v3.x * .5 + .5) * host.clientWidth, y: (-v3.y * .5 + .5) * host.clientHeight }; })
      .sort((a, b) => a.x - b.x || a.y - b.y);
    const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const half = (list) => { const h = []; for (const p of list) { while (h.length > 1 && cross(h[h.length - 2], h[h.length - 1], p) <= 0) h.pop(); h.push(p); } h.pop(); return h; };
    const hull = [...half(pts), ...half([...pts].reverse())];
    return hull.map((p, i) => [p, hull[(i + 1) % hull.length]]);
  }
  // Place a label's bottom centre at world3, but keep its whole box above the
  // room's outline and inside the view. If there's no room above the outline
  // there, slide it left (toward the front of the room, where the wall top is
  // lower, or clear of the room altogether).
  function placeClear(el, world3, gap = 6) {
    v3.copy(world3).project(camera);
    if (v3.z > 1) { el.style.visibility = "hidden"; return; }
    el.style.visibility = "";
    const W = host.clientWidth, ax = (v3.x * .5 + .5) * W, ay = (-v3.y * .5 + .5) * host.clientHeight;
    const w = el.offsetWidth, h = el.offsetHeight, edges = roomOutline();
    // Lowest bottom (screen y) for a label centred on x that clears the outline.
    const bottomAt = (x) => {
      let y = Infinity;
      for (const [a, b] of edges) {
        const lo = Math.max(x - w / 2, Math.min(a.x, b.x)), hi = Math.min(x + w / 2, Math.max(a.x, b.x));
        if (lo > hi || a.x === b.x) continue;   // this edge isn't under the label
        for (const sx of [lo, hi]) y = Math.min(y, a.y + (sx - a.x) / (b.x - a.x) * (b.y - a.y) - gap);
      }
      return y === Infinity ? Math.max(ay - gap, h + 2) : Math.min(ay - gap, y);   // clear of the room: stay level with the anchor
    };
    let x = Math.min(Math.max(ax, w / 2 + 2), W - w / 2 - 2), y = bottomAt(x);
    for (let i = 0; i < 200 && y - h < 2 && x - w / 2 > 2; i++) { x -= 3; y = bottomAt(x); }
    el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
  }

  function updateStudent(p, t, dt, zd) {
    const z = zd[p.zi] || {};
    const talking = !!z.talking && !z.offline, loud = !!z.loud && !z.offline;
    p.stand = damp(p.stand, loud && p.rowdy ? 1 : 0, 2.2, dt);
    const s = p.stand, w = t * p.rate + p.phase;
    const turn = Math.floor((t + pairPhase[p.pair]) / 2.6) % 2;
    p.speaking = talking && (loud || (turn === 0) === (p.side > 0));
    const T = { hipsY: lerp(.53, .93, s) + (s > .5 ? .03 * Math.abs(Math.sin(w * 4.5)) * MOTION : 0), rootX: p.base.x + s * .32,
      thighL: lerp(-1.52, 0, s), kneeL: lerp(1.52, .06, s), thighR: lerp(-1.52, 0, s), kneeR: lerp(1.52, .06, s),
      spYaw: 0, spLean: .07, hdYaw: 0, hdPitch: .05, Lx: -.28, Lz: .1, Le: -1.32, Rx: -.28, Rz: .1, Re: -1.32 };
    if (!talking) {
      T.hdYaw = .2 * Math.sin(w * .23) * MOTION; T.hdPitch = .06 + .05 * Math.sin(w * .5) * MOTION;
      if (p.writer) { T.hdPitch = .45; T.spLean = .17; T.Rx = -.38; T.Re = -1.22 + .08 * Math.sin(w * 8) * MOTION; T.Rz = .04 + .03 * Math.sin(w * 3.1) * MOTION; }
      if ((z.haze > .35 || z.warm) && p.fanner) { T.Rx = -1.0; T.Rz = .5; T.Re = -2.1 + .38 * Math.sin(w * 10) * MOTION; T.hdPitch = -.08; T.spLean = -.04; }
    } else {
      const k = loud ? 1.8 : 1, g = Math.sin(w * 3 * k) * MOTION, g2 = Math.sin(w * 2.2 * k + 1.1) * MOTION;
      const toward = p.side;
      T.hdYaw = toward * (p.speaking ? .55 : .72) + .1 * g2; T.spYaw = toward * .27;
      T.hdPitch = p.speaking ? .05 * Math.sin(w * 6) * MOTION : .12 * Math.max(0, Math.sin(w * 2.4)) * MOTION;
      const gest = p.speaking ? [-.85 + .32 * g * k, .26 + .14 * g2, -1.5 + .55 * g2] : [-.3, .1, -1.3];
      if (toward > 0) [T.Lx, T.Lz, T.Le] = gest; else [T.Rx, T.Rz, T.Re] = gest;
      if (p.speaking && loud) { const g3 = [-.95 + .38 * g2, .32, -1.2 + .5 * g]; if (toward > 0) [T.Rx, T.Rz, T.Re] = g3; else [T.Lx, T.Lz, T.Le] = g3; T.spLean = -.1 + .1 * g; }
      if (s > .5) { T.Lx = -2.5 + .38 * g; T.Lz = .35 + .2 * g2; T.Le = -.45; T.Rx = -2.5 - .38 * g; T.Rz = .35 - .2 * g2; T.Re = -.45; T.hdPitch = -.2; T.spYaw = toward * .45 * Math.sin(w * .8); }
    }
    applyPose(p, T, dt);
    setPresence(p, data.occupied ? (z.offline ? .32 : 1) : 0, dt);
    const glow = PALETTE[dark ? "dark" : "light"].glow * (talking ? (p.speaking ? 1 : .55) : 0);
    p.mats.shirt.emissive.copy(zones[p.zi].color); p.mats.shirt.emissiveIntensity = damp(p.mats.shirt.emissiveIntensity, glow, 4, dt);
  }

  function updateLecturer(t, dt, zd) {
    const p = lec.p, z = zd[lec.zi] || {}, speaking = z.look === "speak";
    const T = standPose();
    if (lec.mode === "walk") {
      const zp = p.root.position.z, d = lec.target - zp, dir = Math.sign(d) || 1, v = .8 * MOTION + .2;
      p.root.position.z += dir * Math.min(Math.abs(d), v * dt);
      lec.phi += dt * v / .62 * Math.PI;
      walkInto(T, lec.phi);
      lec.yawT = dir > 0 ? 0 : Math.PI;
      if (Math.abs(d) < .02) { lec.mode = speaking && lec.act++ % 3 === 2 ? "point" : "talk"; lec.timer = lec.mode === "point" ? 2.6 : (speaking ? 3.4 : 6); }
    } else {
      lec.timer -= dt;
      if (lec.mode === "talk") {
        lec.yawT = Math.PI / 2;
        if (speaking) {
          T.Lx = -.55 + .22 * Math.sin(t * 2.1) * MOTION; T.Lz = .25; T.Le = -1.5 + .38 * Math.sin(t * 2.6) * MOTION;
          T.Rx = -.6 + .26 * Math.sin(t * 2.4 + 1) * MOTION; T.Rz = .3; T.Re = -1.45 + .38 * Math.sin(t * 3.1 + .5) * MOTION;
          T.hdYaw = .38 * Math.sin(t * .6) * MOTION; T.spYaw = .1 * Math.sin(t * .6) * MOTION;
        } else { T.Lx = -.35; T.Lz = -.15; T.Le = -1.25; T.Rx = -.35; T.Rz = -.15; T.Re = -1.25; T.hdYaw = .5 * Math.sin(t * .3); }
      } else {
        lec.yawT = -Math.PI / 2 + .35;
        T.Rx = -1.75 + .06 * Math.sin(t * 3); T.Rz = .12; T.Re = -.12; T.hdPitch = -.12; T.hdYaw = -.15;
      }
      if (lec.timer <= 0) { lec.target = p.root.position.z < 4.6 ? 6.1 : 3.1; lec.mode = "walk"; }
    }
    lec.yaw = dampAngle(lec.yaw, lec.yawT ?? lec.yaw, 5, dt); p.root.rotation.y = lec.yaw;
    applyPose(p, T, dt);
    setPresence(p, data.occupied ? 1 : 0, dt);
    return speaking;
  }

  function updateWalker(w, i, t, dt) {
    setPresence(w.p, data.occupied && i < (data.walkers || 0) ? 1 : 0, dt);
    if (w.p.pres < .01) return;
    const v = .55 + .15 * i;
    w.x += w.dir * v * dt * (MOTION * .7 + .3);
    if (w.x > w.x1) w.dir = -1; if (w.x < w.x0) w.dir = 1;
    w.phi += dt * v / .6 * Math.PI;
    w.yaw = dampAngle(w.yaw, w.dir > 0 ? Math.PI / 2 : -Math.PI / 2, 4, dt);
    w.p.root.position.set(w.x, 0, w.z); w.p.root.rotation.y = w.yaw;
    const T = standPose(); walkInto(T, w.phi); applyPose(w.p, T, dt);
  }

  let introStart = null, last = 0, raf = 0, running = false;
  function frame(now) {
    raf = running ? requestAnimationFrame(frame) : 0;
    if (!data || !world || host.offsetParent === null) return;   // Hidden page or view: don't draw
    const dt = Math.min(.05, last ? (now - last) / 1000 : .016); last = now;
    const t = now / 1000, P = PALETTE[dark ? "dark" : "light"], zd = data.zones;

    // Camera: a short fly-in the first time, then the visitor can orbit
    if (!controls.enabled) {
      introStart ??= now;
      const e = reduce ? 1 : easeOut(Math.min(1, (now - introStart) / 2400));
      placeCamera(HOME.az + .55 * (1 - e), lerp(.5, HOME.polar, e), lerp(40, HOME.r, e));
      if (e >= 1) { controls.enabled = true; controls.update(); }
    } else controls.update();

    // Door opens for a few seconds whenever the room fills or empties
    if (wasOccupied !== null && wasOccupied !== data.occupied) doorAuto = 4.5;
    wasOccupied = data.occupied;
    doorAuto = Math.max(0, doorAuto - dt);
    cur.door = damp(cur.door, doorAuto > 0 ? 1 : 0, 3, dt);
    doorPivot.rotation.y = -1.35 * cur.door;

    // Fresh-air fan: only when the simulator offers one
    fanUnit.visible = data.ventilation !== null && data.ventilation !== undefined;
    cur.fan = damp(cur.fan, data.ventilation ? 1 : 0, 2.2, dt);
    cur.fanAngle += dt * (2 + 26 * cur.fan); fan.rotation.y = cur.fanAngle;
    M.ring.emissiveIntensity = .15 + 2.6 * cur.fan * (.85 + .15 * Math.sin(t * 2.4));
    M.ring.color.setHex(cur.fan > .5 ? 0x2f7fe0 : 0x8a9099);
    fanLight.intensity = 3 * cur.fan * (fanUnit.visible ? 1 : 0);
    airBits.forEach((s) => {
      const u = s.userData; u.t = (u.t + dt * .22 * u.sp) % 1;
      const r = u.t * 3.4, a = u.a + u.t * 1.2;
      s.position.set(11.45 - r * .75 + Math.cos(a) * .25 * u.t, 1.08 + Math.sin(u.t * Math.PI) * 1.1, .5 + r * .62 + Math.sin(a) * .25 * u.t);
      s.material.opacity = fanUnit.visible ? cur.fan * Math.sin(u.t * Math.PI) * .55 : 0;
      s.scale.setScalar(.12 + u.t * .3);
    });
    if (fanTag) {
      fanTag.hidden = !fanUnit.visible;
      fanTag.textContent = data.ventilation ? "Fresh-air fan · on" : "Fresh-air fan · off";
      fanTag.classList.toggle("on", !!data.ventilation);
      if (fanUnit.visible) place(fanTag, v3.set(11.45, 1.35, .5).clone());
    }

    // Areas: tint, outline, words, node LED; haze where CO2 is high
    zones.forEach((z, i) => {
      const d = zd[i] || {}, look = d.offline ? "none" : d.look || "none";
      z.color.lerp(cssColor(`--look-${look}`), 1 - Math.exp(-4 * dt));
      z.tile.material.color.copy(z.color); z.line.material.color.copy(z.color);
      z.tile.material.opacity = damp(z.tile.material.opacity, d.offline ? .06 : look === "none" ? 0 : P.tint, 4, dt);
      z.line.material.opacity = damp(z.line.material.opacity, look === "none" && !d.offline ? 0 : .7, 4, dt);
      z.line.material.dashSize = d.offline ? .22 : 100; z.line.material.gapSize = d.offline ? .16 : 0;
      z.label.lastChild.textContent = d.word || "";
      z.label.dataset.look = d.offline ? "none" : look;
      z.tag.classList.toggle("off", !!d.offline);
      z.led.material.emissiveIntensity = d.offline ? 0 : 2 + .3 * Math.sin(t * 2 + i);
      z.led.material.color.setHex(d.offline ? 0x555a62 : 0x3ddc84);
      z.hazeNow = damp(z.hazeNow ?? 0, d.offline ? 0 : d.haze || 0, .6, dt);
      if (z.lecturer) placeClear(z.label, z.labelAnchor); else place(z.label, z.labelAnchor);
      place(z.tag, z.anchor, "-50%", "10px");
    });
    haze.forEach((s) => {
      const u = s.userData, z = zones.find((q) => u.x >= q.a && u.x < q.b);
      s.position.set(u.x + .35 * Math.sin(t * .11 + u.ph), u.y + .15 * Math.sin(t * .23 + u.ph), u.z + .3 * Math.cos(t * .09 + u.ph));
      s.material.opacity = (z ? z.hazeNow : 0) * (dark ? .32 : .5) * (.75 + .25 * Math.sin(t * .4 + u.ph));
    });

    // People
    students.forEach((p) => updateStudent(p, t, dt, zd));
    const lecturing = updateLecturer(t, dt, zd);
    walkers.forEach((w, i) => updateWalker(w, i, t, dt));

    // Sound rings: from the lecturer, and over any area with excessive noise
    let ri = 0;
    const pulse = (x, zz, col, speed, size, phase) => {
      const m = rings[ri++]; if (!m) return;
      const u = (t * speed + phase) % 1;
      m.position.x = x; m.position.z = zz; m.scale.setScalar(.3 + u * size);
      m.material.color.copy(col); m.material.opacity = (1 - u) * .55;
    };
    const lp = lec.p.root.position;
    if (lecturing && lec.p.pres > .5) { const c = zones[lec.zi].color; pulse(lp.x, lp.z, c, .55, 2.6, 0); pulse(lp.x, lp.z, c, .55, 2.6, .5); }
    zones.forEach((z, i) => { if (zd[i] && zd[i].loud && !zd[i].offline) { pulse(z.cx, 4, z.color, .9, 3.2, 0); pulse(z.cx, 4, z.color, .9, 3.2, .5); } });
    for (; ri < rings.length; ri++) rings[ri].material.opacity = 0;

    // Speech bubbles over whoever is speaking
    let bi = 0;
    for (const p of students) {
      if (!p.speaking || p.pres < .5 || bi >= bubbles.length) continue;
      const d = zd[p.zi] || {};
      if (!d.loud && p.side < 0 && bi % 2) continue;   // keep it readable
      const b = bubbles[bi++];
      p.head.getWorldPosition(headPos); headPos.y += .42;
      place(b, headPos); b.style.opacity = Math.min(1, p.pres); b.classList.toggle("loud", !!d.loud);
    }
    for (; bi < bubbles.length; bi++) bubbles[bi].style.opacity = 0;

    renderer.render(scene, camera);
  }

  return {
    update(next) {
      const s = next.zones.map((z) => `${z.id}:${z.lecturer ? 1 : 0}:${z.name}:${z.node}`).join("|");
      if (next.dark !== dark) { dark = next.dark; if (world) applyPalette(); }
      if (s !== sig) { sig = s; build(next.zones); }
      data = next;
      host.setAttribute("aria-label", "Classroom in 3D with people acting out each area's state. " +
        next.zones.map((z) => `${z.name}: ${z.word}`).join(". ") + ".");
    },
    start() { if (running) return; running = true; last = 0; resize(); raf = requestAnimationFrame(frame); },
    stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; },
    // Test hook: step the scene by hand (a hidden tab barely runs requestAnimationFrame)
    advance(seconds) { const was = running; running = false; let now = last || performance.now(); for (let i = 0; i < Math.ceil(seconds / .033); i++) { now += 33; frame(now); } running = was; },
    snapshot() { this.advance(.05); return renderer.domElement.toDataURL("image/jpeg", .9); },
  };
}
