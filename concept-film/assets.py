"""World layout, ground texture, heightmap, trees, class map and scan-time map for the Cloudbreak film.
Frame: x east, y up, z south (three.js). Outputs into web/."""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # outputs go to web/ next to this script
import json, math
import numpy as np
from PIL import Image
from scipy.ndimage import zoom, gaussian_filter, binary_dilation

rng = np.random.default_rng(7)
mission = json.load(open('web/mission.json'))

# ---------------- layout ----------------
L = dict(
    meadow=dict(xmin=-215, xmax=255, zmin=-178, zmax=116),
    takeoff=dict(x0=-62, x1=42, z=70, w=8),
    hayfield=dict(x0=-62, x1=62, z0=-76, z1=-26),
    pond=dict(cx=55, cz=10, rx=30, rz=18),
    rough=dict(cx=115, cz=42, r=26),
    barn=dict(x=-120, z=-75, w=14, d=10, h=6.0, rot=0.18),
    hay=[[-106, -64], [-103, -69], [-109, -84], [-131, -62]],
    fence=dict(x=-100, z0=-112, z1=12),
    people=[[-72, -2, 0.3], [-69.2, 1.2, 2.4], [-73.6, 2.6, 1.2], [-66.4, -1.0, 3.6], [-70.4, 4.6, 5.0]],
    blanket=dict(x=-70.5, z=1.2, w=4.0, d=3.0, rot=0.3),
    pilot=dict(x=-66.0, z=86.0),
    table=dict(x=-64.6, z=84.9),
    windsock=dict(x=-57.0, z=89.0),
    rocks=dict(cx=122, cz=-25, r=9, n=11),
    power=dict(z=-196, x0=-520, x1=520, step=52, h=9.5),
    lone_trees=[[132, -86, 'pine', 12], [30, -126, 'round', 9.5], [-150, 64, 'round', 10],
                [-96, 46, 'pine', 10], [172, 88, 'round', 11], [-185, -40, 'pine', 13]],
    candidates=[
        dict(id=1, x0=-40, x1=40, z=-50, w=10, verdict='ok'),
        dict(id=2, x0=18, x1=92, z=10, w=10, verdict='water'),
        dict(id=3, x0=-112, x1=-40, z=0, w=10, verdict='people'),
        dict(id=4, x0=80, x1=150, z=42, w=10, verdict='unknown'),
    ],
    sun=dict(azimuth_deg=-62, elevation_deg=11.5),   # azimuth from +x toward -z (north) ... see film.js
    tex=dict(x0=-800, z0=-800, size=1600, px=4096),
    grid=dict(x0=-200, z0=-160, nx=110, nz=68, cell=4.0),
)

# ---------------- noise helpers ----------------
def fbm(shape, octaves, base, seed, persistence=0.5):
    r = np.random.default_rng(seed)
    out = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * (2 ** o)
        g = r.random((n + 3, n + 3)).astype(np.float32)
        up = zoom(g, (shape[0] / n, shape[1] / n), order=3)[:shape[0], :shape[1]]
        out += amp * up; tot += amp; amp *= persistence
    out /= tot
    return (out - out.min()) / (out.max() - out.min() + 1e-9)

def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)

M = L['meadow']
def sd_rect(x, z):
    cx, cz = (M['xmin'] + M['xmax']) / 2, (M['zmin'] + M['zmax']) / 2
    hx, hz = (M['xmax'] - M['xmin']) / 2, (M['zmax'] - M['zmin']) / 2
    qx, qz = np.abs(x - cx) - hx, np.abs(z - cz) - hz
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qz, 0))
    inside = np.minimum(np.maximum(qx, qz), 0)
    return outside + inside

# wobble field for meadow edge (sampled on a coarse grid, interpolated)
WOB = fbm((257, 257), 4, 6, seed=11)
def wobble(x, z):
    u = np.clip((np.asarray(x) + 800) / 1600 * 256, 0, 256); v = np.clip((np.asarray(z) + 800) / 1600 * 256, 0, 256)
    i0, j0 = np.floor(v).astype(int).clip(0, 255), np.floor(u).astype(int).clip(0, 255)
    fv, fu = v - i0, u - j0
    a = WOB[i0, j0] * (1 - fu) + WOB[i0, j0 + 1] * fu
    b = WOB[i0 + 1, j0] * (1 - fu) + WOB[i0 + 1, j0 + 1] * fu
    return (a * (1 - fv) + b * fv) * 22 - 11

def meadow_sd(x, z):
    return sd_rect(x, z) + wobble(x, z)

HILL = fbm((257, 257), 5, 3, seed=5)
def height(x, z):
    sd = np.maximum(meadow_sd(x, z), 0)
    u = np.clip((np.asarray(x) + 800) / 1600 * 256, 0, 255.999); v = np.clip((np.asarray(z) + 800) / 1600 * 256, 0, 255.999)
    i0, j0 = np.floor(v).astype(int), np.floor(u).astype(int)
    fv, fu = v - i0, u - j0
    a = HILL[i0, j0] * (1 - fu) + HILL[i0, j0 + 1] * fu
    b = HILL[i0 + 1, j0] * (1 - fu) + HILL[i0 + 1, j0 + 1] * fu
    hn = a * (1 - fv) + b * fv
    return smoothstep(10, 220, sd) * (6 + 70 * hn ** 1.6) + smoothstep(0, 40, sd) * 1.5

# heightmap for terrain mesh: 241 x 241 over 1600 m
NH = 241
gx = np.linspace(-800, 800, NH)
GX, GZ = np.meshgrid(gx, gx)
HM = height(GX, GZ).astype(np.float32)

# ---------------- trees ----------------
trees = []
def add_tree(x, z, kind, h, autumn=None):
    if autumn is None:
        autumn = kind == 'round' and rng.random() < 0.55
    y = float(height(np.array([x]), np.array([z]))[0])
    trees.append([round(x, 2), round(y, 2), round(z, 2), kind, round(h, 2), 1 if autumn else 0, int(rng.integers(0, 1000))])

for step, band in ((11.0, (3, 140)), (21.0, (140, 900))):
    xs = np.arange(-790, 790, step); zs = np.arange(-790, 790, step)
    X, Z = np.meshgrid(xs, zs)
    X = X + rng.uniform(-step * 0.45, step * 0.45, X.shape); Z = Z + rng.uniform(-step * 0.45, step * 0.45, Z.shape)
    sd = meadow_sd(X, Z)
    sel = (sd > band[0]) & (sd <= band[1]) & (np.hypot(X, Z) < 790)
    p = 0.9 if band[0] < 50 else 0.62
    for x, z in zip(X[sel], Z[sel]):
        if rng.random() > p: continue
        if abs(z - L['power']['z']) < 10: continue
        kind = 'pine' if rng.random() < 0.38 else 'round'
        h = rng.uniform(9, 17) if kind == 'pine' else rng.uniform(7.5, 13)
        add_tree(float(x), float(z), kind, float(h))
for x, z, kind, h in L['lone_trees']:
    add_tree(x, z, kind, h, autumn=(kind == 'round'))
print('trees', len(trees))

# bushes in the rough patch
R = L['rough']
bushes = []
for i in range(70):
    a = rng.uniform(0, 2 * math.pi); r = R['r'] * math.sqrt(rng.uniform(0, 1)) * 0.95
    bushes.append([round(R['cx'] + r * math.cos(a), 2), round(R['cz'] + r * math.sin(a) * 0.8, 2), round(rng.uniform(0.6, 1.6), 2), int(rng.integers(0, 1000))])

# rocks
Rk = L['rocks']
rocks = []
for i in range(Rk['n']):
    a = rng.uniform(0, 2 * math.pi); r = Rk['r'] * math.sqrt(rng.uniform(0, 1))
    rocks.append([round(Rk['cx'] + r * math.cos(a), 2), round(Rk['cz'] + r * math.sin(a), 2), round(rng.uniform(0.5, 1.6), 2), int(rng.integers(0, 1000))])

# ---------------- ground texture ----------------
TX = L['tex']; N = TX['px']; mpp = TX['size'] / N
cols = (np.arange(N) + 0.5) * mpp + TX['x0']
rows = (np.arange(N) + 0.5) * mpp + TX['z0']
XX, ZZ = np.meshgrid(cols.astype(np.float32), rows.astype(np.float32))

n1 = fbm((N, N), 6, 8, seed=1)
n2 = fbm((N, N), 5, 40, seed=2)
n3 = fbm((N, N), 4, 160, seed=3)
sdm = meadow_sd(XX, ZZ).astype(np.float32)

def mix(a, b, t):
    t = t[..., None]
    return a * (1 - t) + b * t

grass_a = np.array([0.33, 0.47, 0.17], np.float32)
grass_b = np.array([0.50, 0.55, 0.22], np.float32)   # yellowed late-season
grass_c = np.array([0.24, 0.38, 0.14], np.float32)
img = mix(np.broadcast_to(grass_a, (N, N, 3)), grass_b, smoothstep(0.45, 0.8, n1))
img = mix(img, grass_c, smoothstep(0.5, 0.85, n2) * 0.6)
img = img * (0.88 + 0.24 * n3[..., None])

# forest floor / hills
forest = np.array([0.20, 0.25, 0.12], np.float32)
img = mix(img, forest * (0.85 + 0.3 * n2[..., None]), smoothstep(-2, 12, sdm))

# hay field (cut meadow with windrow lines along x)
H = L['hayfield']
hf = smoothstep(4, 0, np.maximum.reduce([H['x0'] - XX, XX - H['x1'], H['z0'] - ZZ, ZZ - H['z1']]))
hay_col = np.array([0.52, 0.56, 0.25], np.float32)
rows_pat = 0.5 + 0.5 * np.sin(ZZ / 2.2 * math.pi)
hay = hay_col * (0.92 + 0.12 * rows_pat[..., None]) * (0.95 + 0.1 * n2[..., None])
img = mix(img, hay, hf * 0.9)

# mowed takeoff strip with stripes along x
T = L['takeoff']
ts = smoothstep(1.2, 0, np.maximum.reduce([T['x0'] - XX, XX - T['x1'], np.abs(ZZ - T['z']) - T['w'] / 2]))
stripe = (np.floor((ZZ - T['z'] + T['w'] / 2) / 2.0) % 2).astype(np.float32)
mow = np.array([0.42, 0.58, 0.22], np.float32) * (0.93 + 0.12 * stripe[..., None])
img = mix(img, mow, ts)

# dirt track: from south edge to pilot station, then curving north-west toward the barn
track = [(-70, 140), (-68, 112), (-70, 96), (-78, 80), (-92, 55), (-106, 25), (-112, -10), (-116, -40), (-119, -62)]
tk = np.full((N, N), 1e9, np.float32)
for (ax, az), (bx, bz) in zip(track[:-1], track[1:]):
    vx, vz = bx - ax, bz - az; l2 = vx * vx + vz * vz
    t = np.clip(((XX - ax) * vx + (ZZ - az) * vz) / l2, 0, 1)
    d = np.hypot(XX - (ax + t * vx), ZZ - (az + t * vz))
    tk = np.minimum(tk, d)
dirt = np.array([0.47, 0.39, 0.27], np.float32) * (0.9 + 0.2 * n2[..., None])
img = mix(img, dirt, smoothstep(1.6, 0.6, tk) * 0.85)
img = mix(img, dirt * 0.9, smoothstep(1.8, 1.2, np.abs(tk - 0.0)) * 0.0)

# rough patch: darker mottled
rp = smoothstep(L['rough']['r'] + 4, L['rough']['r'] - 6, np.hypot(XX - R['cx'], (ZZ - R['cz']) / 0.8))
rough = np.array([0.25, 0.33, 0.13], np.float32) * (0.7 + 0.6 * n2[..., None])
img = mix(img, rough, rp)

# pond shore
P = L['pond']
pe = np.hypot((XX - P['cx']) / P['rx'], (ZZ - P['cz']) / P['rz'])
shore = np.array([0.45, 0.40, 0.28], np.float32)
img = mix(img, shore, smoothstep(1.18, 1.02, pe) * 0.9)
img = mix(img, np.array([0.18, 0.22, 0.16], np.float32), smoothstep(1.03, 0.95, pe))

# around barn: trampled dirt
B = L['barn']
bd = np.hypot(XX - B['x'], ZZ - B['z'])
img = mix(img, dirt * 0.95, smoothstep(14, 7, bd) * 0.7)
# pilot pad
pd = np.hypot(XX - L['pilot']['x'], ZZ - L['pilot']['z'])
img = mix(img, mow * 0.95, smoothstep(7, 3, pd) * 0.6)

img = np.clip(img, 0, 1)
Image.fromarray((img ** (1 / 1.0) * 255).astype(np.uint8)).save('web/ground.jpg', quality=90)
print('ground texture saved')

# tileable detail noise 512^2 (FFT-filtered)
def tile_noise(n, f0, seed):
    r = np.random.default_rng(seed)
    w = r.normal(size=(n, n))
    F = np.fft.fft2(w)
    ky = np.fft.fftfreq(n)[:, None]; kx = np.fft.fftfreq(n)[None, :]
    k = np.hypot(kx, ky) + 1e-6
    F *= (1 / k ** 1.2) * np.exp(-(k / f0) ** 2)
    out = np.real(np.fft.ifft2(F))
    return (out - out.min()) / (out.max() - out.min())
dn = 0.6 * tile_noise(512, 0.25, 21) + 0.4 * tile_noise(512, 0.06, 22)
Image.fromarray((dn * 255).astype(np.uint8)).save('web/detail.png')

# ---------------- class map + scan times ----------------
Gd = L['grid']
cx = Gd['x0'] + (np.arange(Gd['nx']) + 0.5) * Gd['cell']
cz = Gd['z0'] + (np.arange(Gd['nz']) + 0.5) * Gd['cell']
CX, CZ = np.meshgrid(cx, cz)          # shape (nz, nx)
cls = np.ones_like(CX, dtype=np.int32)          # 1 usable
def mark(mask, c, dil=0):
    global cls
    if dil: mask = binary_dilation(mask, iterations=dil)
    cls = np.where(mask, c, cls)

# outside meadow / forest edge -> obstacle
mark(meadow_sd(CX, CZ) > -6, 2)
# rough -> unknown
mark(np.hypot(CX - R['cx'], (CZ - R['cz']) / 0.8) < R['r'] + 2, 5)
# water
mark(np.hypot((CX - P['cx']) / (P['rx'] + 3), (CZ - P['cz']) / (P['rz'] + 3)) < 1, 4, dil=1)
# obstacles: barn, hay, fence, trees, rocks
mark(np.hypot(CX - B['x'], CZ - B['z']) < 10, 2, dil=1)
for hx, hz in L['hay']: mark(np.hypot(CX - hx, CZ - hz) < 2.5, 2)
F_ = L['fence']; mark((np.abs(CX - F_['x']) < 2.2) & (CZ > F_['z0']) & (CZ < F_['z1']), 2)
for x, y, z, kind, h, au, sd in trees:
    if -205 < x < 245 and -165 < z < 115: mark(np.hypot(CX - x, CZ - z) < 5.5, 2)
for x, z, s, sd in rocks: mark(np.hypot(CX - x, CZ - z) < 2.5 + s, 2)
# people (+ pilot station)
for x, z, r in L['people']: mark(np.hypot(CX - x, CZ - z) < 3, 3, dil=1)
mark(np.hypot(CX - L['pilot']['x'], CZ - L['pilot']['z']) < 4.5, 3, dil=1)

# scan time: first time the camera footprint (30 m along x 52 m across) covers the cell during survey
ev = mission['events']
t0, fps = mission['t0'], mission['fps']
mx, my, mz, mh = (np.array(mission[k]) for k in ('x', 'y', 'z', 'h'))
tt = t0 + np.arange(len(mx)) / fps
scan = np.full(CX.shape, 9999.0)
sel = np.where((tt >= ev['survey_start'] - 3) & (tt <= ev['survey_end'] + 2) & (my > 30))[0][::3]
fx, fy = CX.ravel(), CZ.ravel()
flat = scan.ravel()
for i in sel:
    dx, dz = fx - mx[i], fy - mz[i]
    c, s = math.cos(mh[i]), math.sin(mh[i])
    along = dx * c + dz * s; cross = -dx * s + dz * c
    hit = (np.abs(along) < 15) & (np.abs(cross) < 26) & (flat > 9000)
    flat[hit] = tt[i]
scan = flat.reshape(CX.shape)
cls = np.where((scan > 9000) & (cls == 1), 5, cls)       # never imaged -> unknown
jit = rng.random(CX.shape)
print('class counts', {int(k): int(v) for k, v in zip(*np.unique(cls, return_counts=True))})

grid = dict(cls=cls.ravel().tolist(), scan=[round(float(v), 2) for v in scan.ravel()], jit=[round(float(v), 3) for v in jit.ravel()])
out = dict(layout=L, trees=trees, bushes=bushes, rocks=rocks,
           height=dict(n=NH, size=1600, data=[round(float(v), 2) for v in HM.ravel()]), grid=grid)
json.dump(out, open('web/world.json', 'w'), separators=(',', ':'))
print('world.json written')

# quick check image of classes
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
fig, ax = plt.subplots(1, 2, figsize=(16, 5))
cm = ListedColormap(['black', '#3ddc84', '#ff4d4d', '#ffa63d', '#3da5ff', '#9aa0a6'])
ax[0].imshow(cls, cmap=cm, vmin=0, vmax=5, extent=[cx[0], cx[-1], cz[-1], cz[0]])
for c in L['candidates']:
    ax[0].add_patch(plt.Rectangle((c['x0'], c['z'] - c['w'] / 2), c['x1'] - c['x0'], c['w'], fill=False, ec='white'))
ax[0].plot(mx[::20], mz[::20], 'w-', lw=0.5)
ax[0].set_title('classes (z down = south)')
ax[1].imshow(np.where(scan > 9000, np.nan, scan), extent=[cx[0], cx[-1], cz[-1], cz[0]]); ax[1].set_title('scan time')
plt.tight_layout(); plt.savefig('class_check.png', dpi=70)
small = Image.open('web/ground.jpg').crop((1500, 1550, 2700, 2300)).resize((1200, 750)); small.save('ground_check.jpg')
