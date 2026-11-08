// Cloudbreak concept film — overlays, UI, shots, compositor
import * as THREE from 'three';
import { SUN, rng, makeHeight, buildSky, buildTerrain, buildWater, buildTrees, buildProps, buildPeople, buildStation, buildGrass, buildPlane } from './world.js';
import { buildTreesReal, buildTerrainReal, buildWaterReal, buildGrassReal, buildPlaneReal } from './real.js';

const VW = 1920, VH = 804, OW = 1920, OH = 1080, BAR = 138, FPS = 30;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const sm = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const smr = (t) => { t = clamp(t, 0, 1); return t * t * t * (t * (t * 6 - 15) + 10); };
const V3 = (x, y, z) => new THREE.Vector3(x, y, z);
const lerpV = (a, b, t) => a.clone().lerp(b, t);

const S = {};   // global film state

// ------------------------------------------------------------ mission sampling
function initMission(MI) {
  const n = MI.n, dt = 1 / MI.fps;
  const rpm = new Float32Array(n), ang = new Float32Array(n), dist = new Float32Array(n);
  for (let i = 1; i < n; i++) {
    const thr = MI.thr[i], tau = thr > rpm[i - 1] ? 0.45 : 1.3;
    rpm[i] = rpm[i - 1] + (thr - rpm[i - 1]) * (1 - Math.exp(-dt / tau));
    ang[i] = ang[i - 1] + 2 * Math.PI * 42 * rpm[i] * dt;
    dist[i] = dist[i - 1] + MI.v[i] * dt;
  }
  MI.rpm = rpm; MI.ang = ang; MI.dist = dist;
}
function ms(t) {
  const MI = S.MI, f = (t - MI.t0) * MI.fps;
  let i = Math.floor(f), a = f - i;
  if (i < 0) { i = 0; a = 0; } if (i > MI.n - 2) { i = MI.n - 2; a = 1; }
  const g = (k) => MI[k][i] * (1 - a) + MI[k][i + 1] * a;
  return { t, x: g('x'), y: g('y'), z: g('z'), h: g('h'), pitch: g('pitch'), bank: g('bank'), v: g('v'), thr: g('thr'), ail: g('ail'), ele: g('ele'), rud: g('rud'), rpm: g('rpm'), ang: g('ang'), dist: g('dist') };
}
const CGH = 0.19;
const ppos = (t) => { const s = ms(t); return V3(s.x, s.y + CGH, s.z); };
const hframe = (h) => ({ fwd: V3(Math.cos(h), 0, Math.sin(h)), right: V3(-Math.sin(h), 0, Math.cos(h)), up: V3(0, 1, 0) });
const shake = (t, amp, f = 1) => V3(amp * (Math.sin(t * 2.1 * f) * 0.6 + Math.sin(t * 5.3 * f + 1.3) * 0.3 + Math.sin(t * 11.7 * f + 0.4) * 0.1),
  amp * (Math.sin(t * 1.7 * f + 2.0) * 0.6 + Math.sin(t * 4.9 * f + 0.2) * 0.3 + Math.sin(t * 13.1 * f) * 0.1),
  amp * (Math.sin(t * 2.6 * f + 4.0) * 0.6 + Math.sin(t * 6.1 * f + 3.3) * 0.4));

// ------------------------------------------------------------ canvas helpers
function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
function glowTex(inner = 'rgba(255,255,255,1)', outer = 'rgba(255,255,255,0)', ring = false) {
  const c = canvas(128, 128), x = c.getContext('2d');
  const g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, inner); g.addColorStop(ring ? 0.25 : 0.35, inner.replace(/[\d.]+\)$/, '0.55)')); g.addColorStop(1, outer);
  x.fillStyle = g; x.fillRect(0, 0, 128, 128);
  if (ring) { x.strokeStyle = 'rgba(255,255,255,0.95)'; x.lineWidth = 7; x.beginPath(); x.arc(64, 64, 44, 0, Math.PI * 2); x.stroke(); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
function gradTexV() { // vertical: bottom opaque -> top transparent
  const c = canvas(4, 128), x = c.getContext('2d'); const g = x.createLinearGradient(0, 128, 0, 0);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.15, 'rgba(255,255,255,0.65)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, 4, 128); const t = new THREE.CanvasTexture(c); return t;
}

// ------------------------------------------------------------ icons (2D)
function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
const IC = {
  check(c, x, y, s, col = '#fff', lw = 0.16) { c.save(); c.strokeStyle = col; c.lineWidth = s * lw; c.lineCap = 'round'; c.lineJoin = 'round'; c.beginPath(); c.moveTo(x - s * 0.32, y + s * 0.02); c.lineTo(x - s * 0.08, y + s * 0.26); c.lineTo(x + s * 0.36, y - s * 0.24); c.stroke(); c.restore(); },
  cross(c, x, y, s, col = '#fff') { c.save(); c.strokeStyle = col; c.lineWidth = s * 0.16; c.lineCap = 'round'; c.beginPath(); c.moveTo(x - s * 0.25, y - s * 0.25); c.lineTo(x + s * 0.25, y + s * 0.25); c.moveTo(x + s * 0.25, y - s * 0.25); c.lineTo(x - s * 0.25, y + s * 0.25); c.stroke(); c.restore(); },
  drop(c, x, y, s, col) { c.save(); c.fillStyle = col; c.beginPath(); c.moveTo(x, y - s * 0.42); c.bezierCurveTo(x + s * 0.32, y - s * 0.05, x + s * 0.34, y + s * 0.38, x, y + s * 0.38); c.bezierCurveTo(x - s * 0.34, y + s * 0.38, x - s * 0.32, y - s * 0.05, x, y - s * 0.42); c.fill(); c.restore(); },
  person(c, x, y, s, col) { c.save(); c.fillStyle = col; c.beginPath(); c.arc(x, y - s * 0.22, s * 0.15, 0, Math.PI * 2); c.fill(); c.beginPath(); c.moveTo(x - s * 0.28, y + s * 0.38); c.quadraticCurveTo(x - s * 0.28, y - s * 0.02, x, y - s * 0.02); c.quadraticCurveTo(x + s * 0.28, y - s * 0.02, x + s * 0.28, y + s * 0.38); c.closePath(); c.fill(); c.restore(); },
  question(c, x, y, s, col) { c.save(); c.strokeStyle = col; c.fillStyle = col; c.lineWidth = s * 0.13; c.lineCap = 'round'; c.beginPath(); c.arc(x, y - s * 0.12, s * 0.2, Math.PI * 1.05, Math.PI * 2.35); c.lineTo(x, y + s * 0.13); c.stroke(); c.beginPath(); c.arc(x, y + s * 0.33, s * 0.075, 0, Math.PI * 2); c.fill(); c.restore(); },
  plane(c, x, y, s, col, rot = 0) { c.save(); c.translate(x, y); c.rotate(rot); c.fillStyle = col; c.beginPath();
    c.moveTo(0, -s * 0.45); c.lineTo(s * 0.06, -s * 0.3); c.lineTo(s * 0.06, -s * 0.08); c.lineTo(s * 0.45, 0.0); c.lineTo(s * 0.45, s * 0.07); c.lineTo(s * 0.06, s * 0.04); c.lineTo(s * 0.05, s * 0.3); c.lineTo(s * 0.17, s * 0.38); c.lineTo(s * 0.17, s * 0.44); c.lineTo(0, s * 0.4);
    c.lineTo(-s * 0.17, s * 0.44); c.lineTo(-s * 0.17, s * 0.38); c.lineTo(-s * 0.05, s * 0.3); c.lineTo(-s * 0.06, s * 0.04); c.lineTo(-s * 0.45, s * 0.07); c.lineTo(-s * 0.45, 0); c.lineTo(-s * 0.06, -s * 0.08); c.lineTo(-s * 0.06, -s * 0.3); c.closePath(); c.fill(); c.restore(); },
  signal(c, x, y, s, col, n = 4) { c.save(); c.fillStyle = col; for (let i = 0; i < 4; i++) { c.globalAlpha = i < n ? 1 : 0.25; rr(c, x - s * 0.36 + i * s * 0.2, y + s * 0.3 - s * (0.18 + i * 0.16), s * 0.13, s * (0.18 + i * 0.16), s * 0.03); c.fill(); } c.restore(); },
  key(c, x, y, s, col) { c.save(); c.strokeStyle = col; c.lineWidth = s * 0.12; c.lineCap = 'round'; c.beginPath(); c.arc(x - s * 0.15, y, s * 0.17, 0, Math.PI * 2); c.moveTo(x + 0.02 * s, y); c.lineTo(x + s * 0.38, y); c.moveTo(x + s * 0.27, y); c.lineTo(x + s * 0.27, y + s * 0.15); c.moveTo(x + s * 0.36, y); c.lineTo(x + s * 0.36, y + s * 0.12); c.stroke(); c.restore(); },
  route(c, x, y, s, col) { c.save(); c.strokeStyle = col; c.fillStyle = col; c.lineWidth = s * 0.1; c.lineCap = 'round'; c.setLineDash([s * 0.12, s * 0.1]); c.beginPath(); c.moveTo(x - s * 0.34, y + s * 0.28); c.bezierCurveTo(x - s * 0.1, y + s * 0.3, x - s * 0.2, y - s * 0.25, x + s * 0.3, y - s * 0.26); c.stroke(); c.setLineDash([]); c.beginPath(); c.arc(x - s * 0.34, y + s * 0.28, s * 0.08, 0, 7); c.fill(); c.beginPath(); c.arc(x + s * 0.32, y - s * 0.26, s * 0.08, 0, 7); c.fill(); c.restore(); },
  grid(c, x, y, s, col) { c.save(); c.strokeStyle = col; c.lineWidth = s * 0.08; for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) { c.globalAlpha = (i + j) % 2 ? 0.6 : 1; c.strokeRect(x - s * 0.36 + i * s * 0.24, y - s * 0.36 + j * s * 0.24, s * 0.2, s * 0.2); } c.restore(); },
  cone(c, x, y, s, col) { c.save(); c.fillStyle = col; c.beginPath(); c.moveTo(x, y - s * 0.38); c.lineTo(x + s * 0.24, y + s * 0.28); c.lineTo(x - s * 0.24, y + s * 0.28); c.closePath(); c.fill(); c.fillStyle = 'rgba(10,16,26,0.85)'; c.fillRect(x - s * 0.13, y - s * 0.02, s * 0.26, s * 0.07); c.fillRect(x - s * 0.36, y + s * 0.28, s * 0.72, s * 0.08); c.restore(); },
  glide(c, x, y, s, col) { c.save(); c.strokeStyle = col; c.lineWidth = s * 0.1; c.lineCap = 'round'; c.beginPath(); c.moveTo(x - s * 0.38, y + s * 0.3); c.lineTo(x + s * 0.38, y + s * 0.3); c.stroke(); c.setLineDash([s * 0.1, s * 0.08]); c.beginPath(); c.moveTo(x + s * 0.36, y - s * 0.3); c.lineTo(x - s * 0.22, y + s * 0.24); c.stroke(); c.restore(); IC.plane(c, x + s * 0.3, y - s * 0.3, s * 0.36, col, -2.4); },
  spark(c, x, y, s, col) { c.save(); c.fillStyle = col; const star = (cx, cy, r) => { c.beginPath(); c.moveTo(cx, cy - r); c.quadraticCurveTo(cx, cy, cx + r, cy); c.quadraticCurveTo(cx, cy, cx, cy + r); c.quadraticCurveTo(cx, cy, cx - r, cy); c.quadraticCurveTo(cx, cy, cx, cy - r); c.fill(); }; star(x - s * 0.06, y + s * 0.04, s * 0.36); star(x + s * 0.28, y - s * 0.26, s * 0.16); c.restore(); },
  shield(c, x, y, s, stroke, fill) { c.save(); c.beginPath(); c.moveTo(x, y - s * 0.5); c.quadraticCurveTo(x + s * 0.25, y - s * 0.38, x + s * 0.42, y - s * 0.38); c.quadraticCurveTo(x + s * 0.44, y + s * 0.2, x, y + s * 0.52); c.quadraticCurveTo(x - s * 0.44, y + s * 0.2, x - s * 0.42, y - s * 0.38); c.quadraticCurveTo(x - s * 0.25, y - s * 0.38, x, y - s * 0.5); c.closePath(); if (fill) { c.fillStyle = fill; c.fill(); } if (stroke) { c.strokeStyle = stroke; c.lineWidth = s * 0.05; c.stroke(); } c.restore(); },
  lock(c, x, y, s, col, closed) { c.save(); c.fillStyle = col; c.strokeStyle = col; c.lineWidth = s * 0.1; rr(c, x - s * 0.24, y - s * 0.02, s * 0.48, s * 0.36, s * 0.06); c.fill(); const lift = (1 - closed) * s * 0.16; c.beginPath(); c.arc(x, y - s * 0.06 - lift, s * 0.15, Math.PI, 0); c.lineTo(x + s * 0.15, y - s * 0.02 - lift * (1 - closed)); c.moveTo(x - s * 0.15, y - s * 0.06 - lift); c.lineTo(x - s * 0.15, y - s * 0.02 - lift * 0.0 - (closed < 1 ? lift : 0)); c.stroke(); c.fillStyle = 'rgba(8,20,16,0.9)'; c.beginPath(); c.arc(x, y + s * 0.13, s * 0.05, 0, 7); c.fill(); c.restore(); },
  cursor(c, x, y, s, press) { c.save(); c.translate(x, y); c.scale(press ? 0.9 : 1, press ? 0.9 : 1); c.beginPath(); c.moveTo(0, 0); c.lineTo(0, s * 0.95); c.lineTo(s * 0.26, s * 0.72); c.lineTo(s * 0.44, s * 1.08); c.lineTo(s * 0.58, s * 1.0); c.lineTo(s * 0.4, s * 0.66); c.lineTo(s * 0.72, s * 0.64); c.closePath(); c.fillStyle = '#fff'; c.shadowColor = 'rgba(0,0,0,0.5)'; c.shadowBlur = s * 0.2; c.fill(); c.shadowBlur = 0; c.strokeStyle = '#111'; c.lineWidth = s * 0.06; c.stroke(); c.restore(); },
};

// ------------------------------------------------------------ UI panel (laptop app)
const GREEN = '#3ddc84', CYAN = '#5fe3ff';
function drawUI(c, X, Y, W, H, st) {
  const u = (v) => v * H;   // scale by panel height
  c.save();
  c.globalAlpha = st.alpha ?? 1;
  // panel
  c.shadowColor = 'rgba(0,0,0,0.55)'; c.shadowBlur = u(0.06);
  rr(c, X, Y, W, H, u(0.035)); c.fillStyle = 'rgba(12,19,30,0.94)'; c.fill(); c.shadowBlur = 0;
  c.strokeStyle = 'rgba(255,255,255,0.10)'; c.lineWidth = u(0.003); c.stroke();
  // map
  const mx = X + W * 0.022, my = Y + H * 0.05, mw = W * 0.585, mh = H * 0.90;
  c.save(); rr(c, mx, my, mw, mh, u(0.02)); c.clip();
  if (S.mapImg) { const img = S.mapImg, ia = img.width / img.height, ra = mw / mh; let sw, sh2, sx, sy; if (ia > ra) { sh2 = img.height; sw = sh2 * ra; sx = (img.width - sw) / 2; sy = 0; } else { sw = img.width; sh2 = sw / ra; sx = 0; sy = (img.height - sh2) / 2; }
    st._map = { mx, my, mw, mh, sx, sy, sw, sh: sh2, iw: img.width, ih: img.height };
    c.drawImage(img, sx, sy, sw, sh2, mx, my, mw, mh); }
  c.fillStyle = 'rgba(8,14,24,0.18)'; c.fillRect(mx, my, mw, mh);
  const w2m = (x, z) => { const M = st._map; const px = (x + 200) / 440 * M.iw, py = (z + 160) / 270 * M.ih; return [M.mx + (px - M.sx) / M.sw * M.mw, M.my + (py - M.sy) / M.sh * M.mh]; };
  if (st._map) {
    // approach path (dashed, animated)
    const a = w2m(190, -50), b = w2m(15, -50);
    c.save(); c.strokeStyle = 'rgba(110,255,190,0.95)'; c.lineWidth = u(0.008); c.setLineDash([u(0.02), u(0.016)]); c.lineDashOffset = -st.t * u(0.08);
    c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke(); c.restore();
    // winner strip outline pulse
    const p0 = w2m(-40, -55), p1 = w2m(40, -45), pul = 0.5 + 0.5 * Math.sin(st.t * 4);
    c.save(); c.strokeStyle = GREEN; c.lineWidth = u(0.006 + 0.004 * pul); c.shadowColor = GREEN; c.shadowBlur = u(0.03); c.strokeRect(p0[0], p0[1], p1[0] - p0[0], p1[1] - p0[1]); c.restore();
    // live plane marker
    if (st.planeXZ) { const q = w2m(st.planeXZ[0], st.planeXZ[1]); c.save(); c.fillStyle = 'rgba(255,255,255,0.25)'; c.beginPath(); c.arc(q[0], q[1], u(0.03 + 0.012 * pul), 0, 7); c.fill(); IC.plane(c, q[0], q[1], u(0.045), '#fff', st.planeH + Math.PI / 2); c.restore(); }
  }
  c.restore();
  // right column
  const cx = X + W * 0.64;
  IC.spark(c, cx + u(0.03), Y + H * 0.12, u(0.07), CYAN);
  for (let i = 0; i < 3; i++) { c.fillStyle = `rgba(95,227,255,${0.3 + 0.7 * (0.5 + 0.5 * Math.sin(st.t * 6 - i * 0.8)) * (st.thinking ?? 0)})`; c.beginPath(); c.arc(cx + u(0.1 + i * 0.035), Y + H * 0.12, u(0.009), 0, 7); c.fill(); }
  // status top-right
  IC.signal(c, X + W * 0.90, Y + H * 0.115, u(0.05), 'rgba(255,255,255,0.75)', 4);
  const pg = st.sendArrive ?? 0;
  c.save(); if (pg > 0) { c.shadowColor = GREEN; c.shadowBlur = u(0.05) * pg; } IC.plane(c, X + W * 0.955, Y + H * 0.115, u(0.06), pg > 0.5 ? GREEN : 'rgba(255,255,255,0.85)', 0); c.restore();
  const rows = [['grid', st.bars?.[0] ?? 0, 0.92], ['cone', st.bars?.[1] ?? 0, 0.86], ['glide', st.bars?.[2] ?? 0, 0.95]];
  rows.forEach(([ic, f, full], i) => {
    const y = Y + H * (0.27 + i * 0.125);
    IC[ic](c, cx + u(0.035), y, u(0.07), 'rgba(255,255,255,0.85)');
    const bx = cx + u(0.1), bw = W * 0.255, bh = u(0.022);
    rr(c, bx, y - bh / 2, bw, bh, bh / 2); c.fillStyle = 'rgba(255,255,255,0.08)'; c.fill();
    if (f > 0) { rr(c, bx, y - bh / 2, Math.max(bh, bw * full * f), bh, bh / 2); const g = c.createLinearGradient(bx, 0, bx + bw, 0); g.addColorStop(0, '#2bbf7a'); g.addColorStop(1, GREEN); c.fillStyle = g; c.fill(); }
    if (f >= 0.999) { c.save(); c.fillStyle = 'rgba(61,220,132,0.18)'; c.beginPath(); c.arc(X + W * 0.955, y, u(0.03), 0, 7); c.fill(); IC.check(c, X + W * 0.955, y, u(0.045), GREEN); c.restore(); }
  });
  // approve button
  const bxc = X + W * 0.80, byc = Y + H * 0.765, br = u(0.105);
  const pulse = st.btnPulse ?? 0, hold = st.hold ?? 0, ok = st.approved ?? 0;
  c.save();
  if (pulse > 0 && ok < 1) { for (let k = 0; k < 2; k++) { const ph = ((st.t * 0.9 + k * 0.5) % 1); c.strokeStyle = `rgba(61,220,132,${(1 - ph) * 0.5 * pulse})`; c.lineWidth = u(0.006); c.beginPath(); c.arc(bxc, byc, br * (1 + ph * 0.6), 0, 7); c.stroke(); } }
  c.beginPath(); c.arc(bxc, byc, br, 0, 7); c.fillStyle = ok > 0 ? `rgba(61,220,132,${0.25 + 0.75 * ok})` : 'rgba(61,220,132,0.10)'; c.fill();
  c.strokeStyle = 'rgba(61,220,132,0.55)'; c.lineWidth = u(0.006); c.stroke();
  if (hold > 0) { c.strokeStyle = GREEN; c.lineWidth = u(0.014); c.lineCap = 'round'; c.shadowColor = GREEN; c.shadowBlur = u(0.03); c.beginPath(); c.arc(bxc, byc, br + u(0.022), -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * hold); c.stroke(); c.shadowBlur = 0; }
  IC.check(c, bxc, byc, br * 1.15 * (1 + 0.12 * ok * Math.max(0, 1 - (st.okAge ?? 9) * 2)), ok > 0.5 ? '#0b2a1a' : GREEN, 0.14);
  c.restore();
  // governor overlay on map
  const gv = st.gov;
  if (gv && gv.show > 0) {
    const gx = mx + mw * 0.5, gy = my + mh * 0.5, gs = u(0.26);
    c.save(); c.globalAlpha *= gv.show;
    c.fillStyle = 'rgba(6,12,20,0.55)'; rr(c, mx, my, mw, mh, u(0.02)); c.fill();
    const allOk = gv.checks.every(v => v >= 1);
    IC.shield(c, gx, gy, gs, allOk ? GREEN : 'rgba(255,255,255,0.85)', allOk ? `rgba(61,220,132,${0.18 + 0.2 * (gv.lock ?? 0)})` : 'rgba(255,255,255,0.05)');
    const icons = ['key', 'route', 'signal', 'plane'], off = u(0.25), pos = [[0, -1], [1, 0], [0, 1], [-1, 0]];
    gv.checks.forEach((v, i) => {
      const px = gx + pos[i][0] * off * 1.25, py = gy + pos[i][1] * off;
      c.save(); c.beginPath(); c.arc(px, py, u(0.055), 0, 7); c.fillStyle = v >= 1 ? 'rgba(61,220,132,0.95)' : 'rgba(20,30,44,0.95)'; c.fill(); c.strokeStyle = v > 0 ? GREEN : 'rgba(255,255,255,0.35)'; c.lineWidth = u(0.005); c.stroke();
      if (v > 0 && v < 1) { c.strokeStyle = GREEN; c.lineWidth = u(0.008); c.beginPath(); c.arc(px, py, u(0.068), -Math.PI / 2, -Math.PI / 2 + 7 * v); c.stroke(); }
      const col = v >= 1 ? '#0b2a1a' : 'rgba(255,255,255,0.85)';
      if (icons[i] === 'plane') IC.plane(c, px, py, u(0.06), col, 0); else IC[icons[i]](c, px, py, u(0.06), col);
      if (v >= 1) { c.beginPath(); c.arc(px + u(0.042), py - u(0.042), u(0.02), 0, 7); c.fillStyle = '#0b2a1a'; c.fill(); IC.check(c, px + u(0.042), py - u(0.042), u(0.03), GREEN); }
      c.restore();
    });
    IC.lock(c, gx, gy, u(0.12), allOk ? GREEN : 'rgba(255,255,255,0.8)', gv.lock ?? 0);
    c.restore();
    // send pulse
    if ((st.send ?? 0) > 0 && (st.send ?? 0) < 1) {
      const s0 = [gx, gy], s1 = [X + W * 0.955, Y + H * 0.115], cpx = (s0[0] + s1[0]) / 2, cpy = Math.min(s0[1], s1[1]) - u(0.25);
      const P = (t) => [(1 - t) * (1 - t) * s0[0] + 2 * (1 - t) * t * cpx + t * t * s1[0], (1 - t) * (1 - t) * s0[1] + 2 * (1 - t) * t * cpy + t * t * s1[1]];
      c.save(); c.strokeStyle = 'rgba(61,220,132,0.35)'; c.lineWidth = u(0.005); c.setLineDash([u(0.012), u(0.012)]); c.beginPath(); for (let k = 0; k <= 30; k++) { const p = P(k / 30); k ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]); } c.stroke(); c.setLineDash([]);
      for (let k = 0; k < 8; k++) { const tt = st.send - k * 0.025; if (tt < 0) break; const p = P(tt); c.fillStyle = `rgba(110,255,190,${1 - k / 8})`; c.beginPath(); c.arc(p[0], p[1], u(0.018) * (1 - k / 10), 0, 7); c.fill(); }
      c.restore();
    }
  }
  // cursor
  if (st.cursor && st.cursor.a > 0) {
    c.save(); c.globalAlpha *= st.cursor.a;
    if (st.cursor.press) { c.strokeStyle = 'rgba(255,255,255,0.5)'; c.lineWidth = u(0.004); c.beginPath(); c.arc(st.cursor.x * W + X, st.cursor.y * H + Y, u(0.03 + 0.03 * ((st.t * 2) % 1)), 0, 7); c.stroke(); }
    IC.cursor(c, st.cursor.x * W + X, st.cursor.y * H + Y, u(0.07), st.cursor.press);
    c.restore();
  }
  c.restore();
}

// ------------------------------------------------------------ overlays (3D)
function buildMapLayer(W) {
  const Gd = W.layout.grid, n = Gd.nx * Gd.nz;
  const data = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) { data[i * 4] = W.grid.cls[i]; data[i * 4 + 1] = W.grid.scan[i]; data[i * 4 + 2] = W.grid.jit[i]; data[i * 4 + 3] = 1; }
  const tex = new THREE.DataTexture(data, Gd.nx, Gd.nz, THREE.RGBAFormat, THREE.FloatType);
  tex.minFilter = tex.magFilter = THREE.NearestFilter; tex.needsUpdate = true;
  const w = Gd.nx * Gd.cell, h = Gd.nz * Gd.cell;
  const g = new THREE.PlaneGeometry(w, h); g.rotateX(-Math.PI / 2); g.translate(Gd.x0 + w / 2, 0.14, Gd.z0 + h / 2);
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, fog: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    uniforms: { uData: { value: tex }, uN: { value: new THREE.Vector2(Gd.nx, Gd.nz) }, uO: { value: new THREE.Vector2(Gd.x0, Gd.z0) }, uCell: { value: Gd.cell },
      uTime: { value: 0 }, uScan: { value: 0 }, uClass: { value: 0 }, uSweep: { value: -1e4 }, uGrid: { value: 1 } },
    vertexShader: `varying vec3 vW; void main(){ vec4 w = modelMatrix*vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `
      uniform sampler2D uData; uniform vec2 uN, uO; uniform float uCell, uTime, uScan, uClass, uSweep, uGrid; varying vec3 vW;
      void main(){
        vec2 rel = (vW.xz - uO) / uCell; vec2 ci = floor(rel);
        if (ci.x < 0.0 || ci.y < 0.0 || ci.x >= uN.x || ci.y >= uN.y) discard;
        vec4 d = texture2D(uData, (ci + 0.5) / uN);
        float cls = d.r, st = d.g, jit = d.b;
        vec2 f = fract(rel); float e = min(min(f.x, 1.0-f.x), min(f.y, 1.0-f.y)); float grid = (1.0 - smoothstep(0.03, 0.09, e)) * uGrid;
        vec4 o = vec4(0.0);
        float scanned = (st < 9000.0 && st <= uTime) ? 1.0 : 0.0;
        float fresh = scanned * exp(-max(uTime - st, 0.0) * 0.5);
        o = vec4(vec3(0.38,0.92,1.0), (0.10 + 0.32*grid + 0.45*fresh) * scanned * uScan);
        if (cls > 0.5) {
          float k = uSweep - vW.x - jit*16.0;
          float rev = smoothstep(0.0, 5.0, k);
          float front = exp(-pow(k/5.0, 2.0));
          vec3 cc = cls < 1.5 ? vec3(0.24,0.88,0.52) : cls < 2.5 ? vec3(1.0,0.32,0.30) : cls < 3.5 ? vec3(1.0,0.66,0.22) : cls < 4.5 ? vec3(0.25,0.66,1.0) : vec3(0.66,0.68,0.72);
          float a = cls < 1.5 ? (0.16 + 0.30*grid) : (cls < 4.5 ? 0.62 + 0.25*grid : 0.0);
          if (cls > 4.5) { float hatch = step(0.55, fract((vW.x + vW.z) * 0.32)); a = 0.10 + 0.28*hatch + 0.22*grid; }
          vec4 c2 = vec4(cc + vec3(0.6)*front, clamp(a*rev + front*0.55, 0.0, 1.0) * uClass);
          o.rgb = mix(o.rgb, c2.rgb, c2.a); o.a = c2.a + o.a*(1.0 - c2.a);
        }
        if (o.a < 0.003) discard;
        gl_FragColor = o;
      }`
  });
  const m = new THREE.Mesh(g, mat); m.renderOrder = 2; m.frustumCulled = false;
  return m;
}

function buildFootprint() {
  const G = new THREE.Group();
  const g = new THREE.PlaneGeometry(1, 1); g.rotateX(-Math.PI / 2);
  const mat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, fog: false, blending: THREE.AdditiveBlending, uniforms: { uT: { value: 0 }, uA: { value: 1 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: `uniform float uT, uA; varying vec2 vUv; void main(){ vec2 d = min(vUv, 1.0-vUv); float e = min(d.x, d.y); float edge = 1.0 - smoothstep(0.0, 0.02, e);
      float scan = exp(-pow((fract(vUv.y - uT*1.4) - 0.5)*14.0, 2.0)); vec3 c = vec3(0.4,0.95,1.0); gl_FragColor = vec4(c, (0.10 + 0.9*edge + 0.25*scan) * uA); }` });
  const quad = new THREE.Mesh(g, mat); quad.renderOrder = 3; G.add(quad);
  const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(8 * 3), 3));
  const lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x7ff0ff, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
  lines.frustumCulled = false; G.add(lines);
  G.userData = { quad, lines, mat };
  return G;
}

function buildTrail(n = 2400) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(n * 3), 3));
  const l = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }));
  l.frustumCulled = false; l.userData.n = n; return l;
}

function buildCandidates(L) {
  const G = new THREE.Group(), list = [];
  const wallTex = gradTexV();
  const icons = { water: 'drop', people: 'person', unknown: 'question' };
  L.candidates.forEach(cd => {
    const g = new THREE.Group(); const len = cd.x1 - cd.x0, w = cd.w, cx = (cd.x0 + cd.x1) / 2;
    g.position.set(cx, 0, cd.z);
    const col = new THREE.Color(0x5fe3ff);
    const fill = new THREE.Mesh(new THREE.PlaneGeometry(len, w).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.15, depthWrite: false, fog: false, toneMapped: false }));
    fill.material.polygonOffset = true; fill.material.polygonOffsetFactor = -4;
    fill.position.y = 0.22; fill.renderOrder = 3; g.add(fill);
    const edgeM = new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 1, depthWrite: false, fog: false, toneMapped: false });
    const wallM = new THREE.MeshBasicMaterial({ color: col, map: wallTex, transparent: true, opacity: 0.55, depthWrite: false, fog: false, toneMapped: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
    const walls = new THREE.Group(), edges = new THREE.Group();
    [[0, -w / 2, len, 0], [0, w / 2, len, 0], [-len / 2, 0, w, Math.PI / 2], [len / 2, 0, w, Math.PI / 2]].forEach(([x, z, l, r]) => {
      const e = new THREE.Mesh(new THREE.BoxGeometry(l + 0.5, 0.25, 0.5), edgeM); e.position.set(x, 0.3, z); e.rotation.y = r; edges.add(e);
      const wl = new THREE.Mesh(new THREE.PlaneGeometry(l, 1).translate(0, 0.5, 0), wallM); wl.position.set(x, 0.2, z); wl.rotation.y = r; walls.add(wl);
    });
    g.add(edges, walls);
    let icon = null;
    if (cd.verdict !== 'ok') {
      const c = canvas(256, 256), x = c.getContext('2d');
      x.fillStyle = 'rgba(255,70,70,0.92)'; x.beginPath(); x.arc(128, 128, 104, 0, 7); x.fill(); x.strokeStyle = 'rgba(255,255,255,0.9)'; x.lineWidth = 10; x.stroke();
      IC[icons[cd.verdict]](x, 128, 128, 150, '#fff');
      const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
      icon = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthWrite: false, depthTest: false, fog: false, toneMapped: false }));
      icon.position.set(0, 13, 0); icon.scale.set(11, 11, 1); icon.renderOrder = 10; g.add(icon);
    }
    G.add(g); list.push({ cd, g, fill, edgeM, wallM, walls, icon });
  });
  G.userData.list = list;
  return G;
}

function buildApproach(MI, EV) {
  const G = new THREE.Group();
  const pts = [], t0 = 196.0, t1 = EV.touchdown;
  for (let t = t0; t <= t1 + 0.001; t += 0.25) { const p = ppos(t); p.y = Math.max(p.y - CGH + 0.25, 0.25); pts.push(p); }
  const curve = new THREE.CatmullRomCurve3(pts);
  const tube = new THREE.TubeGeometry(curve, 900, 0.13, 6, false);
  const len = curve.getLength();
  const tubeM = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, fog: false, blending: THREE.AdditiveBlending,
    uniforms: { uDraw: { value: 0 }, uA: { value: 0 }, uT: { value: 0 }, uLen: { value: len }, uStart: { value: 0 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: `uniform float uDraw, uA, uT, uLen, uStart; varying vec2 vUv; void main(){ if (vUv.x > uDraw || vUv.x < uStart) discard; float tail = smoothstep(uStart, uStart + 0.03, vUv.x); float s = vUv.x*uLen; float dash = step(0.45, fract(s/7.0 - uT*0.9));
      float head = exp(-pow((uDraw - vUv.x)*uLen/6.0, 2.0)) * step(uDraw, 0.999); vec3 c = mix(vec3(0.35,1.0,0.72), vec3(1.0), head*0.7); gl_FragColor = vec4(c, (0.35 + 0.65*dash + head) * uA * tail); }` });
  const tubeMesh = new THREE.Mesh(tube, tubeM); tubeMesh.frustumCulled = false; tubeMesh.renderOrder = 4; G.add(tubeMesh);
  // gates along the final glide
  const gateM = new THREE.MeshBasicMaterial({ color: 0x5dffb0, transparent: true, opacity: 0.0, depthWrite: false, fog: false, toneMapped: false, blending: THREE.AdditiveBlending });
  const gates = [];
  const L = S.W.layout;
  for (let x = 180; x >= 45; x -= 22.5) {
    const y = Math.max(0.1 * (x - 35), 0) + 0.25; const gw = 4.4, gh = 3.0, th = 0.12;
    const g = new THREE.Group();
    [[0, gh / 2, gw, th], [0, -gh / 2, gw, th], [-gw / 2, 0, th, gh], [gw / 2, 0, th, gh]].forEach(([zz, yy, a, b]) => { const m = new THREE.Mesh(new THREE.BoxGeometry(th, b, a), gateM); m.position.set(0, yy, zz); g.add(m); });
    g.position.set(x, y + 0.2, -50); G.add(g); gates.push({ g, along: (curve.getUtoTmapping ? 0 : 0), x });
  }
  // touchdown target ring
  const ringM = new THREE.MeshBasicMaterial({ color: 0x5dffb0, transparent: true, opacity: 0, depthWrite: false, fog: false, toneMapped: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
  const ring = new THREE.Mesh(new THREE.RingGeometry(2.4, 2.9, 48).rotateX(-Math.PI / 2), ringM); ring.position.set(L ? 15 : 15, 0.25, -50); G.add(ring);
  const ring2 = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 32).rotateX(-Math.PI / 2), ringM); ring2.position.set(15, 0.25, -50); G.add(ring2);
  G.userData = { tubeM, gateM, gates, ringM, len };
  return G;
}

function buildLandRing() {
  const m = new THREE.MeshBasicMaterial({ color: 0x5dffb0, transparent: true, opacity: 0, depthWrite: false, fog: false, toneMapped: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
  const G = new THREE.Group(); const rings = [];
  for (let i = 0; i < 2; i++) { const r = new THREE.Mesh(new THREE.RingGeometry(0.92, 1.0, 64).rotateX(-Math.PI / 2), m.clone()); r.position.y = 0.2; G.add(r); rings.push(r); }
  G.userData.rings = rings; return G;
}

function buildDust() {
  const tex = glowTex('rgba(200,180,140,0.9)', 'rgba(200,180,140,0)');
  const G = new THREE.Group(), puffs = [];
  const R = rng(77);
  for (let i = 0; i < 46; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0 }));
    s.userData = { t0: (i < 26 ? 0 : 0.3 + R() * 2.2), ang: R() * Math.PI * 2, sp: 0.4 + R() * 1.4, up: 0.2 + R() * 0.8, side: R() < 0.5 ? -1 : 1, size: 0.25 + R() * 0.5, life: 1.0 + R() * 1.4 };
    G.add(s); puffs.push(s);
  }
  const bits = new THREE.InstancedMesh(new THREE.TetrahedronGeometry(0.02, 0), new THREE.MeshStandardMaterial({ color: 0x8a9a4a, roughness: 0.9 }), 60);
  bits.userData.seed = Array.from({ length: 60 }, () => [R(), R(), R(), R()]); bits.frustumCulled = false; G.add(bits);
  G.userData = { puffs, bits };
  return G;
}

// ------------------------------------------------------------ init
export async function init() {
  const [MI, W] = await Promise.all([fetch('mission.json').then(r => r.json()), fetch('world.json').then(r => r.json())]);
  S.MI = MI; S.W = W; S.EV = MI.events; initMission(MI);
  const H = makeHeight(W.height); S.H = H;
  const loader = new THREE.TextureLoader();
  const [groundTex, detailTex, grassTex, waterN] = await Promise.all([loader.loadAsync('ground.jpg'), loader.loadAsync('detail.png'), loader.loadAsync('grasslight-big.jpg'), loader.loadAsync('waternormals.jpg')]);
  grassTex.colorSpace = THREE.SRGBColorSpace; grassTex.wrapS = grassTex.wrapT = THREE.RepeatWrapping; grassTex.anisotropy = 8;
  groundTex.colorSpace = THREE.SRGBColorSpace; groundTex.anisotropy = 8; groundTex.generateMipmaps = true;
  detailTex.wrapS = detailTex.wrapT = THREE.RepeatWrapping; detailTex.anisotropy = 4;

  const gl = document.getElementById('gl');
  const Q = new URLSearchParams(location.search); S.Q = Q;
  const R = new THREE.WebGLRenderer({ canvas: gl, antialias: Q.get('aa') !== '0', preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  S.RS = parseFloat(Q.get('rs') || '1'); S.RW = Math.round(VW * S.RS); S.RH = Math.round(VH * S.RS);
  R.setPixelRatio(1); R.setSize(S.RW, S.RH, false);
  R.toneMapping = THREE.ACESFilmicToneMapping; R.toneMappingExposure = 1.0; R.outputColorSpace = THREE.SRGBColorSpace;
  R.shadowMap.enabled = true; R.shadowMap.type = Q.get('pcf') === '1' ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
  S.R = R; S.gl = gl;

  const scene = new THREE.Scene(); S.scene = scene;
  const sky = buildSky(); scene.add(sky); S.sky = sky;
  // environment from sky
  const envScene = new THREE.Scene(); const sky2 = buildSky(); envScene.add(sky2);
  const pm = new THREE.PMREMGenerator(R); scene.environment = pm.fromScene(envScene, 0.02).texture; scene.environmentIntensity = 0.55;
  scene.fog = new THREE.FogExp2(new THREE.Color(0.86, 0.66, 0.50).convertSRGBToLinear(), 0.0012);

  const sun = new THREE.DirectionalLight(new THREE.Color(1.0, 0.80, 0.60), 3.4);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
  scene.add(sun); scene.add(sun.target); S.sun = sun;
  const hemi = new THREE.HemisphereLight(new THREE.Color(0.62, 0.74, 1.0), new THREE.Color(0.42, 0.34, 0.22), Q.get('lamb') === '0' ? 0.55 : 1.15); scene.add(hemi);

  S.terrain = buildTerrainReal(W, groundTex, detailTex, grassTex); scene.add(S.terrain);
  { const hd = W.height, n = 61, pg = new THREE.PlaneGeometry(hd.size, hd.size, n - 1, n - 1); pg.rotateX(-Math.PI / 2); const pp = pg.attributes.position; for (let k = 0; k < pp.count; k++) pp.setY(k, H(pp.getX(k), pp.getZ(k))); pg.computeBoundingSphere(); S.terrainProxy = new THREE.Mesh(pg, new THREE.MeshBasicMaterial()); S.terrainProxy.updateMatrixWorld(true); }
  S.water = buildWaterReal(W.layout, waterN); scene.add(S.water);
  S.trees = buildTreesReal(W); scene.add(S.trees);
  S.props = buildProps(W, H); scene.add(S.props);
  S.people = buildPeople(W); scene.add(S.people);
  S.screenCanvas = canvas(1024, 640); S.screenTex = new THREE.CanvasTexture(S.screenCanvas); S.screenTex.colorSpace = THREE.SRGBColorSpace;
  S.station = buildStation(W, S.screenTex); scene.add(S.station);
  S.station.userData.pilot.traverse(o => o.layers.enable(1));
  S.whiteM = new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false, fog: false });
  const tk = W.layout.takeoff;
  S.grass = buildGrassReal([
    { x0: -64, x1: -16, z0: 61, z1: 82, n: 14000, h0: 0.12, h1: 0.34, skip: (x, z) => Math.abs(z - tk.z) < tk.w / 2 },
    { x0: -26, x1: 26, z0: -60, z1: -38, n: 14000, h0: 0.07, h1: 0.17, tint: 1.08 },
    { x0: -76, x1: -56, z0: 76, z1: 96, n: 7000, h0: 0.08, h1: 0.2 },
  ]);
  scene.add(S.grass);
  S.plane = buildPlaneReal(); scene.add(S.plane);

  S.mapLayer = buildMapLayer(W); scene.add(S.mapLayer);
  S.foot = buildFootprint(); scene.add(S.foot);
  S.trail = buildTrail(); scene.add(S.trail);
  S.marker = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex('rgba(255,255,255,1)', 'rgba(255,255,255,0)', true), transparent: true, depthTest: false, depthWrite: false, sizeAttenuation: false, fog: false, toneMapped: false }));
  S.marker.renderOrder = 20; scene.add(S.marker);
  S.cands = buildCandidates(W.layout); scene.add(S.cands);
  S.appr = buildApproach(MI, S.EV); scene.add(S.appr);
  S.landRing = buildLandRing(); scene.add(S.landRing);
  S.dust = buildDust(); scene.add(S.dust);
  // scan wall
  const wallG = new THREE.PlaneGeometry(W.layout.grid.nz * W.layout.grid.cell + 20, 36).translate(0, 18, 0); wallG.rotateY(Math.PI / 2);
  S.scanWall = new THREE.Mesh(wallG, new THREE.MeshBasicMaterial({ color: 0x7ff6ff, map: gradTexV(), transparent: true, opacity: 0, depthWrite: false, fog: false, toneMapped: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide }));
  S.scanWall.position.set(0, 0, W.layout.grid.z0 + W.layout.grid.nz * W.layout.grid.cell / 2); scene.add(S.scanWall);

  S.cam = new THREE.PerspectiveCamera(40, VW / VH, 0.3, 6000);
  S.out = document.getElementById('out'); S.ctx = S.out.getContext('2d');
  // grain + vignette
  S.grain = [0, 1, 2, 3].map(k => { const c = canvas(256, 256), x = c.getContext('2d'), im = x.createImageData(256, 256), r = rng(500 + k); for (let i = 0; i < im.data.length; i += 4) { const v = 128 + (r() - 0.5) * 200; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255; } x.putImageData(im, 0, 0); return c; });
  const vg = canvas(VW, VH), vx = vg.getContext('2d'); const g = vx.createRadialGradient(VW / 2, VH / 2, VH * 0.35, VW / 2, VH / 2, VW * 0.62);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0.5)'); vx.fillStyle = g; vx.fillRect(0, 0, VW, VH); S.vig = vg;
  S.tmp = canvas(240, 100); S.bgCache = {};
  S.raycaster = new THREE.Raycaster();

  buildShots();
  makeMapImage();
  await document.fonts.ready;
  return true;
}

// ------------------------------------------------------------ per-frame state
function setShadow(center, size) {
  const sun = S.sun; sun.target.position.copy(center); sun.position.copy(center).addScaledVector(SUN, 600);
  const c = sun.shadow.camera; c.left = -size; c.right = size; c.top = size; c.bottom = -size; c.near = 50; c.far = 1150; c.updateProjectionMatrix();
}
function shadowFocusFor(t, pad = 6) {
  const p = ppos(t), h = p.y; const horiz = V3(SUN.x, 0, SUN.z).normalize(); const disp = horiz.multiplyScalar(-h / Math.tan(Math.asin(SUN.y)));
  const c = V3(p.x, 0, p.z).addScaledVector(disp, 0.5); return [c, pad + disp.length() * 0.6];
}

function updatePlane(t, visible = true) {
  const s = ms(t), P = S.plane, u = P.userData;
  P.visible = visible;
  P.position.set(s.x, s.y + CGH, s.z);
  P.rotation.set(s.bank, -s.h, s.pitch, 'YZX');
  u.ailR.rotation.z = -s.ail; u.ailL.rotation.z = s.ail; u.ele.rotation.z = s.ele; u.rud.rotation.y = s.rud;
  const r = s.rpm; u.blades.rotation.x = s.ang + (r > 0.3 ? (Math.sin(t * 97.3) * 3.1) : 0);
  u.disc.material.opacity = sm(0.06, 0.32, r) * 0.9; u.bladeM.opacity = 1 - 0.82 * sm(0.12, 0.4, r);
  u.wheels.forEach((w, i) => { w.rotation.z = -s.dist / (i < 2 ? 0.05 : 0.045); });
  P.updateMatrixWorld(true);
  return s;
}

function resetOverlays() {
  const m = S.mapLayer.material.uniforms; m.uScan.value = 0; m.uClass.value = 0; m.uSweep.value = -1e4; S.mapLayer.visible = false;
  S.foot.visible = false; S.trail.visible = false; S.marker.visible = false; S.scanWall.material.opacity = 0;
  S.cands.visible = false; S.appr.visible = false; S.landRing.visible = false; S.dust.visible = false; S.grass.visible = false;
  S.cands.userData.list.forEach(c => { c.g.visible = true; });
}

function setCands(lt, st) { // st: {appear[], reject[], fade, win, wallH}
  S.cands.visible = true;
  S.cands.userData.list.forEach((c, i) => {
    const ap = st.appear[i] ?? 0, rj = st.reject[i] ?? 0, isWin = c.cd.verdict === 'ok';
    const fade = isWin ? 1 : 1 - (st.fade ?? 0);
    const red = new THREE.Color(1.0, 0.32, 0.3), cy = new THREE.Color(0.37, 0.89, 1.0), gr = new THREE.Color(0.36, 1.0, 0.62);
    let col = cy.clone();
    if (!isWin) col.lerp(red, rj); else col.lerp(gr, st.win ?? 0);
    const flash = isWin ? 0 : Math.exp(-Math.pow(((st.rjAge?.[i] ?? -9)) / 0.18, 2));
    const pulse = isWin ? (st.win ?? 0) * (0.75 + 0.25 * Math.sin(lt * 5)) : 0;
    c.edgeM.color.copy(col); c.wallM.color.copy(col); c.fill.material.color.copy(col);
    c.edgeM.opacity = ap * fade * (0.9 + flash) * (st.edgeA ?? 1); c.edgeM.visible = (st.edgeA ?? 1) > 0.01;
    c.wallM.opacity = ap * fade * (0.45 + 0.4 * flash + 0.35 * pulse) * (st.wallA ?? 1);
    c.fill.material.opacity = ap * fade * (0.12 + 0.18 * flash + 0.12 * pulse) * (st.fillA ?? 1);
    c.walls.scale.y = Math.max(0.01, (st.wallH ?? 7) * smr(ap) * (isWin ? 1 + 0.6 * (st.win ?? 0) : 1));
    c.g.visible = ap * fade > 0.002;
    if (c.icon) { const ia = sm(0, 0.25, (st.rjAge?.[i] ?? -9)) * fade; c.icon.material.opacity = ia; c.icon.visible = ia > 0.01; const pop = 1 + 0.35 * Math.exp(-Math.pow(((st.rjAge?.[i] ?? -9) - 0.12) / 0.12, 2)); c.icon.scale.set(11 * pop, 11 * pop, 1); }
  });
}

function setApproach(draw, alpha, t, gatesA = 1, ringA = 1, start = 0) {
  S.appr.visible = alpha > 0.001 || gatesA > 0.001;
  const u = S.appr.userData; u.tubeM.uniforms.uDraw.value = draw; u.tubeM.uniforms.uA.value = alpha; u.tubeM.uniforms.uT.value = t; u.tubeM.uniforms.uStart.value = start;
  u.gates.forEach((g) => { g.g.visible = draw > 0.58 + (180 - g.x) / 135 * 0.35; });
  u.gateM.opacity = 0.65 * gatesA;
  u.ringM.opacity = (0.55 + 0.35 * Math.sin(t * 4)) * ringA * sm(0.92, 1.0, draw);
}

function updateFootprint(t, alpha = 1) {
  const s = ms(t); const f = S.foot.userData; S.foot.visible = true;
  f.quad.position.set(s.x, 0.3, s.z); f.quad.rotation.y = -s.h; f.quad.scale.set(30, 1, 52); f.mat.uniforms.uT.value = t; f.mat.uniforms.uA.value = alpha;
  const cam = V3(0, -0.11, 0).applyMatrix4(S.plane.matrixWorld);
  const c = Math.cos(s.h), sn = Math.sin(s.h); const corners = [[15, 26], [15, -26], [-15, -26], [-15, 26]].map(([a, b]) => V3(s.x + a * c - b * sn, 0.3, s.z + a * sn + b * c));
  const pa = f.lines.geometry.attributes.position; corners.forEach((p, i) => { pa.setXYZ(i * 2, cam.x, cam.y, cam.z); pa.setXYZ(i * 2 + 1, p.x, p.y, p.z); }); pa.needsUpdate = true;
  f.lines.material.opacity = 0.45 * alpha;
}

function updateTrail(t0, t1, alt = null) {
  const L = S.trail, n = L.userData.n, pa = L.geometry.attributes.position, ca = L.geometry.attributes.color; let k = 0;
  const dt = Math.max((t1 - t0) / (n - 1), 1 / 60);
  for (let t = t0; t <= t1 && k < n; t += dt, k++) { const s = ms(t); pa.setXYZ(k, s.x, alt ?? s.y, s.z); const a = 0.25 + 0.75 * Math.pow((t - t0) / Math.max(t1 - t0, 1e-3), 1.5); ca.setXYZ(k, 0.45 * a, 0.95 * a, 1.0 * a); }
  L.geometry.setDrawRange(0, k); pa.needsUpdate = true; ca.needsUpdate = true; L.visible = k > 1;
}

function updateDust(t) {
  const td = S.EV.touchdown, D = S.dust.userData; S.dust.visible = t > td - 0.05 && t < td + 6;
  if (!S.dust.visible) return;
  D.puffs.forEach((p, i) => {
    const u = p.userData, age = t - td - u.t0;
    if (age < 0 || age > u.life) { p.visible = false; return; }
    p.visible = true;
    const sp = ms(td + u.t0); const back = V3(-Math.cos(sp.h), 0, -Math.sin(sp.h));
    const wz = (i % 2 ? 0.135 : -0.135);
    const base = V3(sp.x - 0.04 * Math.cos(sp.h) - wz * Math.sin(sp.h), 0.05, sp.z - 0.04 * Math.sin(sp.h) + wz * Math.cos(sp.h));
    const k = 1 - Math.exp(-age * 2.0);
    base.addScaledVector(back, u.sp * k * 0.9).add(V3(Math.cos(u.ang) * 0.35 * k, u.up * k * 0.5, Math.sin(u.ang) * 0.35 * k));
    p.position.copy(base);
    const s = u.size * (0.6 + 2.2 * k) * (i < 26 ? 1 : 0.6); p.scale.set(s, s, 1);
    p.material.opacity = (i < 26 ? 0.55 : 0.28) * (1 - age / u.life) * sm(0, 0.08, age);
  });
  const bits = D.bits, m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), sc = V3(1, 1, 1);
  const s0 = ms(td);
  bits.userData.seed.forEach(([a, b, c, d], i) => {
    const age = t - td - a * 0.15; let p;
    if (age < 0 || age > 1.4) { p = V3(0, -50, 0); } else {
      const vx = -Math.cos(s0.h) * (1 + 2 * b) + (c - 0.5) * 1.5, vz = -Math.sin(s0.h) * (1 + 2 * b) + (d - 0.5) * 1.5, vy = 1.0 + 2.2 * c;
      p = V3(s0.x + vx * age, Math.max(0.02, 0.05 + vy * age - 4.9 * age * age), s0.z + vz * age);
    }
    e.set(age * 9 * a, age * 7 * b, age * 5); q.setFromEuler(e); m4.compose(p, q, sc); bits.setMatrixAt(i, m4);
  });
  bits.instanceMatrix.needsUpdate = true;
}

function updateLandRing(t) {
  const ts = S.EV.stop - 0.25, R = S.landRing; const s = ms(t);
  R.visible = t > ts && t < ts + 4; if (!R.visible) return;
  R.position.set(s.x, 0, s.z);
  R.userData.rings.forEach((r, i) => { const age = t - ts - i * 0.45; if (age < 0) { r.visible = false; return; } r.visible = true; const k = 1 - Math.exp(-age * 1.6); r.scale.setScalar(0.6 + 7.5 * k); r.material.opacity = 0.9 * (1 - sm(0.2, 2.2, age)); });
}

function setMarker(t, scale = 0.035, a = 1) { const p = ppos(t); S.marker.visible = a > 0; S.marker.position.copy(p); S.marker.scale.set(scale, scale, 1); S.marker.material.opacity = a; }

// ------------------------------------------------------------ map image for the laptop UI
function makeMapImage() {
  resetOverlays();
  S.mapLayer.visible = true; const m = S.mapLayer.material.uniforms; m.uClass.value = 0.8; m.uSweep.value = 1e4; m.uTime.value = 1e4; m.uGrid.value = 0.5;
  setCands(0, { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 0.5 });
  setApproach(1, 0.0, 0);
  updatePlane(-6, true); S.plane.visible = false; S.grass.visible = false; S.marker.visible = false;
  const cam = new THREE.OrthographicCamera(-220, 220, 135, -135, 1, 1200); cam.position.set(20, 600, -25); cam.up.set(0, 0, -1); cam.lookAt(20, 0, -25);
  setShadow(V3(20, 0, -25), 260); S.scene.fog.density = 0.0;
  const w = Math.round(S.RH * 440 / 270);
  S.R.setViewport(0, 0, w, S.RH); S.R.setScissor(0, 0, w, S.RH); S.R.setScissorTest(true);
  S.R.toneMappingExposure = 1.05; S.R.render(S.scene, cam);
  S.R.setScissorTest(false); S.R.setViewport(0, 0, S.RW, S.RH);
  const img = canvas(w, S.RH); img.getContext('2d').drawImage(S.gl, 0, S.gl.height - S.RH, w, S.RH, 0, 0, w, S.RH);
  S.mapImg = img;
  resetOverlays();
}

// ------------------------------------------------------------ shots
const EVT = [];   // audio/UI events (film time)
function buildShots() {
  const EV = S.EV;
  const shots = [];
  const add = (id, dur, fn, extra = {}) => shots.push(Object.assign({ id, dur, fn }, extra));

  add('establish', 8.0, (lt) => {
    const e = smr(lt / 8.0);
    return { mt: -6, pos: lerpV(V3(-18, 46, 205), V3(-46, 26, 146), e), look: lerpV(V3(-70, 0, 38), V3(-61, 1, 62), e), fov: 42, near: 0.5,
      shadow: [V3(-50, 0, 85), 150], fade: 1 - sm(0, 1.8, lt), title: sm(1.4, 2.6, lt) * (1 - sm(5.8, 7.2, lt)) };
  });
  add('spool', 4.0, (lt) => {
    const e = smr(lt / 4.0);
    return { mt: -4 + lt, pos: lerpV(V3(-53.62, 0.23, 69.12), V3(-53.74, 0.27, 69.02), e), look: V3(-54.95, 0.17, 70.05), fov: 34, near: 0.02, grass: true, shadow: [V3(-55, 0, 70), 4] };
  });
  add('takeoff', 6.0, (lt) => {
    const mt = lt; const p = ppos(mt + 0.12);
    const [c, sz] = shadowFocusFor(mt, 10);
    return { mt, pos: V3(-25, 0.45, 75.2).add(shake(lt, 0.012, 1.2)), look: p.add(V3(0, 0.12, 0)), fov: 24, near: 0.05, grass: true, shadow: [c, Math.max(sz, 14)] };
  });
  add('chase', 6.0, (lt) => {
    const mt = 6 + lt, a = ms(mt - 0.12), hf = hframe(a.h);
    const pos = V3(a.x, a.y + CGH, a.z).addScaledVector(hf.fwd, -2.5).addScaledVector(hf.up, 0.62).addScaledVector(hf.right, -0.95).add(shake(lt, 0.02, 1.5));
    const look = ppos(mt).addScaledVector(hf.fwd, 3.2).add(V3(0, -0.25, 0));
    const [c, sz] = shadowFocusFor(mt, 8);
    return { mt, pos, look, fov: 34, near: 0.05, shadow: [c, sz] };
  });
  add('climbout', 7.0, (lt) => {
    const mt = 12 + lt * 1.25, e = smr(lt / 7); const p = ppos(mt - 0.12);
    return { mt, pos: V3(70, 30, 112).add(V3(8 * e, 1 * e, -4 * e)).add(shake(lt, 0.03, 0.8)), look: p, fov: lerp(6, 4.5, e), near: 0.5, shadow: [V3(100, 0, 85), 70] };
  });
  add('survey', 7.0, (lt) => {
    const e = smr(lt / 7.0), mt = 38 + (159.5 - 38) * lt / 7.0, a = -0.10 + 0.16 * e;
    return { mt, pos: V3(-5, 430, -45), look: V3(-5, 0, -45), up: V3(Math.sin(a), 0, -Math.cos(a)), fov: 41 - 3 * e, near: 5, fog: 0.00025, exposure: 1.2,
      shadow: [V3(0, 0, -40), 300], survey: true };
  });
  add('belly', 6.0, (lt) => ({ mt: 72 + lt, belly: true, fov: 34, near: 0.05, fog: 0.0006, shadow: [V3(ms(72 + lt).x, 0, -70), 45], hidePlane: true }));
  add('formation', 6.5, (lt) => {
    const mt = 95.6 + lt, a = ms(mt - 0.06), hf = hframe(a.h);
    const pos = V3(a.x, a.y + CGH, a.z).addScaledVector(hf.fwd, -0.9).addScaledVector(hf.up, 0.95).addScaledVector(hf.right, -1.55).add(shake(lt, 0.01, 1.0));
    const look = ppos(mt).addScaledVector(hf.fwd, 0.3).add(V3(0, -0.15, 0));
    return { mt, pos, look, fov: 42, near: 0.03, roll: -0.06, shadow: [ppos(mt), 2.0], scanGround: true };
  });
  add('classify', 9.0, (lt) => {
    const e = smr(lt / 9.0), az = THREE.MathUtils.degToRad(lerp(58, 40, e)), mt = 166 + lt;
    const pos = V3(10 + 270 * Math.cos(az), 180, -25 + 270 * Math.sin(az));
    return { mt, pos, look: V3(-5, 0, -32), fov: 40, near: 2, exposure: 0.8, white: 0.85 * (1 - sm(0, 0.6, lt)), shadow: [V3(0, 0, -30), 280],
      map: { scan: 1 - sm(0, 1.5, lt), cls: 1, sweep: lerp(-215, 270, sm(0.8, 6.8, lt)), wall: sm(0.6, 1.0, lt) * (1 - sm(6.2, 7.0, lt)), time: 1e4 }, marker: 0.03 };
  });
  add('candidates', 8.5, (lt) => {
    const e = smr(lt / 8.5), az = THREE.MathUtils.degToRad(lerp(36, 12, e)), R = lerp(205, 180, e), Hh = lerp(122, 104, e), mt = 175 + lt;
    const pos = V3(15 + R * Math.cos(az), Hh, -20 + R * Math.sin(az));
    const rjT = [null, 4.0, 3.3, 2.6];
    const cand = { appear: [0, 1, 2, 3].map(i => sm(0.3 + 0.25 * i, 1.3 + 0.25 * i, lt)), reject: rjT.map(t => t ? sm(t, t + 0.25, lt) : 0), rjAge: rjT.map(t => t ? lt - t : -9), fade: sm(4.9, 6.0, lt), win: sm(4.6, 5.4, lt), wallH: 7 };
    return { mt, pos, look: V3(8, 0, -28), fov: 40, near: 2, exposure: 0.95, shadow: [V3(10, 0, -25), 240],
      map: { scan: 0.2 * (1 - sm(0, 2, lt)), cls: 1 - 0.45 * sm(4, 7, lt), sweep: 1e4, time: 1e4 }, cand, appr: { draw: sm(5.2, 7.8, lt), a: sm(5.0, 5.4, lt) }, marker: 0.03 };
  }, { events: [[2.6, 'reject'], [3.3, 'reject'], [4.0, 'reject'], [4.6, 'win'], [5.2, 'path']] });
  add('pilot', 6.5, (lt) => {
    const e = smr(lt / 6.5), mt = 186 + lt;
    return { mt, pos: lerpV(V3(-67.95, 1.62, 85.78), V3(-67.45, 1.45, 85.55), e), look: lerpV(V3(-58.0, 2.4, 82.6), V3(-64.95, 1.02, 85.12), smr(sm(1.0, 5.2, lt))), fov: lerp(34, 28, e), near: 0.05, grass: true,
      shadow: [V3(-65.2, 0, 85.4), 6], screen: { mode: 'request', lt }, marker: 0.018, dof: 1.7 };
  });
  add('approve', 8.0, (lt) => ({ mt: 192.5 + lt, ui: true, lt }), { events: [[2.6, 'press'], [4.2, 'approved'], [4.9, 'tick'], [5.3, 'tick'], [5.7, 'tick'], [6.1, 'tick'], [6.4, 'lock'], [6.6, 'send']] });
  add('spiral', 7.0, (lt) => {
    const mt = 199 + lt * 2.0, e = smr(lt / 7);
    return { mt, pos: V3(-32, 8.5, -63).add(V3(4 * e, -1.2 * e, 0)).add(shake(lt, 0.02, 0.6)), look: lerpV(V3(170, 16, -28), V3(150, 10, -36), e), fov: 27, near: 0.5, shadow: [V3(30, 0, -50), 90], fade: 1 - sm(0, 0.5, lt), marker: 0.02,
      cand: { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 2.5, wallA: 0.5 }, appr: { draw: 1, a: 1, cut: true } };
  });
  add('final', 7.0, (lt) => {
    const mt = 215.5 + lt, a = ms(mt - 0.15), hf = hframe(a.h);
    const pos = V3(a.x, a.y + CGH, a.z).addScaledVector(hf.fwd, -3.0).addScaledVector(hf.up, 0.95).addScaledVector(hf.right, 0.65).add(shake(lt, 0.02, 1.2));
    const look = ppos(mt).addScaledVector(hf.fwd, 22).add(V3(0, -2.6, 0));
    const [c, sz] = shadowFocusFor(mt, 10);
    return { mt, pos, look, fov: 40, near: 0.03, shadow: [c, sz], cand: { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 6 }, appr: { draw: 1, a: 1, cut: true } };
  });
  add('headon', 5.5, (lt) => {
    const mt = 222.5 + lt; const p = ppos(mt);
    return { mt, pos: V3(5, 0.9, -50.7).add(shake(lt, 0.006, 0.9)), look: p, fov: 2.9, near: 1.0, grass: true, shadow: [V3(35, 0, -50), 45],
      cand: { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 0.01, wallA: 0, edgeA: 0, fillA: 0 }, appr: { draw: 1, a: 0, gates: 0, ring: 0 } };
  });
  // slow-motion ramp for touchdown
  const td = EV.touchdown, rate = (lt) => 1 - 0.66 * Math.exp(-Math.pow((lt - 4.2) / 1.35, 2));
  const tab = [0]; for (let i = 1; i <= 750; i++) tab.push(tab[i - 1] + rate((i - 0.5) / 100) / 100);
  const off = td - tab[420];
  const mtTD = (lt) => off + tab[Math.min(750, Math.max(0, Math.round(lt * 100)))];
  add('touchdown', 7.5, (lt) => {
    const mt = mtTD(lt); const p = ppos(mt + 0.05);
    return { mt, pos: V3(14.0, 0.30, -45.0).add(shake(lt, 0.006, 0.9)), look: p.add(V3(-0.35, 0.05, 0)), fov: 23, near: 0.03, grass: true, shadow: [V3(ms(mt).x, 0, -49), 9], dust: true,
      cand: { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 0.01, wallA: 0, edgeA: 0, fillA: 0 }, appr: { draw: 1, a: 0, gates: 0, ring: 1 - sm(4.0, 5.0, lt) } };
  }, { events: [[4.2, 'touchdown']] });
  add('rollout', 6.0, (lt) => {
    const mt = 232.6 + lt, e = smr(lt / 6);
    return { mt, pos: lerpV(V3(-9.9, 0.27, -51.3), V3(-9.6, 0.30, -51.15), e), look: V3(-4.7, 0.24, -50.0), fov: 22, near: 0.03, grass: true, dust: true, shadow: [V3(-5, 0, -50), 6], landRing: false,
      cand: { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 0.01, wallA: 0, edgeA: 0, fillA: 0 } };
  }, { events: [[3.5 - 0.25, 'stop']] });
  add('pullback', 11.0, (lt) => {
    const mt = 238.6 + lt * 0.3, e = smr(sm(0, 6.6, lt));
    const pos = lerpV(V3(-9.5, 1.1, -47.6), V3(70, 100, 26), e); pos.y += Math.sin(e * Math.PI) * 6;
    return { mt, pos, look: lerpV(V3(-4.8, 0.3, -50), V3(-18, 0, -46), e), fov: lerp(40, 46, e), near: 0.05, shadow: [V3(-5, 0, -50), lerp(8, 160, e)],
      map: { scan: 0, cls: 0.35 * e, sweep: 1e4, time: 1e4 }, cand: { appear: [1, 0, 0, 0], reject: [0, 0, 0, 0], fade: 1, win: 1, wallH: 5 * e, wallA: 0.6 * e, edgeA: sm(0.1, 0.5, e) },
      fade: sm(5.2, 6.6, lt), title: sm(6.7, 7.8, lt) * (1 - sm(10.2, 10.95, lt)), endTitle: true };
  });

  let t = 0; shots.forEach(s => { s.start = t; t += s.dur; (s.events || []).forEach(([dt, name]) => EVT.push([+(s.start + dt).toFixed(3), name])); });
  S.shots = shots; S.duration = t;
  // mission-time audio events
  const toFilm = (mtTarget, shotId) => { const s = shots.find(x => x.id === shotId); for (let lt = 0; lt <= s.dur; lt += 1 / 120) { if (s.fn(lt).mt >= mtTarget) return s.start + lt; } return null; };
  EVT.push([+toFilm(0.0, 'takeoff').toFixed(3), 'roll']);
}

// ------------------------------------------------------------ frame
function setCamera(C, s) {
  const cam = S.cam;
  cam.fov = C.fov ?? 40; cam.near = C.near ?? 0.3; cam.far = 6000; cam.aspect = VW / VH;
  if (C.belly) {
    const pos = V3(0, -0.115, 0).applyMatrix4(S.plane.matrixWorld); cam.position.copy(pos);
    const basis = new THREE.Matrix4().makeBasis(V3(0, 0, 1), V3(1, 0, 0), V3(0, 1, 0));
    const ql = new THREE.Quaternion().setFromRotationMatrix(basis);
    cam.quaternion.copy(S.plane.quaternion).multiply(ql);
  } else {
    cam.position.copy(C.pos); cam.up.copy(C.up ?? V3(0, 1, 0)); cam.lookAt(C.look);
    if (C.roll) cam.rotateZ(C.roll);
  }
  cam.updateProjectionMatrix(); cam.updateMatrixWorld(true);
}

function sunVisibility(cam) {
  const fwd = V3(0, 0, -1).applyQuaternion(cam.quaternion); if (fwd.dot(SUN) < 0.2) return null;
  const p = cam.position.clone().addScaledVector(SUN, 2500).project(cam);
  const sx = (p.x + 1) / 2 * VW, sy = (1 - p.y) / 2 * VH;
  if (sx < -500 || sx > VW + 500 || sy < -400 || sy > VH + 400) return null;
  const targets = [S.terrainProxy, S.trees, S.plane, S.station];
  let vis = 0; const offs = [[0, 0], [0.004, 0], [-0.004, 0], [0, 0.004], [0, -0.004]];
  offs.forEach(([a, b]) => { const d = SUN.clone().add(V3(a, b, a * 0.5)).normalize(); S.raycaster.set(cam.position, d); S.raycaster.far = 3000; const hit = S.raycaster.intersectObjects(targets, true); if (!hit.length) vis += 1; });
  const inFrame = (sx > 0 && sx < VW && sy > 0 && sy < VH) ? 1 : sm(500, 0, Math.max(-sx, sx - VW, -sy, sy - VH));
  return { x: sx, y: sy, v: (vis / offs.length) * inFrame };
}

function drawFlare(c, f) {
  if (!f || f.v <= 0.01) return;
  const x = f.x, y = f.y + BAR, v = f.v; c.save(); c.globalCompositeOperation = 'lighter';
  let g = c.createRadialGradient(x, y, 0, x, y, 420); g.addColorStop(0, `rgba(255,214,160,${0.42 * v})`); g.addColorStop(0.25, `rgba(255,170,100,${0.16 * v})`); g.addColorStop(1, 'rgba(255,140,80,0)');
  c.fillStyle = g; c.fillRect(x - 420, y - 420, 840, 840);
  g = c.createRadialGradient(x, y, 0, x, y, 70); g.addColorStop(0, `rgba(255,250,235,${0.85 * v})`); g.addColorStop(1, 'rgba(255,240,220,0)'); c.fillStyle = g; c.fillRect(x - 70, y - 70, 140, 140);
  c.save(); c.translate(x, y); c.scale(1, 0.012); g = c.createRadialGradient(0, 0, 0, 0, 0, 900); g.addColorStop(0, `rgba(255,200,150,${0.5 * v})`); g.addColorStop(1, 'rgba(255,180,120,0)'); c.fillStyle = g; c.fillRect(-900, -900, 1800, 1800); c.restore();
  const cx = VW / 2, cy = OH / 2; [[-0.35, 26, '255,190,120', 0.10], [0.25, 14, '140,200,255', 0.12], [0.55, 44, '255,160,90', 0.06], [0.9, 18, '180,255,200', 0.08], [1.25, 70, '255,170,110', 0.05]].forEach(([k, r, col, a]) => {
    const gx = x + (cx - x) * (1 + k) * 1.0, gy = y + (cy - y) * (1 + k); const gg = c.createRadialGradient(gx, gy, 0, gx, gy, r); gg.addColorStop(0, `rgba(${col},${a * v})`); gg.addColorStop(0.8, `rgba(${col},${a * v * 0.6})`); gg.addColorStop(1, `rgba(${col},0)`); c.fillStyle = gg; c.beginPath(); c.arc(gx, gy, r, 0, 7); c.fill();
  });
  c.restore();
}

function drawHUD(c, lt, s) {
  const x0 = 0, y0 = BAR, w = VW, h = VH; c.save();
  c.strokeStyle = 'rgba(255,255,255,0.85)'; c.lineWidth = 3; const m = 46, L = 70;
  [[x0 + m, y0 + m, 1, 1], [x0 + w - m, y0 + m, -1, 1], [x0 + m, y0 + h - m, 1, -1], [x0 + w - m, y0 + h - m, -1, -1]].forEach(([x, y, sx, sy]) => { c.beginPath(); c.moveTo(x, y + sy * L); c.lineTo(x, y); c.lineTo(x + sx * L, y); c.stroke(); });
  c.lineWidth = 2; c.strokeStyle = 'rgba(255,255,255,0.7)'; const cx = w / 2, cy = y0 + h / 2;
  c.beginPath(); c.moveTo(cx - 34, cy); c.lineTo(cx - 12, cy); c.moveTo(cx + 12, cy); c.lineTo(cx + 34, cy); c.moveTo(cx, cy - 34); c.lineTo(cx, cy - 12); c.moveTo(cx, cy + 12); c.lineTo(cx, cy + 34); c.stroke();
  // attitude tick
  c.save(); c.translate(cx, cy); c.rotate(-s.bank); c.strokeStyle = 'rgba(95,227,255,0.8)'; c.beginPath(); c.moveTo(-140, 0); c.lineTo(-70, 0); c.moveTo(70, 0); c.lineTo(140, 0); c.stroke(); c.restore();
  // rec dot
  if (Math.floor(lt * 1.6) % 2 === 0) { c.fillStyle = 'rgba(255,60,60,0.95)'; c.beginPath(); c.arc(x0 + m + 26, y0 + m + 30, 9, 0, 7); c.fill(); }
  // frame counter bars (abstract)
  for (let i = 0; i < 18; i++) { const on = (i / 18) < ((lt * 0.9) % 1); c.fillStyle = on ? 'rgba(95,227,255,0.85)' : 'rgba(255,255,255,0.2)'; c.fillRect(w - m - 18 * 12 + i * 12, y0 + m + 22, 8, 14); }
  c.restore();
}

let lastShot = null;
export function frame(ft) {
  const T0 = performance.now();
  const shots = S.shots; let sh = shots[shots.length - 1];
  for (const s of shots) { if (ft < s.start + s.dur) { sh = s; break; } }
  const lt = Math.max(0, ft - sh.start);
  const C = sh.fn(lt);
  const c = S.ctx;
  c.globalAlpha = 1; c.globalCompositeOperation = 'source-over';
  c.fillStyle = '#000'; c.fillRect(0, 0, OW, OH);
  resetOverlays();
  const s = updatePlane(C.mt, !C.hidePlane);
  // generic scene state
  S.scene.fog.density = C.fog ?? 0.0012; S.R.toneMappingExposure = C.exposure ?? 1.0;
  S.sky.material.uniforms.uTime.value = ft; S.water.userData.nt.offset.set(ft * 0.012, ft * 0.007);
  S.grass.visible = !!C.grass;
  if (C.shadow) setShadow(C.shadow[0], C.shadow[1]);
  // pilot head + windsock
  const sock = S.props.userData.sock; sock.rotation.y = 0.12 * Math.sin(ft * 1.7); sock.rotation.z = -0.12 + 0.05 * Math.sin(ft * 2.3);
  S.people.children.forEach((p, i) => { p.rotation.z = 0.02 * Math.sin(ft * 0.9 + i); });
  // overlays
  if (C.survey) {
    S.mapLayer.visible = true; const u = S.mapLayer.material.uniforms; u.uScan.value = 1; u.uClass.value = 0; u.uTime.value = C.mt; u.uGrid.value = 1;
    updateFootprint(C.mt, 1); updateTrail(S.EV.survey_start - 6, C.mt); setMarker(C.mt, 0.03, 1);
  }
  if (C.scanGround) { S.mapLayer.visible = true; const u = S.mapLayer.material.uniforms; u.uScan.value = 0.8; u.uClass.value = 0; u.uTime.value = C.mt; u.uGrid.value = 1; }
  if (C.map) { S.mapLayer.visible = true; const u = S.mapLayer.material.uniforms; u.uScan.value = C.map.scan; u.uClass.value = C.map.cls; u.uSweep.value = C.map.sweep; u.uTime.value = C.map.time; u.uGrid.value = 1;
    if (C.map.wall) { S.scanWall.position.x = C.map.sweep; S.scanWall.material.opacity = 0.55 * C.map.wall; } }
  if (C.cand) setCands(lt, C.cand);
  if (C.appr) setApproach(C.appr.draw, C.appr.a, ft, C.appr.gates ?? C.appr.a, C.appr.ring ?? C.appr.a, C.appr.cut ? clamp((C.mt + 0.4 - 196) / (S.EV.touchdown - 196), 0, 1) : 0);
  if (C.marker) setMarker(C.mt, C.marker, 1);
  if (C.dust) updateDust(C.mt);
  if (C.landRing) updateLandRing(C.mt);
  // laptop screen texture
  if (C.screen) {
    const sc = S.screenCanvas, x = sc.getContext('2d'); x.fillStyle = '#05080d'; x.fillRect(0, 0, sc.width, sc.height);
    const p = ms(C.mt);
    drawUI(x, 0, 0, sc.width, sc.height, { t: ft, bars: [1, 1, 1], btnPulse: 1, thinking: 0.4, planeXZ: [p.x, p.z], planeH: p.h });
    S.screenTex.needsUpdate = true;
  }

  if (C.ui) { drawApproveShot(c, lt, C, sh); }
  else {
    setCamera(C, s);
    const tr0 = performance.now(); S.R.render(S.scene, S.cam); S.R.getContext().finish(); S.prof = { render: performance.now() - tr0 };
    const td0 = performance.now(); c.imageSmoothingQuality = 'high'; c.drawImage(S.gl, 0, 0, S.RW, S.RH, 0, BAR, VW, VH); S.prof.draw = performance.now() - td0;
    if (C.belly) {
      // classification reveal band following a scan line
      const u = S.mapLayer.material.uniforms; S.mapLayer.visible = true; u.uScan.value = 0; u.uClass.value = 1; u.uSweep.value = 1e4; u.uTime.value = 1e4; u.uGrid.value = 1;
      S.R.render(S.scene, S.cam);
      const per = 1.5, ph = (lt % per) / per, ys = ph * (VH + 260) - 130;
      for (let k = 0; k < 10; k++) { const y0 = ys - (k + 1) * 30, a = 0.85 * (1 - k / 10); c.save(); c.beginPath(); c.rect(0, BAR + Math.max(0, y0), VW, Math.max(0, Math.min(VH, y0 + 30) - Math.max(0, y0))); c.clip(); c.globalAlpha = a; c.drawImage(S.gl, 0, 0, S.RW, S.RH, 0, BAR, VW, VH); c.restore(); }
      c.save(); const lg = c.createLinearGradient(0, BAR + ys - 6, 0, BAR + ys + 6); lg.addColorStop(0, 'rgba(95,227,255,0)'); lg.addColorStop(0.5, 'rgba(160,240,255,0.9)'); lg.addColorStop(1, 'rgba(95,227,255,0)');
      c.fillStyle = lg; if (ys > 0 && ys < VH) c.fillRect(0, BAR + ys - 6, VW, 12); c.restore();
      drawHUD(c, lt, s);
    }
    if (C.dof) pilotDOF(c, C.dof);
    const tf0 = performance.now(); drawFlare(c, sunVisibility(S.cam)); S.prof.flare = performance.now() - tf0;
  }
  // grade: vignette + grain
  const tg0 = performance.now(); c.save(); const GR = S.Q.get('grain') === '1'; if (GR) c.drawImage(S.vig, 0, BAR);
  c.globalCompositeOperation = 'overlay'; c.globalAlpha = GR ? 0.09 : 0.0; const gr = S.grain[Math.floor(ft * 30) % 4]; const pat = c.createPattern(gr, 'repeat');
  c.translate((Math.floor(ft * 30) * 37) % 256, (Math.floor(ft * 30) * 91) % 256); c.fillStyle = pat; c.fillRect(-256, BAR - 256, VW + 512, VH + 512); c.restore();
  if (S.prof) S.prof.grade = performance.now() - tg0;
  // fades
  if (C.white) { c.fillStyle = `rgba(235,250,255,${C.white})`; c.fillRect(0, BAR, VW, VH); }
  if (C.fade) { c.fillStyle = `rgba(0,0,0,${C.fade})`; c.fillRect(0, BAR, VW, VH); }
  if (C.title) drawTitle(c, C.title, !!C.endTitle);
  // letterbox (clean)
  c.fillStyle = '#000'; c.fillRect(0, 0, OW, BAR); c.fillRect(0, BAR + VH, OW, BAR);
  S.lastMs = performance.now() - T0;
  const cue = { ft, shot: sh.id, mt: C.mt, thr: s.thr, rpm: s.rpm, v: s.v, y: s.y, ms: S.lastMs, prof: S.prof, dist: C.belly ? 0.1 : (C.ui ? 300 : S.cam.position.distanceTo(S.plane.position)), belly: !!C.belly, ui: !!C.ui };
  lastShot = sh.id;
  return cue;
}

function pilotDOF(c, amt) {
  // foreground (pilot) shallow depth of field: white silhouette pass -> soft mask -> blurred frame composited through it
  const sc = S.scene, cam = S.cam, R = S.R, fog = sc.fog, bg = sc.background;
  sc.fog = null; sc.background = null; sc.overrideMaterial = S.whiteM; cam.layers.set(1); R.shadowMap.autoUpdate = false;
  R.setClearColor(0x000000, 1); R.render(sc, cam);
  sc.fog = fog; sc.background = bg; sc.overrideMaterial = null; cam.layers.set(0); R.shadowMap.autoUpdate = true;
  const W2 = 960, H2 = 402;
  if (!S.dofC) S.dofC = { mk: canvas(W2, H2), bl: canvas(W2, H2) };
  const mk = S.dofC.mk, mx = mk.getContext('2d', { willReadFrequently: true }), bl = S.dofC.bl, bx = bl.getContext('2d');
  mx.globalCompositeOperation = 'source-over'; mx.filter = `blur(${(2.5 * amt).toFixed(2)}px)`; mx.clearRect(0, 0, W2, H2); mx.drawImage(S.gl, 0, 0, S.RW, S.RH, 0, 0, W2, H2); mx.filter = 'none';
  const id = mx.getImageData(0, 0, W2, H2), d = id.data; for (let i = 0; i < d.length; i += 4) { const a = Math.min(255, d[i] * 1.6); d[i + 3] = a; d[i] = d[i + 1] = d[i + 2] = 0; } mx.putImageData(id, 0, 0);
  bx.globalCompositeOperation = 'source-over'; bx.clearRect(0, 0, W2, H2); bx.filter = `blur(${(5.5 * amt).toFixed(2)}px)`; bx.drawImage(c.canvas, 0, BAR, VW, VH, 0, 0, W2, H2); bx.filter = 'none';
  bx.globalCompositeOperation = 'destination-in'; bx.drawImage(mk, 0, 0); bx.globalCompositeOperation = 'source-over';
  c.drawImage(bl, 0, 0, W2, H2, 0, BAR, VW, VH);
}

function drawTitle(c, a, end) {
  c.save(); c.globalAlpha = a; c.fillStyle = '#fff'; c.textAlign = 'center'; c.textBaseline = 'middle';
  c.shadowColor = 'rgba(0,0,0,0.35)'; c.shadowBlur = 18;
  c.font = '200 104px "Inter"'; c.letterSpacing = '34px';
  c.fillText('CLOUDBREAK', OW / 2 + 17, OH / 2 - (end ? 6 : 44));
  c.shadowBlur = 0; c.font = '300 22px "Inter"'; c.letterSpacing = '9px'; c.globalAlpha = a * 0.72;
  c.fillText('CONCEPT VISUALIZATION', OW / 2 + 4.5, OH / 2 + (end ? 74 : 36));
  c.restore();
}

function drawApproveShot(c, lt, C, sh) {
  // background: blurred, darkened still from the end of the pilot shot (cached)
  if (!S.bgCache.approve) {
    const pilotShot = S.shots.find(x => x.id === 'pilot'); const P = pilotShot.fn(pilotShot.dur);
    updatePlane(P.mt, true); S.grass.visible = true; setShadow(P.shadow[0], P.shadow[1]);
    const sc = S.screenCanvas, x = sc.getContext('2d'); x.fillStyle = '#05080d'; x.fillRect(0, 0, sc.width, sc.height); const p = ms(P.mt);
    drawUI(x, 0, 0, sc.width, sc.height, { t: 0, bars: [1, 1, 1], btnPulse: 1, planeXZ: [p.x, p.z], planeH: p.h }); S.screenTex.needsUpdate = true;
    setCamera(Object.assign({}, P, { pos: V3(-65.55, 1.30, 85.55), look: V3(-64.60, 0.88, 84.90), fov: 34 }), null);
    S.R.render(S.scene, S.cam);
    const small = canvas(480, 201), sx = small.getContext('2d'); sx.filter = 'blur(7px)'; sx.drawImage(S.gl, 0, 0, S.RW, S.RH, -20, -20, 520, 241);
    const big = canvas(VW, VH), bx = big.getContext('2d'); bx.imageSmoothingEnabled = true; bx.imageSmoothingQuality = 'high'; bx.filter = 'blur(6px)'; bx.drawImage(small, -30, -30, VW + 60, VH + 60); bx.filter = 'none'; bx.fillStyle = 'rgba(4,8,14,0.45)'; bx.fillRect(0, 0, VW, VH);
    S.bgCache.approve = big;
  }
  c.drawImage(S.bgCache.approve, 0, BAR);
  const inA = sm(0, 0.6, lt), outA = 1 - sm(7.6, 8.0, lt);
  const pw = 1500, ph = 620, scale = 0.965 + 0.035 * smr(inA);
  const X = (VW - pw * scale) / 2, Y = BAR + (VH - ph * scale) / 2;
  const t = lt;
  const cursorPath = (k) => { const a = [0.98, 1.05], b = [0.80, 0.765]; const e = smr(k); return [lerp(a[0], b[0], e) + 0.03 * Math.sin(e * Math.PI) * 0.5, lerp(a[1], b[1], e) - 0.08 * Math.sin(e * Math.PI)]; };
  const ck = sm(1.3, 2.5, t); const [cxp, cyp] = cursorPath(ck);
  const press = t > 2.6 && t < 4.25;
  const st = { t: lt, alpha: inA * outA, thinking: 1 - sm(1.2, 1.8, t), bars: [sm(0.6, 1.2, t), sm(0.85, 1.45, t), sm(1.1, 1.7, t)], btnPulse: sm(1.6, 2.0, t) * (1 - sm(2.6, 2.8, t)),
    hold: sm(2.6, 4.2, t) * (t < 4.2 ? 1 : 1 - sm(4.4, 4.7, t)), approved: sm(4.2, 4.35, t), okAge: t - 4.2,
    cursor: { x: cxp, y: cyp, a: sm(1.2, 1.5, t) * (1 - sm(4.6, 5.0, t)), press },
    gov: { show: sm(4.5, 4.8, t), checks: [4.9, 5.3, 5.7, 6.1].map(k => sm(k - 0.3, k, t)), lock: sm(6.4, 6.65, t) },
    send: t >= 6.6 ? sm(6.6, 7.5, t) : 0, sendArrive: sm(7.4, 7.6, t) };
  const p = ms(C.mt); st.planeXZ = [p.x, p.z]; st.planeH = p.h;
  c.save(); c.translate(X, Y); c.scale(scale, scale); drawUI(c, 0, 0, pw, ph, st); c.restore();
}

function cueOnly(ft) {
  const shots = S.shots; let sh = shots[shots.length - 1];
  for (const s of shots) { if (ft < s.start + s.dur) { sh = s; break; } }
  const lt = Math.max(0, ft - sh.start), C = sh.fn(lt), s = ms(C.mt);
  const dist = C.belly ? 0.1 : (C.ui ? 300 : C.pos.distanceTo(ppos(C.mt)));
  return { ft, shot: sh.id, lt, mt: C.mt, thr: s.thr, rpm: s.rpm, v: s.v, y: s.y, dist, belly: !!C.belly, ui: !!C.ui, fade: C.fade || 0, title: C.title || 0 };
}
// ------------------------------------------------------------ public API
window.FILM = {
  init, events: () => EVT, cues: (n) => { const out = []; for (let i = 0; i < n; i++) out.push(cueOnly(i / 30)); return out; },
  shots: () => S.shots.map(s => ({ id: s.id, start: s.start, dur: s.dur })),
  duration: () => S.duration,
  frame: async (ft) => { const cue = frame(ft); const bl = await new Promise(r => S.out.toBlob(r, 'image/jpeg', 0.93)); const ab = await bl.arrayBuffer(); const u = new Uint8Array(ab); let s = ''; for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); return { jpg: btoa(s), cue }; },
};
