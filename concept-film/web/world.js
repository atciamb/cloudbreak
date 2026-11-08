// Cloudbreak concept film — world construction (terrain, sky, vegetation, props, people, plane)
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { buildPersonReal, propTextures, rockGeometry, buildBushesReal } from './real.js';

export function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

export const SUN = (() => {
  const el = THREE.MathUtils.degToRad(11.5);
  const az = Math.atan2(-0.423, -0.906);            // west-north-west
  return new THREE.Vector3(Math.cos(el) * Math.cos(az), Math.sin(el), Math.cos(el) * Math.sin(az)).normalize();
})();

// ---------------------------------------------------------------- height lookup
export function makeHeight(hd) {
  const n = hd.n, size = hd.size, d = hd.data;
  return (x, z) => {
    const u = (x + size / 2) / size * (n - 1), v = (z + size / 2) / size * (n - 1);
    const j = Math.max(0, Math.min(n - 2, Math.floor(u))), i = Math.max(0, Math.min(n - 2, Math.floor(v)));
    const fu = Math.min(1, Math.max(0, u - j)), fv = Math.min(1, Math.max(0, v - i));
    const a = d[i * n + j] * (1 - fu) + d[i * n + j + 1] * fu;
    const b = d[(i + 1) * n + j] * (1 - fu) + d[(i + 1) * n + j + 1] * fu;
    return a * (1 - fv) + b * fv;
  };
}

// ---------------------------------------------------------------- sky
export function buildSky() {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { uSun: { value: SUN.clone() }, uTime: { value: 0 } },
    vertexShader: `varying vec3 vDir; void main(){ vDir = normalize(position); vec4 p = modelViewMatrix*vec4(position,1.0); gl_Position = projectionMatrix*p; gl_Position.z = gl_Position.w*0.99999; }`,
    fragmentShader: `
      uniform vec3 uSun; uniform float uTime; varying vec3 vDir;
      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      float noise(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
        return mix(mix(hash(i),hash(i+vec2(1,0)),f.x), mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x), f.y); }
      float fbm(vec2 p){ float a=0.5, s=0.0; for(int k=0;k<4;k++){ s+=a*noise(p); p=p*2.03+vec2(1.7,9.2); a*=0.5; } return s; }
      vec3 lin(vec3 c){ return pow(c, vec3(2.2)); }
      void main(){
        vec3 d = normalize(vDir);
        float e = d.y;
        float sd = max(dot(d, uSun), 0.0);
        float sh = max(dot(normalize(vec3(d.x,0.0,d.z)), normalize(vec3(uSun.x,0.0,uSun.z))), 0.0);
        vec3 zen = lin(vec3(0.24,0.40,0.66)), mid = lin(vec3(0.58,0.68,0.82));
        vec3 horWarm = lin(vec3(1.00,0.70,0.44)), horCool = lin(vec3(0.86,0.72,0.74));
        vec3 hor = mix(horCool, horWarm, pow(sh, 2.0));
        float ee = max(e, 0.0);
        vec3 col = mix(hor, mid, smoothstep(0.0, 0.22, ee));
        col = mix(col, zen, smoothstep(0.18, 0.85, ee));
        col += lin(vec3(1.0,0.62,0.30)) * pow(sd, 6.0) * 0.55;
        col += lin(vec3(1.0,0.80,0.55)) * pow(sd, 60.0) * 1.2;
        // clouds: domain-warped altocumulus + cirrus, lit from the sun side
        if (e > 0.0) {
          vec2 p = d.xz / (e + 0.07) * 1.15 + vec2(uTime*0.004, uTime*0.001);
          vec2 q = vec2(fbm(p*0.55), fbm(p*0.55 + vec2(5.2,1.3)));
          float c = fbm(p*0.9 + q*1.7);
          float cov = smoothstep(0.50, 0.74, c) * smoothstep(0.0, 0.07, e) * (1.0 - smoothstep(0.32, 0.85, e));
          vec2 toSun = normalize(uSun.xz);
          float c2 = fbm(p*0.9 + q*1.7 + toSun*0.35);
          float lit = clamp(0.55 + (c - c2) * 4.0, 0.0, 1.0);
          vec3 shadowC = mix(lin(vec3(0.46,0.42,0.52)), lin(vec3(0.62,0.50,0.52)), pow(sd*0.5+0.5, 2.0));
          vec3 litC = mix(lin(vec3(1.0,0.86,0.72)), lin(vec3(1.0,0.66,0.40)), pow(sd*0.5+0.5, 3.0));
          vec3 cl = mix(shadowC, litC, lit);
          cl += lin(vec3(1.0,0.72,0.42)) * pow(sd, 10.0) * 1.6 * (1.0 - smoothstep(0.55,0.85,c));
          col = mix(col, cl, cov * 0.92);
          float ci = smoothstep(0.62, 0.9, fbm(vec2(p.x*0.18, p.y*1.6) + 3.0)) * smoothstep(0.05, 0.3, e) * 0.35;
          col = mix(col, mix(lin(vec3(0.95,0.85,0.85)), lin(vec3(1.0,0.75,0.55)), pow(sd*0.5+0.5,3.0)), ci);
        }
        col += lin(vec3(1.0,0.93,0.78)) * smoothstep(0.99955, 0.99975, sd) * 8.0;
        if (e < 0.0) col = mix(col, lin(vec3(0.72,0.62,0.52)), smoothstep(0.0, -0.06, e));
        gl_FragColor = vec4(col, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`
  });
  mat.toneMapped = true;
  const m = new THREE.Mesh(new THREE.SphereGeometry(3000, 48, 24), mat);
  m.frustumCulled = false;
  m.renderOrder = -10;
  return m;
}

// ---------------------------------------------------------------- terrain
export function buildTerrain(W, groundTex, detailTex) {
  const hd = W.height, n = hd.n;
  const g = new THREE.PlaneGeometry(hd.size, hd.size, n - 1, n - 1);
  g.rotateX(-Math.PI / 2);
  const pos = g.attributes.position;
  for (let k = 0; k < pos.count; k++) pos.setY(k, hd.data[k]);
  g.computeVertexNormals();
  const LAMB = new URLSearchParams(location.search).get('lamb') !== '0';
  const mat = LAMB ? new THREE.MeshLambertMaterial({ map: groundTex }) : new THREE.MeshStandardMaterial({ map: groundTex, roughness: 0.97, metalness: 0.0 });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uDetail = { value: detailTex };
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWP;')
      .replace('#include <project_vertex>', '#include <project_vertex>\nvWP = (modelMatrix*vec4(transformed,1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vWP; uniform sampler2D uDetail;')
      .replace('#include <map_fragment>', `#include <map_fragment>
        float d1 = texture2D(uDetail, vWP.xz*0.42).r; float d2 = texture2D(uDetail, vWP.xz*0.061).r; float d3 = texture2D(uDetail, vWP.xz*2.3).r;
        diffuseColor.rgb *= (0.80 + 0.40*d1) * (0.86 + 0.28*d2) * (0.90 + 0.20*d3);`);
  };
  const m = new THREE.Mesh(g, mat);
  m.receiveShadow = true;
  return m;
}

export function buildWater(L) {
  const P = L.pond;
  const g = new THREE.CircleGeometry(1, 72); g.rotateX(-Math.PI / 2);
  const mat = new THREE.MeshStandardMaterial({ color: 0x1d3a44, roughness: 0.06, metalness: 0.0, envMapIntensity: 1.6 });
  const m = new THREE.Mesh(g, mat);
  m.scale.set(P.rx, 1, P.rz); m.position.set(P.cx, 0.05, P.cz);
  m.receiveShadow = true;
  return m;
}

// ---------------------------------------------------------------- trees
export function buildTrees(W) {
  const R = rng(99);
  const trunkG = new THREE.CylinderGeometry(0.16, 0.26, 1, 6); trunkG.translate(0, 0.5, 0);
  const roundG = new THREE.IcosahedronGeometry(1, 1);
  const pa = new THREE.ConeGeometry(1, 1, 7); pa.translate(0, 0.5, 0);
  const pineParts = [];
  [[0.18, 0.46, 0.95], [0.40, 0.40, 0.72], [0.60, 0.40, 0.48]].forEach(([y0, h, r]) => { const c = pa.clone(); c.scale(r, h, r); c.translate(0, y0, 0); pineParts.push(c); });
  const pineG = mergeGeometries(pineParts);
  const LAMB = new URLSearchParams(location.search).get('lamb') !== '0';
  const trunkM = LAMB ? new THREE.MeshLambertMaterial({ color: 0x5a4330, flatShading: true }) : new THREE.MeshStandardMaterial({ color: 0x5a4330, roughness: 0.95, flatShading: true });
  const leafM = LAMB ? new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true }) : new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.92, flatShading: true });
  const T = W.trees;
  const autumn = [0xc9762b, 0xd99b2f, 0xb24a2a, 0xe0b54a, 0xa8572b, 0xcf8a3a].map(c => new THREE.Color(c));
  const greens = [0x5a7a2e, 0x4c6b2a, 0x6b7f33, 0x3f5f27].map(c => new THREE.Color(c));
  const pinesC = [0x2c4a2a, 0x24402a, 0x335331, 0x2a4636].map(c => new THREE.Color(c));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  const TILE = 160, tiles = new Map();
  T.forEach(t => { const k = Math.floor((t[0] + 800) / TILE) + ',' + Math.floor((t[2] + 800) / TILE); if (!tiles.has(k)) tiles.set(k, []); tiles.get(k).push(t); });
  const G = new THREE.Group();
  tiles.forEach(list => {
    const nR = list.filter(t => t[3] === 'round').length, nP = list.length - nR;
    const trunks = new THREE.InstancedMesh(trunkG, trunkM, list.length);
    const rounds = nR ? new THREE.InstancedMesh(roundG, leafM, nR) : null;
    const pines = nP ? new THREE.InstancedMesh(pineG, leafM, nP) : null;
    let ir = 0, ip = 0;
    list.forEach(([x, y, z, kind, h, au, seed], k) => {
      const rr = rng(seed + 11);
      q.setFromAxisAngle(up, rr() * Math.PI * 2);
      const tw = kind === 'pine' ? 0.9 : 1.0;
      p.set(x, y - 0.2, z); s.set(tw * (0.8 + 0.4 * rr()), kind === 'pine' ? h * 0.3 : h * 0.5, tw * (0.8 + 0.4 * rr()));
      m4.compose(p, q, s); trunks.setMatrixAt(k, m4);
      if (kind === 'pine') {
        p.set(x, y, z); s.set(h * 0.32 * (0.85 + 0.3 * rr()), h, h * 0.32 * (0.85 + 0.3 * rr()));
        m4.compose(p, q, s); pines.setMatrixAt(ip, m4);
        const c = pinesC[Math.floor(rr() * pinesC.length)].clone().multiplyScalar(0.85 + 0.3 * rr()); pines.setColorAt(ip++, c);
      } else {
        const cr = h * (0.30 + 0.06 * rr());
        p.set(x, y + h * 0.6, z); s.set(cr * (0.9 + 0.25 * rr()), cr * (1.0 + 0.2 * rr()), cr * (0.9 + 0.25 * rr()));
        m4.compose(p, q, s); rounds.setMatrixAt(ir, m4);
        const pal = au ? autumn : greens;
        const c = pal[Math.floor(rr() * pal.length)].clone().multiplyScalar(0.85 + 0.3 * rr()); rounds.setColorAt(ir++, c);
      }
    });
    [trunks, rounds, pines].filter(Boolean).forEach(m => { m.castShadow = true; m.receiveShadow = true; m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; m.computeBoundingSphere(); m.computeBoundingBox && m.computeBoundingBox(); G.add(m); });
  });
  return G;
}


// ---------------------------------------------------------------- props
export function buildProps(W, H) {
  const L = W.layout, G = new THREE.Group(), PT = propTextures();
  const std = (c, r = 0.85, extra = {}) => new THREE.MeshStandardMaterial(Object.assign({ color: c, roughness: r }, extra));
  const sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };

  // barn
  const B = L.barn, barn = new THREE.Group();
  PT.plank.repeat.set(2.5, 1); const body = sh(new THREE.Mesh(new THREE.BoxGeometry(B.w, 4.2, B.d), new THREE.MeshStandardMaterial({ map: PT.plank, roughness: 0.92 })));
  body.position.y = 2.1; barn.add(body);
  const roofShape = new THREE.Shape(); roofShape.moveTo(-B.d / 2 - 0.6, 0); roofShape.lineTo(0, 2.6); roofShape.lineTo(B.d / 2 + 0.6, 0); roofShape.lineTo(-B.d / 2 - 0.6, 0);
  const roofG = new THREE.ExtrudeGeometry(roofShape, { depth: B.w + 1.0, bevelEnabled: false }); roofG.translate(0, 0, -(B.w + 1.0) / 2); roofG.rotateY(Math.PI / 2);
  PT.roof.repeat.set(0.35, 0.35); const roof = sh(new THREE.Mesh(roofG, new THREE.MeshStandardMaterial({ map: PT.roof, roughness: 0.55, metalness: 0.4 }))); roof.position.y = 4.2; barn.add(roof);
  const gableG = new THREE.ShapeGeometry((() => { const s = new THREE.Shape(); s.moveTo(-B.d / 2, 0); s.lineTo(0, 2.3); s.lineTo(B.d / 2, 0); s.lineTo(-B.d / 2, 0); return s; })());
  [-1, 1].forEach(sg => { const gm = sh(new THREE.Mesh(gableG, std(0x8f2b21, 0.9, { side: THREE.DoubleSide }))); gm.rotation.y = Math.PI / 2; gm.position.set(sg * B.w / 2, 4.2, 0); barn.add(gm); });
  const door = sh(new THREE.Mesh(new THREE.BoxGeometry(0.1, 3.2, 3.6), std(0x6e2119, 0.9))); door.position.set(B.w / 2 + 0.05, 1.6, 0); barn.add(door);
  const trimM = std(0xf0ebe0, 0.8);
  [[0, 1.6, 1.8, 0.12, 3.2, 0.12], [0, 1.6, -1.8, 0.12, 3.2, 0.12], [0, 3.2, 0, 0.12, 0.12, 3.7]].forEach(([x, y, z, a, b, c]) => { const t = new THREE.Mesh(new THREE.BoxGeometry(a, b, c), trimM); t.position.set(B.w / 2 + 0.12 + x, y, z); barn.add(t); });
  const xb = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.14, 4.6), trimM); xb.position.set(B.w / 2 + 0.12, 1.6, 0); xb.rotation.x = Math.atan2(3.0, 3.4); barn.add(xb);
  const xb2 = xb.clone(); xb2.rotation.x = -xb.rotation.x; barn.add(xb2);
  barn.position.set(B.x, H(B.x, B.z), B.z); barn.rotation.y = B.rot; G.add(barn);

  // hay bales
  const hayG = new THREE.CylinderGeometry(0.75, 0.75, 1.2, 14); hayG.rotateZ(Math.PI / 2);
  PT.straw.repeat.set(2, 1); const hayM = new THREE.MeshStandardMaterial({ map: PT.straw, roughness: 0.95 });
  L.hay.forEach(([x, z], i) => { const h = sh(new THREE.Mesh(hayG, hayM)); h.position.set(x, 0.75, z); h.rotation.y = i * 1.3; G.add(h); });

  // fence
  const F = L.fence, postG = new THREE.BoxGeometry(0.12, 1.25, 0.12); postG.translate(0, 0.62, 0);
  const nPost = Math.floor((F.z1 - F.z0) / 3) + 1;
  const posts = new THREE.InstancedMesh(postG, std(0x7a6a55, 0.95), nPost);
  const m4 = new THREE.Matrix4();
  for (let i = 0; i < nPost; i++) { m4.makeTranslation(F.x, 0, F.z0 + i * 3); posts.setMatrixAt(i, m4); }
  posts.castShadow = true; G.add(posts);
  [0.55, 1.0].forEach(y => { const r = sh(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.08, F.z1 - F.z0), std(0x8a7a62, 0.95))); r.position.set(F.x, y, (F.z0 + F.z1) / 2); G.add(r); });

  // rocks
  const rockG = rockGeometry(5);
  const rocks = new THREE.InstancedMesh(rockG, new THREE.MeshStandardMaterial({ color: 0x8f897c, roughness: 0.95, bumpMap: PT.straw, bumpScale: 1.5 }), W.rocks.length);
  const q = new THREE.Quaternion(), e = new THREE.Euler(), sc = new THREE.Vector3(), ps = new THREE.Vector3();
  W.rocks.forEach(([x, z, s, seed], i) => { const r = rng(seed + 3); e.set(r() * 3, r() * 3, r() * 3); q.setFromEuler(e); sc.set(s, s * 0.55, s * 0.8); ps.set(x, s * 0.25, z); m4.compose(ps, q, sc); rocks.setMatrixAt(i, m4); });
  rocks.castShadow = true; rocks.receiveShadow = true; G.add(rocks);

  // bushes in rough patch
  G.add(buildBushesReal(W.bushes));

  // power line
  const P = L.power, poleM = std(0x5b4636, 0.9), wireM = new THREE.LineBasicMaterial({ color: 0x2a2a2a, transparent: true, opacity: 0.85 });
  const tops = [];
  for (let x = P.x0; x <= P.x1; x += P.step) {
    const y0 = H(x, P.z);
    const pole = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.17, P.h, 6), poleM)); pole.position.set(x, y0 + P.h / 2, P.z); G.add(pole);
    const arm = sh(new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, 2.4), poleM)); arm.position.set(x, y0 + P.h - 0.5, P.z); G.add(arm);
    tops.push([x, y0 + P.h - 0.4]);
  }
  [-1.05, 0, 1.05].forEach(dz => {
    for (let k = 0; k < tops.length - 1; k++) {
      const pts = []; const [xa, ya] = tops[k], [xb, yb] = tops[k + 1];
      for (let i = 0; i <= 12; i++) { const u = i / 12; pts.push(new THREE.Vector3(xa + (xb - xa) * u, ya + (yb - ya) * u - 1.3 * 4 * u * (1 - u) + (dz === 0 ? 0.35 : 0), P.z + dz)); }
      G.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), wireM));
    }
  });

  // picnic blanket + basket
  const BL = L.blanket, cnv = document.createElement('canvas'); cnv.width = cnv.height = 64; const cx = cnv.getContext('2d');
  for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) { cx.fillStyle = (i + j) % 2 ? '#c8343a' : '#f2ece2'; cx.fillRect(i * 8, j * 8, 8, 8); }
  const bt = new THREE.CanvasTexture(cnv); bt.colorSpace = THREE.SRGBColorSpace; bt.magFilter = THREE.NearestFilter;
  const blanket = new THREE.Mesh(new THREE.PlaneGeometry(BL.w, BL.d), new THREE.MeshStandardMaterial({ map: bt, roughness: 0.95 }));
  blanket.rotation.x = -Math.PI / 2; blanket.rotation.z = BL.rot; blanket.position.set(BL.x, 0.03, BL.z); blanket.receiveShadow = true; G.add(blanket);
  const basket = sh(new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.3, 0.35), std(0x8a5a2b))); basket.position.set(BL.x + 0.8, 0.18, BL.z - 0.5); G.add(basket);

  // windsock
  const WS = L.windsock, ws = new THREE.Group();
  const wpole = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.04, 3.2, 6), std(0xdedede, 0.6))); wpole.position.y = 1.6; ws.add(wpole);
  const sc2 = document.createElement('canvas'); sc2.width = 64; sc2.height = 8; const sx = sc2.getContext('2d');
  for (let i = 0; i < 5; i++) { sx.fillStyle = i % 2 ? '#f4f0ea' : '#ff6a1a'; sx.fillRect(i * 12.8, 0, 12.8, 8); }
  const st = new THREE.CanvasTexture(sc2); st.colorSpace = THREE.SRGBColorSpace;
  const sockG = new THREE.CylinderGeometry(0.12, 0.26, 1.4, 12, 1, true); sockG.rotateZ(-Math.PI / 2); sockG.translate(0.72, 0, 0);
  const sockUV = sockG.attributes.uv; for (let i = 0; i < sockUV.count; i++) { const u = sockUV.getX(i), v = sockUV.getY(i); sockUV.setXY(i, v, u); }
  const sock = sh(new THREE.Mesh(sockG, new THREE.MeshStandardMaterial({ map: st, roughness: 0.8, side: THREE.DoubleSide })));
  sock.position.y = 3.05; sock.rotation.z = -0.12; ws.add(sock);
  ws.position.set(WS.x, 0, WS.z); G.add(ws);
  G.userData.sock = sock;
  return G;
}

// ---------------------------------------------------------------- people
export function buildPerson(opts) {
  const { shirt = 0x2f6fb3, pants = 0x2b2f3a, skin = 0xc68e62, hair = 0x3a2a1f, seated = false, cap = null } = opts;
  const M = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, flatShading: true });
  const g = new THREE.Group(), sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };
  const legG = new THREE.BoxGeometry(0.13, 0.82, 0.14); legG.translate(0, -0.41, 0);
  const lh = seated ? 0.45 : 0.86;
  [-0.09, 0.09].forEach(dx => { const l = sh(new THREE.Mesh(legG, M(pants))); l.position.set(dx, lh, 0); if (seated) l.rotation.x = -Math.PI / 2 + 0.15; g.add(l); });
  const torso = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.16, 0.62, 7), M(shirt))); torso.position.y = lh + 0.31; g.add(torso);
  const head = sh(new THREE.Mesh(new THREE.IcosahedronGeometry(0.11, 1), M(skin))); head.position.y = lh + 0.75; g.add(head);
  const hairM = sh(new THREE.Mesh(new THREE.SphereGeometry(0.118, 10, 8), M(hair))); hairM.position.set(0, lh + 0.77, -0.03); hairM.scale.set(1, 0.95, 0.95); g.add(hairM);
  if (cap) { const c = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.06, 10), M(cap))); c.position.y = lh + 0.84; g.add(c); const b = sh(new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.015, 0.14), M(cap))); b.position.set(0, lh + 0.82, 0.12); g.add(b); }
  const armG = new THREE.BoxGeometry(0.09, 0.6, 0.09); armG.translate(0, -0.3, 0);
  const arms = [];
  [-0.24, 0.24].forEach(dx => { const a = sh(new THREE.Mesh(armG, M(shirt))); a.position.set(dx, lh + 0.58, 0); a.rotation.z = dx < 0 ? 0.12 : -0.12; g.add(a); arms.push(a); });
  g.userData = { head, arms, torso, lh };
  return g;
}

export function buildPeople(W) {
  const L = W.layout, G = new THREE.Group();
  const shirts = [0xd9a03a, 0x3b7bb8, 0xc0453a, 0x5b8a4a, 0xe8e2d6];
  L.people.forEach(([x, z, rot], i) => {
    const p = buildPersonReal({ shirt: shirts[i % 5], pants: [0x2b2f3a, 0x445566, 0x3a3226][i % 3], skin: [0xc68e62, 0x8d5a3b, 0xe0b08a, 0xa86f4a, 0xd49a6c][i], seated: i % 2 === 1 });
    p.position.set(x, 0, z); p.rotation.y = rot; G.add(p);
  });
  return G;
}

export function buildStation(W, screenTex) {
  const L = W.layout, G = new THREE.Group();
  const std = (c, r = 0.7) => new THREE.MeshStandardMaterial({ color: c, roughness: r, flatShading: true });
  const sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };
  // table
  const T = L.table, table = new THREE.Group();
  const top = sh(new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.035, 0.62), std(0xd8d4cc, 0.6))); top.position.y = 0.73; table.add(top);
  [[-0.5, -0.26], [0.5, -0.26], [-0.5, 0.26], [0.5, 0.26]].forEach(([x, z]) => { const l = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.72, 5), std(0x555555, 0.4))); l.position.set(x, 0.36, z); table.add(l); });
  // laptop
  const lap = new THREE.Group();
  const base = sh(new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.018, 0.24), std(0x2a2d33, 0.5))); base.position.y = 0.009; lap.add(base);
  const lid = new THREE.Group(); lid.position.set(0, 0.018, -0.12); lid.rotation.x = -0.32;
  const shell = sh(new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.23, 0.01), std(0x2a2d33, 0.5))); shell.position.set(0, 0.115, 0); lid.add(shell);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.316, 0.198), new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false }));
  scr.position.set(0, 0.117, 0.0056); lid.add(scr);
  lap.add(lid); lap.position.set(0.05, 0.75, 0.04); table.add(lap);
  const bat = sh(new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.035, 0.04), std(0xc23b2b, 0.5))); bat.position.set(-0.36, 0.765, 0.1); bat.rotation.y = 0.4; table.add(bat);
  const bat2 = bat.clone(); bat2.position.set(-0.3, 0.765, -0.05); bat2.rotation.y = -0.2; table.add(bat2);
  const tx = sh(new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.05, 0.1), std(0x30343c, 0.5))); tx.position.set(0.42, 0.77, 0.12); tx.rotation.y = -0.5; table.add(tx);
  table.position.set(T.x, 0, T.z); table.rotation.y = -1.15; G.add(table);
  // pilot with radio
  const pilot = buildPersonReal({ shirt: 0x26324a, pants: 0x3b3a36, skin: 0xc99a74, hair: 0x2b1d14, cap: 0x3d4436 });
  const { arms, lh } = pilot.userData;
  arms[0].rotation.set(-1.05, 0, 0.35); arms[1].rotation.set(-1.05, 0, -0.35);
  const radio = sh(new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.1, 0.07), std(0x1b1d22, 0.5))); radio.position.set(0, lh + 0.36, 0.36); radio.rotation.x = -0.5; pilot.add(radio);
  [-0.07, 0.07].forEach(dx => { const a = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.16, 4), std(0x111111)); a.position.set(dx, lh + 0.47, 0.32); a.rotation.x = -0.3; pilot.add(a); });
  pilot.position.set(L.pilot.x, 0, L.pilot.z); pilot.rotation.y = 2.05; G.add(pilot);
  pilot.userData.headBase = pilot.userData.head.rotation.clone();
  G.userData = { pilot, table, lap };
  return G;
}

// ---------------------------------------------------------------- grass tufts near camera spots
export function buildGrass(zones) {
  const blade = new THREE.BufferGeometry();
  const v = [], col = [];
  for (let k = 0; k < 3; k++) {
    const a = k * Math.PI / 3, c = Math.cos(a), s = Math.sin(a), w = 0.008, lean = 0.12 * (k - 1);
    v.push(-w * c, 0, -w * s, w * c, 0, w * s, lean * s, 1, lean * c);
  }
  blade.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
  blade.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, side: THREE.DoubleSide });
  const total = zones.reduce((a, z) => a + z.n, 0);
  const im = new THREE.InstancedMesh(blade, mat, total);
  const R = rng(1234), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), s = new THREE.Vector3(), p = new THREE.Vector3();
  const pal = [0x6a8a34, 0x7c9440, 0x8e9a46, 0x5d7a2e, 0xa59a50].map(c => new THREE.Color(c));
  let i = 0;
  zones.forEach(Z => {
    for (let k = 0; k < Z.n; k++) {
      let x, z, tries = 0;
      do { x = Z.x0 + R() * (Z.x1 - Z.x0); z = Z.z0 + R() * (Z.z1 - Z.z0); tries++; } while (Z.skip && Z.skip(x, z) && tries < 8);
      const h = Z.h0 + R() * (Z.h1 - Z.h0) * (Z.skip && Z.skip(x, z) ? 0.25 : 1);
      e.set((R() - 0.5) * 0.4, R() * 6.3, (R() - 0.5) * 0.4); q.setFromEuler(e);
      s.set(1 + R(), h, 1 + R()); p.set(x, 0, z); m4.compose(p, q, s); im.setMatrixAt(i, m4);
      im.setColorAt(i, pal[Math.floor(R() * pal.length)].clone().multiplyScalar(0.8 + 0.4 * R())); i++;
    }
  });
  im.instanceMatrix.needsUpdate = true; im.instanceColor.needsUpdate = true; im.computeBoundingSphere();
  im.receiveShadow = true; im.castShadow = false;
  return im;
}

// ---------------------------------------------------------------- the airplane (CG at origin, +x forward, +y up, +z right wing)
export function buildPlane() {
  const WHITE = new THREE.Color(0xf3f1ec), NAVY = new THREE.Color(0x1f2d4f), ORANGE = new THREE.Color(0xff6a1a);
  const foam = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.0, flatShading: true });
  const sh = (m) => { m.castShadow = true; m.receiveShadow = true; return m; };
  const colorize = (g, fn) => { const p = g.attributes.position, c = []; for (let i = 0; i < p.count; i++) { const col = fn(p.getX(i), p.getY(i), p.getZ(i)); c.push(col.r, col.g, col.b); } g.setAttribute('color', new THREE.Float32BufferAttribute(c, 3)); return g; };
  const G = new THREE.Group();
  // fuselage: per-face livery (navy belly, orange cheatline), then taper
  const faceColor = (geom, fn) => { const g = geom.index ? geom.toNonIndexed() : geom; const p = g.attributes.position, c = new Float32Array(p.count * 3);
    for (let i = 0; i < p.count; i += 3) { const cx = (p.getX(i) + p.getX(i + 1) + p.getX(i + 2)) / 3, cy = (p.getY(i) + p.getY(i + 1) + p.getY(i + 2)) / 3, cz = (p.getZ(i) + p.getZ(i + 1) + p.getZ(i + 2)) / 3;
      const col = fn(cx, cy, cz); for (let k = 0; k < 3; k++) { c[(i + k) * 3] = col.r; c[(i + k) * 3 + 1] = col.g; c[(i + k) * 3 + 2] = col.b; } }
    g.setAttribute('color', new THREE.BufferAttribute(c, 3)); return g; };
  let fg = new THREE.BoxGeometry(0.86, 0.11, 0.09, 12, 8, 2);
  fg.translate(-0.17, -0.02, 0);
  fg = faceColor(fg, (x, y) => (y < -0.047 ? NAVY : (y < -0.034 ? ORANGE : WHITE)));
  const fp = fg.attributes.position;
  for (let i = 0; i < fp.count; i++) {
    const x = fp.getX(i); let y = fp.getY(i), z = fp.getZ(i);
    const t = Math.min(1, Math.max(0, (-0.12 - x) / 0.48));
    const yb = -0.075 + 0.062 * t, yt = 0.035 - 0.012 * t;           // bottom rises toward the tail
    y = yb + (y + 0.075) / 0.11 * (yt - yb);
    z = z * (1 - 0.45 * t);
    if (x > 0.2) { const k = (x - 0.2) / 0.06; y = y * (1 - 0.18 * k); z = z * (1 - 0.15 * k); }
    fp.setY(i, y); fp.setZ(i, z);
  }
  fg.computeVertexNormals();
  G.add(sh(new THREE.Mesh(fg, foam)));
  // canopy / hatch accent
  const hatch = sh(new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.012, 0.075), new THREE.MeshStandardMaterial({ color: 0x24324f, roughness: 0.3, metalness: 0.1 })));
  hatch.position.set(0.15, 0.038, 0); G.add(hatch);
  // wing halves
  const wingG = (side) => {
    let g = new THREE.BoxGeometry(0.165, 0.016, 0.53, 1, 1, 24); g.translate(-0.022, 0, side * 0.265);
    g = faceColor(g, (x, y, z) => { const a = Math.abs(z); return a > 0.455 ? NAVY : (a > 0.42 && a < 0.44 ? ORANGE : WHITE); });
    g.computeVertexNormals(); return g;
  };
  const parts = {};
  ['L', 'R'].forEach((s, k) => {
    const side = s === 'R' ? 1 : -1, half = new THREE.Group();
    half.add(sh(new THREE.Mesh(wingG(side), foam)));
    const fixedG = new THREE.BoxGeometry(0.045, 0.012, 0.27); fixedG.translate(-0.1275, -0.002, side * 0.135);
    colorize(fixedG, () => WHITE); half.add(sh(new THREE.Mesh(fixedG, foam)));
    const ail = new THREE.Group(); ail.position.set(-0.105, -0.002, side * 0.395);
    let ag = new THREE.BoxGeometry(0.045, 0.011, 0.25, 1, 1, 12); ag.translate(-0.0225, 0, 0);
    ag = faceColor(ag, (x, y, z) => (Math.abs(z + side * 0.395) > 0.455 ? NAVY : (Math.abs(z + side * 0.395) > 0.42 && Math.abs(z + side * 0.395) < 0.44 ? ORANGE : WHITE))); ag.computeVertexNormals();
    ail.add(sh(new THREE.Mesh(ag, foam))); half.add(ail); parts['ail' + s] = ail;
    half.position.set(0.0, 0.046, 0); half.rotation.x = -side * 0.052; G.add(half);
  });
  // tail
  let stab = new THREE.BoxGeometry(0.08, 0.008, 0.38, 1, 1, 12); stab.translate(-0.53, 0.014, 0); stab = faceColor(stab, (x, y, z) => (Math.abs(z) > 0.15 ? NAVY : WHITE)); stab.computeVertexNormals();
  G.add(sh(new THREE.Mesh(stab, foam)));
  const ele = new THREE.Group(); ele.position.set(-0.57, 0.014, 0);
  const eg = new THREE.BoxGeometry(0.042, 0.007, 0.36); eg.translate(-0.021, 0, 0); colorize(eg, () => ORANGE);
  ele.add(sh(new THREE.Mesh(eg, foam))); G.add(ele); parts.ele = ele;
  const fin = new THREE.BoxGeometry(0.09, 0.14, 0.006); fin.translate(-0.535, 0.088, 0); colorize(fin, () => NAVY);
  G.add(sh(new THREE.Mesh(fin, foam)));
  const rud = new THREE.Group(); rud.position.set(-0.58, 0.02, 0);
  const rg = new THREE.BoxGeometry(0.042, 0.15, 0.006); rg.translate(-0.021, 0.075, 0); colorize(rg, () => ORANGE);
  rud.add(sh(new THREE.Mesh(rg, foam))); G.add(rud); parts.rud = rud;
  // gear
  const wireM = new THREE.MeshStandardMaterial({ color: 0x9a9a9a, roughness: 0.3, metalness: 0.8 });
  const tyreM = new THREE.MeshStandardMaterial({ color: 0x1c1c1c, roughness: 0.8, flatShading: true });
  const hubM = new THREE.MeshStandardMaterial({ color: 0xff6a1a, roughness: 0.5 });
  const strut = (a, b) => { const d = new THREE.Vector3().subVectors(b, a); const m = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, d.length(), 5), wireM)); m.position.copy(a).addScaledVector(d, 0.5); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.clone().normalize()); return m; };
  const wheel = (r) => { const w = new THREE.Group(); const t = sh(new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.022, 14), tyreM)); t.rotation.x = Math.PI / 2; w.add(t); const h = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.45, r * 0.45, 0.024, 10), hubM); h.rotation.x = Math.PI / 2; w.add(h); return w; };
  parts.wheels = [];
  [-1, 1].forEach(s => { G.add(strut(new THREE.Vector3(-0.04, -0.07, s * 0.035), new THREE.Vector3(-0.04, -0.14, s * 0.125))); const w = wheel(0.05); w.position.set(-0.04, -0.14, s * 0.135); G.add(w); parts.wheels.push(w); });
  G.add(strut(new THREE.Vector3(0.22, -0.06, 0), new THREE.Vector3(0.22, -0.145, 0)));
  const nw = wheel(0.045); nw.position.set(0.22, -0.145, 0); G.add(nw); parts.wheels.push(nw);
  // camera pod + GPS
  const pod = sh(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.03, 0.042), new THREE.MeshStandardMaterial({ color: 0x15171b, roughness: 0.4 })));
  pod.position.set(0.0, -0.088, 0); G.add(pod);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.009, 0.009, 0.006, 16), new THREE.MeshStandardMaterial({ color: 0x0a0d12, roughness: 0.05, metalness: 0.6 }));
  lens.position.set(0.0, -0.105, 0); G.add(lens);
  const gps = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.024, 0.024, 0.011, 16), new THREE.MeshStandardMaterial({ color: 0x2b2e33, roughness: 0.5 })));
  gps.position.set(-0.03, 0.061, 0); G.add(gps);
  // motor, spinner, prop
  const motor = sh(new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.03, 12), new THREE.MeshStandardMaterial({ color: 0x3a3a3a, roughness: 0.3, metalness: 0.7 })));
  motor.rotation.z = Math.PI / 2; motor.position.set(0.272, -0.012, 0); G.add(motor);
  const prop = new THREE.Group(); prop.position.set(0.30, -0.012, 0);
  const spin = sh(new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.04, 14), new THREE.MeshStandardMaterial({ color: 0xff6a1a, roughness: 0.4 })));
  spin.rotation.z = -Math.PI / 2; spin.position.x = 0.02; prop.add(spin);
  const bladeM = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.4, transparent: true, opacity: 1 });
  const blades = new THREE.Group();
  [-1, 1].forEach(s => { const b = sh(new THREE.Mesh(new THREE.BoxGeometry(0.005, 0.105, 0.018), bladeM)); b.position.y = s * 0.058; b.rotation.y = s * 0.28; blades.add(b); });
  prop.add(blades);
  const dc = document.createElement('canvas'); dc.width = dc.height = 128; const dx = dc.getContext('2d');
  const gr = dx.createRadialGradient(64, 64, 6, 64, 64, 64); gr.addColorStop(0, 'rgba(30,30,30,0.0)'); gr.addColorStop(0.25, 'rgba(30,30,30,0.35)'); gr.addColorStop(0.85, 'rgba(40,40,40,0.28)'); gr.addColorStop(0.97, 'rgba(60,60,60,0.45)'); gr.addColorStop(1, 'rgba(60,60,60,0)');
  dx.fillStyle = gr; dx.fillRect(0, 0, 128, 128);
  const disc = new THREE.Mesh(new THREE.CircleGeometry(0.118, 40), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(dc), transparent: true, depthWrite: false, side: THREE.DoubleSide, opacity: 0 }));
  disc.rotation.y = Math.PI / 2; prop.add(disc);
  G.add(prop);
  Object.assign(parts, { prop, blades, bladeM, disc });
  G.userData = parts;
  return G;
}
