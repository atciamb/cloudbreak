// Cloudbreak concept film — realistic-look replacements (leaf-card trees, textured ground, grass cards, water, plane, people, props)
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
export function rng(seed) { let s = seed >>> 0 || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }

const cnv = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

// ---------------------------------------------------------------- foliage atlas (2x2): broadleaf A/B, conifer A/B
function foliageAtlas() {
  const N = 1024, c = cnv(N, N), x = c.getContext('2d'), R = rng(4242);
  const H = N / 2;
  // broadleaf clusters
  for (let cell = 0; cell < 2; cell++) {
    const ox = cell * H, oy = 0, cx = ox + H / 2, cy = oy + H / 2;
    // twigs
    x.strokeStyle = 'rgba(70,52,38,1)'; x.lineCap = 'round';
    for (let k = 0; k < 7; k++) { const a = R() * Math.PI * 2; x.lineWidth = 3 + R() * 3; x.beginPath(); x.moveTo(cx, cy); x.quadraticCurveTo(cx + Math.cos(a + 0.4) * 90, cy + Math.sin(a + 0.4) * 90, cx + Math.cos(a) * 200, cy + Math.sin(a) * 200); x.stroke(); }
    const leaves = 520;
    for (let pass = 0; pass < 2; pass++) for (let i = 0; i < leaves / 2; i++) {
      const rr = 225 * Math.pow(R(), 0.62), a = R() * Math.PI * 2;
      const px = cx + Math.cos(a) * rr, py = cy + Math.sin(a) * rr * 0.92;
      const L = 0.55 + 0.45 * R() * (pass ? 1 : 0.7) * (1 - 0.35 * rr / 225);
      const rx = 9 + R() * 9, ry = 5 + R() * 5;
      x.save(); x.translate(px, py); x.rotate(R() * Math.PI * 2);
      const v = Math.round(255 * L), g = Math.round(v * (0.93 + 0.07 * R())), b = Math.round(v * (0.78 + 0.12 * R()));
      x.fillStyle = `rgb(${v},${g},${b})`; x.beginPath(); x.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2); x.fill();
      x.strokeStyle = `rgba(${Math.round(v * 0.7)},${Math.round(g * 0.7)},${Math.round(b * 0.7)},0.6)`; x.lineWidth = 1; x.beginPath(); x.moveTo(-rx, 0); x.lineTo(rx, 0); x.stroke();
      x.restore();
    }
  }
  // conifer branches: filled sprays + needle strokes
  for (let cell = 0; cell < 2; cell++) {
    const ox = cell * H, oy = H;
    x.save(); x.translate(ox, oy);
    for (let br = 0; br < 4; br++) {
      const y0 = 70 + br * 115 + (R() - 0.5) * 20, x0 = 12, x1 = 500 - R() * 30, wid = 70 - br * 6;
      // soft filled spray silhouette
      x.fillStyle = 'rgb(118,120,104)'; x.beginPath(); x.moveTo(x0, y0);
      for (let k = 0; k <= 24; k++) { const t = k / 24, xx = x0 + (x1 - x0) * t; x.lineTo(xx, y0 - wid * (1 - t) * (0.75 + 0.25 * Math.sin(t * 40 + br))); }
      for (let k = 24; k >= 0; k--) { const t = k / 24, xx = x0 + (x1 - x0) * t; x.lineTo(xx, y0 + wid * (1 - t) * (0.75 + 0.25 * Math.cos(t * 37 + br))); }
      x.closePath(); x.fill();
      x.strokeStyle = 'rgb(70,55,40)'; x.lineWidth = 6; x.beginPath(); x.moveTo(x0, y0); x.lineTo(x1, y0); x.stroke();
      for (let k = 0; k < 900; k++) {
        const t = R(), bx = x0 + (x1 - x0) * t, by = y0 + (R() - 0.5) * 8;
        const len = (wid * 0.9) * (1 - 0.8 * t) + 6, a = (R() < 0.5 ? -1 : 1) * (0.9 + R() * 0.6) + 0.35;
        const v = Math.round(255 * (0.45 + 0.55 * R())); x.strokeStyle = `rgb(${v},${v},${Math.round(v * 0.88)})`; x.lineWidth = 2.5;
        x.beginPath(); x.moveTo(bx, by); x.lineTo(bx + Math.cos(a) * len * 0.35, by + Math.sin(a) * len); x.stroke();
      }
    }
    x.restore();
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t.generateMipmaps = true;
  return t;
}

// card: quad centred at c, basis u (width) / v (height), atlas cell, color, normal bend toward n0
function pushCard(A, c, u, v, cell, col, center, radii, bend = 0.75) {
  const cu = (cell % 2) * 0.5, cv = cell < 2 ? 0.5 : 0.0;   // canvas row 0 => uv v in [0.5,1]
  const corners = [[-1, -1, cu, cv], [1, -1, cu + 0.5, cv], [1, 1, cu + 0.5, cv + 0.5], [-1, 1, cu, cv + 0.5]];
  const n = new THREE.Vector3().crossVectors(u, v).normalize();
  const base = A.pos.length / 3;
  corners.forEach(([a, b, uu, vv]) => {
    const p = c.clone().addScaledVector(u, a).addScaledVector(v, b);
    A.pos.push(p.x, p.y, p.z);
    const r = new THREE.Vector3((p.x - center.x) / radii.x, (p.y - center.y) / radii.y, (p.z - center.z) / radii.z).normalize();
    const nn = n.clone().multiplyScalar(1 - bend).addScaledVector(r, bend).normalize();
    A.nrm.push(nn.x, nn.y, nn.z); A.uv.push(uu, vv); A.col.push(col, col, col);
  });
  A.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
}
function finishGeo(A) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(A.pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(A.nrm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(A.uv, 2)); g.setAttribute('color', new THREE.Float32BufferAttribute(A.col, 3)); g.setIndex(A.idx);
  g.computeBoundingSphere(); return g;
}

// normalized tree geometries (height 1)
function broadleafGeo(seed, cards) {
  const R = rng(seed), A = { pos: [], nrm: [], uv: [], col: [], idx: [] };
  const center = new THREE.Vector3(0, 0.63, 0), radii = new THREE.Vector3(0.40, 0.35, 0.40);
  for (let i = 0; i < cards; i++) {
    let p; do { p = new THREE.Vector3(R() * 2 - 1, R() * 2 - 1, R() * 2 - 1); } while (p.lengthSq() > 1);
    const rr = Math.pow(p.length(), 0.45); p.normalize().multiplyScalar(rr);
    const c = new THREE.Vector3(center.x + p.x * radii.x, center.y + p.y * radii.y, center.z + p.z * radii.z);
    const e = new THREE.Euler(R() * Math.PI, R() * Math.PI * 2, R() * Math.PI); const q = new THREE.Quaternion().setFromEuler(e);
    const s = (cards > 20 ? 0.17 : 0.27) * (0.8 + 0.5 * R());
    const u = new THREE.Vector3(s, 0, 0).applyQuaternion(q), v = new THREE.Vector3(0, s, 0).applyQuaternion(q);
    const ao = 0.55 + 0.45 * Math.min(1, Math.max(0, 0.5 + 0.5 * p.y + 0.35 * rr));
    pushCard(A, c, u, v, R() < 0.5 ? 0 : 1, ao * (0.85 + 0.3 * R()), center, radii);
  }
  const g = finishGeo(A);
  const trunk = new THREE.CylinderGeometry(0.018, 0.034, 0.56, 7, 1, true); trunk.translate(0, 0.28, 0);
  const brs = [];
  for (let k = 0; k < 5; k++) { const b = new THREE.CylinderGeometry(0.006, 0.012, 0.26, 5, 1, true); b.translate(0, 0.13, 0); b.rotateZ(0.7 + R() * 0.3); b.rotateY(k / 5 * Math.PI * 2 + R()); b.translate(0, 0.36 + R() * 0.12, 0); brs.push(b); }
  const wood = mergeGeometries([trunk, ...brs].map(x => x.toNonIndexed()));
  const wc = []; for (let i = 0; i < wood.attributes.position.count; i++) wc.push(0.16, 0.12, 0.09);
  wood.setAttribute('color', new THREE.Float32BufferAttribute(wc, 3)); wood.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(wood.attributes.position.count * 2).fill(0.001), 2));
  return { leaves: g, wood };
}

function noFlip(m) { m.onBeforeCompile = (sh) => { sh.fragmentShader = sh.fragmentShader.replace('#include <normal_fragment_begin>', THREE.ShaderChunk.normal_fragment_begin.replace('normal *= faceDirection;', '').replace('normal = normal * faceDirection;', '')); }; m.customProgramCacheKey = () => 'noflip'; return m; }
function coniferGeo(seed, levels, per) {
  const R = rng(seed), A = { pos: [], nrm: [], uv: [], col: [], idx: [] };
  const center = new THREE.Vector3(0, 0.45, 0), radii = new THREE.Vector3(0.3, 0.6, 0.3);
  for (let l = 0; l < levels; l++) {
    const y = 0.12 + 0.72 * l / (levels - 1), rad = 0.30 * Math.pow(1 - (y - 0.1) / 0.86, 1.0) + 0.05;
    const n = Math.max(5, Math.round(per * (0.5 + rad / 0.3 * 0.7)));
    for (let k = 0; k < n; k++) {
      const a = (k / n + R() * 0.15 + l * 0.37) * Math.PI * 2, dir = new THREE.Vector3(Math.cos(a), 0, Math.sin(a));
      const droop = -0.35 - R() * 0.25;
      const u = dir.clone().multiplyScalar(rad * 0.55).add(new THREE.Vector3(0, droop * rad * 0.5, 0));
      const side = new THREE.Vector3(-dir.z, 0, dir.x).multiplyScalar(rad * 0.38).add(new THREE.Vector3(0, rad * 0.12, 0));
      const c = new THREE.Vector3(0, y, 0).addScaledVector(u, 1.0);
      const ao = 0.5 + 0.5 * (y + 0.2 * R());
      pushCard(A, c, u, side, R() < 0.5 ? 2 : 3, ao, center, radii, 0.6);
    }
  }
  [[0.885, 0.05, 5], [0.925, 0.036, 4], [0.955, 0.024, 3]].forEach(([y, rad, n], li) => { for (let k = 0; k < n; k++) {
    const a = (k / n + li * 0.29 + R() * 0.1) * Math.PI * 2, dir = new THREE.Vector3(Math.cos(a), 0, Math.sin(a));
    const u = dir.clone().multiplyScalar(rad * 0.6).add(new THREE.Vector3(0, -0.2 * rad, 0)), side = new THREE.Vector3(-dir.z, 0, dir.x).multiplyScalar(rad * 0.4).add(new THREE.Vector3(0, rad * 0.15, 0));
    pushCard(A, new THREE.Vector3(0, y, 0).addScaledVector(u, 1.0), u, side, R() < 0.5 ? 2 : 3, 1.0, center, radii, 0.6); } });
  const g = finishGeo(A);
  const trunk = new THREE.CylinderGeometry(0.008, 0.024, 0.8, 6, 1, true); trunk.translate(0, 0.4, 0);
  const wood = trunk.toNonIndexed(); const wc = []; for (let i = 0; i < wood.attributes.position.count; i++) wc.push(0.14, 0.10, 0.08);
  wood.setAttribute('color', new THREE.Float32BufferAttribute(wc, 3)); wood.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(wood.attributes.position.count * 2).fill(0.001), 2));
  return { leaves: g, wood };
}

export function buildTreesReal(W) {
  const atlas = foliageAtlas();
  const leafM = noFlip(new THREE.MeshLambertMaterial({ map: atlas, vertexColors: true, alphaTest: 0.45, side: THREE.DoubleSide, alphaToCoverage: true }));
  const woodM = new THREE.MeshLambertMaterial({ vertexColors: true });
  const pineM = noFlip(new THREE.MeshLambertMaterial({ map: atlas, vertexColors: true, alphaTest: 0.3, side: THREE.DoubleSide, alphaToCoverage: true }));
  const kinds = {
    roundN: broadleafGeo(11, 44), roundF: broadleafGeo(12, 13),
    pineN: coniferGeo(21, 10, 6), pineF: coniferGeo(22, 9, 5),
  };
  const autumn = [0xd2782c, 0xe0a634, 0xb84a2c, 0xe8bf52, 0xb2622e, 0xd8903c, 0x9c3a24].map(c => new THREE.Color(c));
  const greens = [0x6a8a34, 0x5a7a30, 0x7d8a3a].map(c => new THREE.Color(c));
  const pinesC = [0x3c5a34, 0x31502f, 0x40603a, 0x2f4d38].map(c => new THREE.Color(c));
  const M = W.layout.meadow;
  const sdRect = (x, z) => { const cx = (M.xmin + M.xmax) / 2, cz = (M.zmin + M.zmax) / 2, hx = (M.xmax - M.xmin) / 2, hz = (M.zmax - M.zmin) / 2; const qx = Math.abs(x - cx) - hx, qz = Math.abs(z - cz) - hz; return Math.hypot(Math.max(qx, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qz), 0); };
  const TILE = 160, tiles = new Map();
  W.trees.forEach(t => { const far = sdRect(t[0], t[2]) > 120; const k = (far ? 'F' : 'N') + Math.floor((t[0] + 800) / TILE) + ',' + Math.floor((t[2] + 800) / TILE); if (!tiles.has(k)) tiles.set(k, { far, list: [] }); tiles.get(k).list.push(t); });
  const G = new THREE.Group(), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  tiles.forEach(({ far, list }) => {
    ['round', 'pine'].forEach(kind => {
      const L = list.filter(t => t[3] === kind); if (!L.length) return;
      const geo = kinds[kind + (far ? 'F' : 'N')];
      const leaves = new THREE.InstancedMesh(geo.leaves, kind === 'pine' ? pineM : leafM, L.length), wood = new THREE.InstancedMesh(geo.wood, woodM, L.length);
      L.forEach(([x, y, z, k2, h, au, seed], i) => {
        const r = rng(seed + 3); q.setFromAxisAngle(up, r() * Math.PI * 2);
        const w = kind === 'pine' ? h * (0.85 + 0.3 * r()) : h * (0.95 + 0.35 * r());
        p.set(x, y - 0.3, z); s.set(w, h, w); m4.compose(p, q, s); leaves.setMatrixAt(i, m4); wood.setMatrixAt(i, m4);
        const pal = kind === 'pine' ? pinesC : (au ? autumn : greens);
        const col = pal[Math.floor(r() * pal.length)].clone().multiplyScalar(0.85 + 0.3 * r());
        leaves.setColorAt(i, col); wood.setColorAt(i, new THREE.Color(1, 1, 1));
      });
      [leaves, wood].forEach(m => { m.castShadow = true; m.receiveShadow = true; m.instanceMatrix.needsUpdate = true; m.instanceColor.needsUpdate = true; m.computeBoundingSphere(); G.add(m); });
    });
  });
  return G;
}

// ---------------------------------------------------------------- terrain with photographic grass detail
export function buildTerrainReal(W, groundTex, detailTex, grassTex) {
  const hd = W.height, n = hd.n;
  const g = new THREE.PlaneGeometry(hd.size, hd.size, n - 1, n - 1); g.rotateX(-Math.PI / 2);
  const pos = g.attributes.position; for (let k = 0; k < pos.count; k++) pos.setY(k, hd.data[k]); g.computeVertexNormals();
  const mat = new THREE.MeshLambertMaterial({ map: groundTex });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uDetail = { value: detailTex }; sh.uniforms.uGrass = { value: grassTex };
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWP;').replace('#include <project_vertex>', '#include <project_vertex>\nvWP = (modelMatrix*vec4(transformed,1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vWP; uniform sampler2D uDetail; uniform sampler2D uGrass;')
      .replace('#include <map_fragment>', `#include <map_fragment>
        vec3 macro = diffuseColor.rgb;
        float green = smoothstep(0.0, 0.06, macro.g - max(macro.r, macro.b) * 0.92);
        float Lm = dot(macro, vec3(0.3, 0.59, 0.11));
        macro = mix(macro, vec3(Lm) * vec3(1.14, 1.07, 0.60), 0.46 * green);
        float n1 = texture2D(uDetail, vWP.xz * 0.011).r, n2 = texture2D(uDetail, vWP.xz * 0.047 + 0.31).r;
        float n3 = texture2D(uDetail, vWP.xz * 0.23 + 0.67).r, n4 = texture2D(uDetail, vWP.xz * 1.37 + 0.11).r, n5 = texture2D(uDetail, vWP.xz * 4.1 + 0.53).r;
        float dryM = smoothstep(0.44, 0.62, n1 * 0.55 + n2 * 0.45);
        vec3 col = macro * mix(vec3(1.0), vec3(1.22, 1.10, 0.70), dryM * 0.6 * green);
        col *= mix(vec3(1.0), vec3(0.86, 0.95, 0.80), smoothstep(0.5, 0.35, n2) * 0.5 * green);
        col *= 0.70 + 0.30 * n2 + 0.32 * n3 + green * (0.55 * (n4 - 0.48) + 0.45 * (n5 - 0.48));
        vec3 g3 = texture2D(uGrass, vWP.xz / 1.7 + 0.13).rgb; float gl = dot(g3, vec3(0.3, 0.59, 0.11)) / 0.19;
        col *= mix(1.0, 0.8 + 0.25 * gl, 0.25 * green);
        diffuseColor.rgb = col;`);
  };
  const m = new THREE.Mesh(g, mat); m.receiveShadow = true; return m;
}

export function buildWaterReal(L, normalTex) {
  const P = L.pond; const g = new THREE.CircleGeometry(1, 96); g.rotateX(-Math.PI / 2);
  normalTex.wrapS = normalTex.wrapT = THREE.RepeatWrapping; normalTex.repeat.set(6, 4);
  const mat = new THREE.MeshStandardMaterial({ color: 0x1b3238, roughness: 0.04, metalness: 0.0, normalMap: normalTex, normalScale: new THREE.Vector2(0.25, 0.25), envMapIntensity: 1.8 });
  const m = new THREE.Mesh(g, mat); m.scale.set(P.rx, 1, P.rz); m.position.set(P.cx, 0.05, P.cz); m.receiveShadow = true; m.userData.nt = normalTex; return m;
}

// ---------------------------------------------------------------- textured grass tufts
export function buildGrassReal(zones) {
  const c = cnv(256, 256), x = c.getContext('2d'), R = rng(77);
  for (let i = 0; i < 120; i++) {
    const bx = 128 + (R() - 0.5) * 230, h = 90 + R() * 160, lean = (R() - 0.5) * 90, w = 2 + R() * 3.5;
    const v = 0.7 + 0.3 * R(); const g = x.createLinearGradient(0, 256, 0, 256 - h);
    g.addColorStop(0, `rgb(${Math.round(170 * v)},${Math.round(180 * v)},${Math.round(120 * v)})`); g.addColorStop(1, `rgb(${Math.round(250 * v)},${Math.round(246 * v)},${Math.round(200 * v)})`);
    x.fillStyle = g; x.beginPath(); x.moveTo(bx - w, 256); x.quadraticCurveTo(bx + lean * 0.3, 256 - h * 0.6, bx + lean, 256 - h); x.quadraticCurveTo(bx + lean * 0.3 + w * 0.4, 256 - h * 0.6, bx + w, 256); x.fill();
  }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const quads = [];
  for (let k = 0; k < 3; k++) { const q = new THREE.PlaneGeometry(1, 1); q.translate(0, 0.5, 0); q.rotateY(k * Math.PI / 3); quads.push(q); }
  const geo = mergeGeometries(quads); const nr = geo.attributes.normal; for (let i = 0; i < nr.count; i++) nr.setXYZ(i, 0, 1, 0);
  const mat = noFlip(new THREE.MeshLambertMaterial({ map: tex, alphaTest: 0.4, side: THREE.DoubleSide, alphaToCoverage: true }));
  const total = zones.reduce((a, z) => a + z.n, 0); const im = new THREE.InstancedMesh(geo, mat, total);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), s = new THREE.Vector3(), p = new THREE.Vector3(), Rg = rng(1234);
  const pal = [0x9aa652, 0xaaaa5c, 0xbdb26c, 0x8e9c4c, 0xc8b878, 0xa6a258].map(c2 => new THREE.Color(c2)); let i = 0;
  zones.forEach(Z => { for (let k = 0; k < Z.n; k++) {
    const xx = Z.x0 + Rg() * (Z.x1 - Z.x0), zz = Z.z0 + Rg() * (Z.z1 - Z.z0); const onSkip = Z.skip && Z.skip(xx, zz);
    const h = (Z.h0 + Rg() * (Z.h1 - Z.h0)) * (onSkip ? 0.3 : 1), w = h * (0.9 + 0.6 * Rg());
    e.set((Rg() - 0.5) * 0.25, Rg() * 6.3, (Rg() - 0.5) * 0.25); q.setFromEuler(e); s.set(w, h, w); p.set(xx, -0.01, zz); m4.compose(p, q, s); im.setMatrixAt(i, m4);
    im.setColorAt(i, pal[Math.floor(Rg() * pal.length)].clone().multiplyScalar((Z.tint ?? 1) * (0.8 + 0.35 * Rg()))); i++; } });
  im.instanceMatrix.needsUpdate = true; im.instanceColor.needsUpdate = true; im.computeBoundingSphere(); im.receiveShadow = true;
  return im;
}

// ---------------------------------------------------------------- people (smoother)
export function buildPersonReal(opts) {
  const { shirt = 0x2f6fb3, pants = 0x2b2f3a, skin = 0xc68e62, hair = 0x3a2a1f, seated = false, cap = null } = opts;
  const M = (c, r = 0.85) => new THREE.MeshStandardMaterial({ color: c, roughness: r });
  const g = new THREE.Group(), sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };
  const lh = seated ? 0.45 : 0.86;
  [-0.09, 0.09].forEach(dx => { const l = sh(new THREE.Mesh(new THREE.CapsuleGeometry(0.065, 0.72, 4, 10), M(pants))); l.position.set(dx, lh - 0.42, 0); if (seated) { l.rotation.x = -Math.PI / 2 + 0.15; l.position.set(dx, lh - 0.36, 0.38); } g.add(l); });
  [-0.09, 0.09].forEach(dx => { const sh2 = sh(new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.07, 0.24), M(0x2a2420, 0.6))); sh2.position.set(dx, seated ? 0.05 : 0.035, seated ? 0.8 : 0.04); g.add(sh2); });
  const torso = sh(new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.36, 6, 14), M(shirt))); torso.position.y = lh + 0.31; torso.scale.set(1, 1, 0.68); g.add(torso);
  const neck = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.055, 0.08, 10), M(skin, 0.6))); neck.position.y = lh + 0.66; g.add(neck);
  const head = sh(new THREE.Mesh(new THREE.SphereGeometry(0.105, 20, 16), M(skin, 0.55))); head.scale.set(0.92, 1.08, 1.0); head.position.y = lh + 0.77; g.add(head);
  const hairM = sh(new THREE.Mesh(new THREE.SphereGeometry(0.11, 20, 14), M(hair, 0.9))); hairM.position.set(0, lh + 0.795, -0.022); hairM.scale.set(0.95, 0.95, 0.95); g.add(hairM);
  if (cap) { const c = sh(new THREE.Mesh(new THREE.SphereGeometry(0.113, 20, 10, 0, Math.PI * 2, 0, Math.PI * 0.5), M(cap, 0.8))); c.position.y = lh + 0.81; g.add(c); const b = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.012, 16, 1, false, -Math.PI / 2, Math.PI), M(cap, 0.8))); b.position.set(0, lh + 0.815, 0.08); g.add(b); }
  const arms = [];
  [-0.21, 0.21].forEach(dx => { const a = new THREE.Group(); const up = sh(new THREE.Mesh(new THREE.CapsuleGeometry(0.05, 0.5, 4, 10), M(shirt))); up.position.y = -0.28; a.add(up); const hand = sh(new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 10), M(skin, 0.6))); hand.position.y = -0.57; a.add(hand); a.position.set(dx, lh + 0.56, 0); a.rotation.z = dx < 0 ? 0.1 : -0.1; g.add(a); arms.push(a); });
  g.userData = { head, arms, torso, lh };
  return g;
}

// ---------------------------------------------------------------- props: textures for barn, hay, rocks
export function propTextures() {
  const plank = cnv(512, 256), px = plank.getContext('2d'), R = rng(9);
  for (let i = 0; i < 32; i++) { const v = 0.75 + 0.25 * R(); px.fillStyle = `rgb(${Math.round(150 * v)},${Math.round(44 * v)},${Math.round(34 * v)})`; px.fillRect(i * 16, 0, 16, 256); px.fillStyle = 'rgba(40,10,8,0.6)'; px.fillRect(i * 16, 0, 1.5, 256);
    for (let k = 0; k < 30; k++) { px.fillStyle = `rgba(${R() < 0.5 ? '255,220,200' : '30,8,6'},${0.05 + 0.08 * R()})`; px.fillRect(i * 16 + R() * 14, R() * 256, 1 + R() * 2, 10 + R() * 60); } }
  const roof = cnv(256, 256), rx = roof.getContext('2d');
  for (let i = 0; i < 32; i++) { const v = 0.75 + 0.15 * Math.sin(i * 1.9); rx.fillStyle = `rgb(${Math.round(110 * v)},${Math.round(112 * v)},${Math.round(116 * v)})`; rx.fillRect(i * 8, 0, 8, 256); }
  for (let k = 0; k < 400; k++) { rx.fillStyle = `rgba(${R() < 0.6 ? '120,70,40' : '200,200,200'},${0.05 + 0.1 * R()})`; rx.fillRect(R() * 256, R() * 256, 2 + R() * 8, 2 + R() * 8); }
  const straw = cnv(256, 256), sx = straw.getContext('2d'); sx.fillStyle = 'rgb(196,160,84)'; sx.fillRect(0, 0, 256, 256);
  for (let k = 0; k < 1400; k++) { const v = 0.6 + 0.6 * R(); sx.strokeStyle = `rgba(${Math.round(220 * v)},${Math.round(180 * v)},${Math.round(100 * v)},0.7)`; sx.lineWidth = 1 + R(); sx.beginPath(); const x0 = R() * 256, y0 = R() * 256, a = R() * 3.14; sx.moveTo(x0, y0); sx.lineTo(x0 + Math.cos(a) * 20, y0 + Math.sin(a) * 6); sx.stroke(); }
  const T = (c) => { const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; return t; };
  return { plank: T(plank), roof: T(roof), straw: T(straw) };
}

export function rockGeometry(seed) {
  const g = new THREE.IcosahedronGeometry(1, 3), p = g.attributes.position, R = rng(seed);
  const o = [R() * 10, R() * 10, R() * 10];
  for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i), z = p.getZ(i); const n = 1 + 0.18 * Math.sin(x * 3.1 + o[0]) * Math.cos(y * 2.7 + o[1]) + 0.1 * Math.sin(z * 5.3 + o[2]) + 0.05 * Math.sin((x + z) * 9.1); p.setXYZ(i, x * n, y * n * 0.62, z * n); }
  g.computeVertexNormals(); return g;
}

// ---------------------------------------------------------------- plane with airfoil wing and finer details
export function buildPlaneReal() {
  const WHITE = new THREE.Color(0xf2f0ea), NAVY = new THREE.Color(0x1d2b4c), ORANGE = new THREE.Color(0xff6a1a);
  const foam = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.62, metalness: 0.0 });
  const sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };
  const faceColor = (geom, fn) => { const g = geom.index ? geom.toNonIndexed() : geom; const p = g.attributes.position, c = new Float32Array(p.count * 3);
    for (let i = 0; i < p.count; i += 3) { const cx = (p.getX(i) + p.getX(i + 1) + p.getX(i + 2)) / 3, cy = (p.getY(i) + p.getY(i + 1) + p.getY(i + 2)) / 3, cz = (p.getZ(i) + p.getZ(i + 1) + p.getZ(i + 2)) / 3;
      const col = fn(cx, cy, cz); for (let k = 0; k < 3; k++) { c[(i + k) * 3] = col.r; c[(i + k) * 3 + 1] = col.g; c[(i + k) * 3 + 2] = col.b; } }
    g.setAttribute('color', new THREE.BufferAttribute(c, 3)); return g; };
  const G = new THREE.Group(), parts = {};
  // fuselage (box foam with livery), slightly softened normals
  let fg = new THREE.BoxGeometry(0.86, 0.11, 0.09, 14, 8, 3); fg.translate(-0.17, -0.02, 0);
  fg = faceColor(fg, (x, y) => (y < -0.047 ? NAVY : (y < -0.034 ? ORANGE : WHITE)));
  const fp = fg.attributes.position;
  for (let i = 0; i < fp.count; i++) { const x = fp.getX(i); let y = fp.getY(i), z = fp.getZ(i); const t = Math.min(1, Math.max(0, (-0.12 - x) / 0.48));
    const yb = -0.075 + 0.062 * t, yt = 0.035 - 0.012 * t; y = yb + (y + 0.075) / 0.11 * (yt - yb); z = z * (1 - 0.45 * t);
    if (x > 0.2) { const k = (x - 0.2) / 0.06; y = y * (1 - 0.18 * k); z = z * (1 - 0.15 * k); } fp.setY(i, y); fp.setZ(i, z); }
  fg.computeVertexNormals(); G.add(sh(new THREE.Mesh(fg, foam)));
  const hatch = sh(new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.006, 0.07), new THREE.MeshStandardMaterial({ color: 0x1d2a44, roughness: 0.25, metalness: 0.2 }))); hatch.position.set(0.15, 0.037, 0); G.add(hatch);
  // airfoil wing halves (Clark-Y-ish), extruded along span
  const af = new THREE.Shape(); const ch = 0.165, th = 0.022, N = 18; const top = [], bot = [];
  for (let i = 0; i <= N; i++) { const u = i / N, xx = 0.5 * (1 - Math.cos(Math.PI * u)); const t = 5 * th * (0.2969 * Math.sqrt(xx) - 0.126 * xx - 0.3516 * xx * xx + 0.2843 * xx ** 3 - 0.1015 * xx ** 4); const camber = 0.035 * Math.sin(Math.PI * xx) * ch; top.push([-xx * ch, camber + t * 0.5]); bot.push([-xx * ch, camber * 0.3 - t * 0.35]); }
  af.moveTo(top[0][0], top[0][1]); top.slice(1).forEach(([a, b]) => af.lineTo(a, b)); bot.reverse().forEach(([a, b]) => af.lineTo(a, b));
  ['L', 'R'].forEach((s) => {
    const side = s === 'R' ? 1 : -1, half = new THREE.Group();
    let wg = new THREE.ExtrudeGeometry(af, { depth: 0.53, bevelEnabled: false, steps: 12, curveSegments: 4 }); if (side < 0) wg.translate(0, 0, -0.53);
    wg.translate(0.06, 0, 0);
    wg = faceColor(wg, (x, y, z) => { const a = Math.abs(z); return a > 0.455 ? NAVY : (a > 0.42 && a < 0.44 ? ORANGE : WHITE); }); wg.computeVertexNormals();
    half.add(sh(new THREE.Mesh(wg, foam)));
    const ail = new THREE.Group(); ail.position.set(-0.105, 0.004, side * 0.395);
    let ag = new THREE.BoxGeometry(0.045, 0.007, 0.25, 1, 1, 12); ag.translate(-0.0225, 0, 0);
    ag = faceColor(ag, (x, y, z) => { const a = Math.abs(z + side * 0.395); return a > 0.455 ? NAVY : (a > 0.42 && a < 0.44 ? ORANGE : WHITE); }); ag.computeVertexNormals();
    ail.add(sh(new THREE.Mesh(ag, foam))); half.add(ail); parts['ail' + s] = ail;
    const inb = new THREE.BoxGeometry(0.045, 0.007, 0.27); inb.translate(-0.1275, 0.004, side * 0.135); half.add(sh(new THREE.Mesh(faceColor(inb, () => WHITE), foam)));
    half.position.set(0.0, 0.040, 0); half.rotation.x = -side * 0.052; G.add(half);
  });
  // tail
  let stab = new THREE.BoxGeometry(0.08, 0.006, 0.38, 1, 1, 12); stab.translate(-0.53, 0.014, 0); stab = faceColor(stab, (x, y, z) => (Math.abs(z) > 0.15 ? NAVY : WHITE)); stab.computeVertexNormals(); G.add(sh(new THREE.Mesh(stab, foam)));
  const ele = new THREE.Group(); ele.position.set(-0.57, 0.014, 0); let eg = new THREE.BoxGeometry(0.042, 0.006, 0.36); eg.translate(-0.021, 0, 0); ele.add(sh(new THREE.Mesh(faceColor(eg, () => ORANGE), foam))); G.add(ele); parts.ele = ele;
  let fin = new THREE.BoxGeometry(0.09, 0.14, 0.006); fin.translate(-0.535, 0.088, 0); G.add(sh(new THREE.Mesh(faceColor(fin, () => NAVY), foam)));
  const rud = new THREE.Group(); rud.position.set(-0.58, 0.02, 0); let rg = new THREE.BoxGeometry(0.042, 0.15, 0.006); rg.translate(-0.021, 0.075, 0); rud.add(sh(new THREE.Mesh(faceColor(rg, () => ORANGE), foam))); G.add(rud); parts.rud = rud;
  // pushrods + horns
  const rodM = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.4, metalness: 0.5 });
  [[0.0, -0.01, 0.047, -0.56, 0.02, 0.012], [0.0, 0.0, -0.047, -0.57, 0.05, -0.01]].forEach(([x0, y0, z0, x1, y1, z1]) => { const a = new THREE.Vector3(x0, y0, z0), b = new THREE.Vector3(x1, y1, z1), d = b.clone().sub(a); const r = new THREE.Mesh(new THREE.CylinderGeometry(0.0012, 0.0012, d.length(), 4), rodM); r.position.copy(a).addScaledVector(d, 0.5); r.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.normalize()); G.add(r); });
  // gear
  const wireM = new THREE.MeshStandardMaterial({ color: 0xb0b0b0, roughness: 0.25, metalness: 0.9 });
  const tyreM = new THREE.MeshStandardMaterial({ color: 0x161616, roughness: 0.85 }), hubM = new THREE.MeshStandardMaterial({ color: 0xff6a1a, roughness: 0.45 });
  const strut = (a, b) => { const d = new THREE.Vector3().subVectors(b, a); const m = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.0035, 0.0035, d.length(), 6), wireM)); m.position.copy(a).addScaledVector(d, 0.5); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.clone().normalize()); return m; };
  const wheel = (r) => { const w = new THREE.Group(); const t = sh(new THREE.Mesh(new THREE.TorusGeometry(r * 0.72, r * 0.3, 10, 24), tyreM)); w.add(t); const h = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.48, r * 0.48, 0.02, 18), hubM); h.rotation.x = Math.PI / 2; w.add(h); return w; };
  parts.wheels = [];
  [-1, 1].forEach(s => { G.add(strut(new THREE.Vector3(-0.04, -0.07, s * 0.035), new THREE.Vector3(-0.04, -0.14, s * 0.125))); const w = wheel(0.05); w.position.set(-0.04, -0.14, s * 0.135); G.add(w); parts.wheels.push(w); });
  G.add(strut(new THREE.Vector3(0.22, -0.06, 0), new THREE.Vector3(0.22, -0.145, 0))); const nw = wheel(0.045); nw.position.set(0.22, -0.145, 0); G.add(nw); parts.wheels.push(nw);
  // camera pod, GPS, antenna
  const pod = sh(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.03, 0.042), new THREE.MeshStandardMaterial({ color: 0x15171b, roughness: 0.35 }))); pod.position.set(0.0, -0.088, 0); G.add(pod);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.009, 0.009, 0.006, 20), new THREE.MeshStandardMaterial({ color: 0x0a0d12, roughness: 0.02, metalness: 0.8 })); lens.position.set(0.0, -0.105, 0); G.add(lens);
  const gps = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.024, 0.024, 0.01, 20), new THREE.MeshStandardMaterial({ color: 0x2b2e33, roughness: 0.4 }))); gps.position.set(-0.03, 0.062, 0); G.add(gps);
  const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.001, 0.001, 0.12, 4), rodM); ant.position.set(-0.25, 0.06, 0.03); ant.rotation.z = 0.5; G.add(ant);
  // motor, spinner, prop
  const motor = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.03, 18), new THREE.MeshStandardMaterial({ color: 0x3a3a3a, roughness: 0.25, metalness: 0.85 }))); motor.rotation.z = Math.PI / 2; motor.position.set(0.272, -0.012, 0); G.add(motor);
  const prop = new THREE.Group(); prop.position.set(0.30, -0.012, 0);
  const spin = sh(new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.04, 20), new THREE.MeshStandardMaterial({ color: 0xff6a1a, roughness: 0.35 }))); spin.rotation.z = -Math.PI / 2; spin.position.x = 0.02; prop.add(spin);
  const bladeM = new THREE.MeshStandardMaterial({ color: 0x181818, roughness: 0.35, transparent: true, opacity: 1 });
  const blades = new THREE.Group();
  [-1, 1].forEach(s => { const bg = new THREE.BoxGeometry(0.004, 0.105, 0.016, 1, 6, 1); const bp = bg.attributes.position; for (let i = 0; i < bp.count; i++) { const y = bp.getY(i); const k = (y + 0.0525) / 0.105; bp.setZ(i, bp.getZ(i) * (1.15 - 0.6 * k)); } bg.computeVertexNormals(); const b = sh(new THREE.Mesh(bg, bladeM)); b.position.y = s * 0.058; b.rotation.y = s * 0.28; blades.add(b); });
  prop.add(blades);
  const dc = cnv(128, 128), dx = dc.getContext('2d'); const gr = dx.createRadialGradient(64, 64, 6, 64, 64, 64);
  gr.addColorStop(0, 'rgba(30,30,30,0.0)'); gr.addColorStop(0.25, 'rgba(30,30,30,0.28)'); gr.addColorStop(0.85, 'rgba(40,40,40,0.22)'); gr.addColorStop(0.97, 'rgba(60,60,60,0.35)'); gr.addColorStop(1, 'rgba(60,60,60,0)');
  dx.fillStyle = gr; dx.fillRect(0, 0, 128, 128);
  const disc = new THREE.Mesh(new THREE.CircleGeometry(0.118, 48), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(dc), transparent: true, depthWrite: false, side: THREE.DoubleSide, opacity: 0 }));
  disc.rotation.y = Math.PI / 2; prop.add(disc); G.add(prop);
  Object.assign(parts, { prop, blades, bladeM, disc }); G.userData = parts;
  return G;
}

// ---------------------------------------------------------------- shrubs: small leaf-card clusters
export function buildBushesReal(list) {
  const atlas = foliageAtlas(); const geo = broadleafGeo(31, 30).leaves; geo.translate(0, -0.26, 0);
  const m = noFlip(new THREE.MeshLambertMaterial({ map: atlas, vertexColors: true, alphaTest: 0.45, side: THREE.DoubleSide, alphaToCoverage: true }));
  const im = new THREE.InstancedMesh(geo, m, list.length);
  const cols = [0x4f6328, 0x66702e, 0x7a5a2c, 0x45592a, 0x8a6a30, 0x5c6a2a].map(c => new THREE.Color(c));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), sc = new THREE.Vector3(), ps = new THREE.Vector3();
  list.forEach(([x, z, s, seed], i) => { const R = rng(seed + 5); e.set(0, R() * 6.3, 0); q.setFromEuler(e); const k = s / 0.4 * 1.15; sc.set(k * (0.9 + 0.3 * R()), k * (0.75 + 0.3 * R()), k * (0.9 + 0.3 * R())); ps.set(x, 0, z); m4.compose(ps, q, sc); im.setMatrixAt(i, m4); im.setColorAt(i, cols[Math.floor(R() * cols.length)]); });
  im.instanceMatrix.needsUpdate = true; im.instanceColor.needsUpdate = true; im.castShadow = true; im.receiveShadow = true; im.computeBoundingSphere();
  return im;
}
