"""Synthesize the soundtrack (ambient score + plane + foley + UI) from out/cues.json + out/meta.json.
Writes out/audio.wav (48 kHz stereo). Length = film duration + TAIL seconds."""
import json, os, numpy as np
from scipy.signal import lfilter, fftconvolve, butter, sosfilt

SR = 48000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
TAIL = 8.6   # 8.0 s end-credits card + 0.6 s black
rng = np.random.default_rng(7)

meta = json.load(open(f'{OUT}/meta.json'))
cues = json.load(open(f'{OUT}/cues.json'))
DUR = sum(s['dur'] for s in meta['shots'])
N = int((DUR + TAIL) * SR)
t = np.arange(N) / SR
EV = {}
for ft, name in meta['events']:
    EV.setdefault(name, []).append(ft)

# ---------------------------------------------------------------- cue curves at audio rate
cf = np.array([c['ft'] for c in cues])
def curve(key, fill=None):
    v = np.array([float(c[key]) for c in cues])
    return np.interp(t, cf, v, right=v[-1] if fill is None else fill)
rpm, thr, vel, dist, alt = curve('rpm'), curve('thr'), curve('v'), curve('dist'), curve('y')
belly = curve('belly') > 0.5
ui = curve('ui') > 0.5
shot_at = lambda ft: next((s['id'] for s in meta['shots'] if ft < s['start'] + s['dur']), meta['shots'][-1]['id'])

def smooth(x, ms):
    n = max(1, int(SR * ms / 1000)); k = np.ones(n) / n
    return np.convolve(np.pad(x, (n, n), mode='edge'), k, mode='same')[n:-n]

def onepole_tv(x, fc, block=512):
    """time-varying one-pole lowpass; fc array (Hz) per sample"""
    y = np.empty_like(x); z = np.zeros(1)
    for i in range(0, len(x), block):
        f = float(np.mean(fc[i:i + block])); a = 1 - np.exp(-2 * np.pi * f / SR)
        y[i:i + block], z = lfilter([a], [1, a - 1], x[i:i + block], zi=z)
    return y

def env_ad(n, a, d):
    """attack (s) then exp decay time-constant d (s)"""
    tt = np.arange(n) / SR
    return np.minimum(1, tt / max(a, 1e-4)) * np.exp(-np.maximum(0, tt - a) / d)

def place(buf, x, at, gain=1.0, pan=0.0):
    i = int(at * SR)
    if i >= buf.shape[1] or i + len(x) <= 0: return
    j = min(buf.shape[1], i + len(x)); s = max(0, -i)
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, max(i, 0):j] += x[s:j - i] * gain * l * 1.414
    buf[1, max(i, 0):j] += x[s:j - i] * gain * r * 1.414

def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], btype='band', fs=SR, output='sos'), x)
def lp(x, f, order=2):
    return sosfilt(butter(order, f, btype='low', fs=SR, output='sos'), x)
def hp(x, f, order=2):
    return sosfilt(butter(order, f, btype='high', fs=SR, output='sos'), x)

def reverb_ir(sec=3.2, t60=2.6, seed=3):
    r = np.random.default_rng(seed); n = int(sec * SR); tt = np.arange(n) / SR
    ir = np.zeros((2, n))
    for ch in range(2):
        nz = r.standard_normal(n) * np.exp(-6.91 * tt / t60)
        nz = lp(nz, 6000) * 0.6 + lp(nz, 1800) * 0.4
        ir[ch] = nz
    for k in range(12):  # early reflections
        d = int(r.uniform(0.008, 0.07) * SR); ir[k % 2, d] += r.uniform(0.2, 0.5)
    ir[:, :int(0.004 * SR)] = 0
    return ir / np.sqrt((ir ** 2).sum(axis=1, keepdims=True)) * 0.9

IR = reverb_ir()
def verb(st, wet):
    out = np.zeros_like(st)
    for ch in range(2):
        out[ch] = fftconvolve(st[ch], IR[ch])[:st.shape[1]]
    return st * (1 - wet * 0.3) + out * wet

midi = lambda m: 440.0 * 2 ** ((m - 69) / 12)

# ================================================================= SCORE
score = np.zeros((2, N))
CH = [  # start, end, notes, level, brightness
    (0.0, 8.6, [50, 57, 64, 66, 69], 0.55, 0.35),
    (8.0, 12.6, [47, 54, 61, 62, 66], 0.55, 0.38),
    (12.0, 18.6, [43, 55, 62, 66, 69], 0.65, 0.42),
    (18.0, 24.6, [45, 57, 62, 64, 69], 0.7, 0.45),
    (24.0, 31.8, [50, 57, 62, 66, 69, 74], 0.8, 0.5),
    (31.0, 38.6, [52, 59, 62, 66, 71], 0.62, 0.42),
    (38.0, 44.6, [48, 55, 64, 67, 71], 0.6, 0.42),
    (44.0, 51.1, [43, 55, 62, 67, 71], 0.62, 0.44),
    (50.5, 55.6, [42, 57, 62, 66, 69], 0.6, 0.44),
    (55.0, 60.1, [45, 57, 61, 64, 69], 0.62, 0.46),
    (59.5, 64.6, [47, 54, 62, 66, 69], 0.6, 0.42),
    (64.1, 68.6, [43, 55, 62, 66, 71], 0.66, 0.48),
    (68.0, 75.1, [52, 59, 62, 67], 0.42, 0.3),
    (74.5, 79.1, [45, 57, 62, 64], 0.45, 0.34),
    (78.7, 83.1, [50, 57, 64, 66, 69, 74], 0.75, 0.5),
    (82.5, 90.1, [47, 54, 61, 62, 66], 0.6, 0.42),
    (89.5, 97.1, [43, 55, 62, 64, 69], 0.66, 0.46),
    (96.5, 100.6, [45, 57, 62, 67, 69], 0.72, 0.5),
    (100.0, 106.5, [45, 57, 61, 64, 69, 73], 0.82, 0.56),
    (106.2, 116.1, [38, 50, 57, 64, 66, 69, 73], 0.95, 0.5),
    (115.5, 120.9, [50, 55, 62, 66, 71], 0.7, 0.42),
    (120.3, DUR + TAIL, [38, 50, 57, 64, 66, 69, 76], 0.8, 0.45),
]
def pad_note(m, n, bright, seed):
    r = np.random.default_rng(seed); tt = np.arange(n) / SR; f0 = midi(m); out = np.zeros((2, n))
    for vi, det in enumerate((-7, 0, 6)):
        f = f0 * 2 ** (det / 1200) * (1 + 0.0025 * np.sin(2 * np.pi * (0.17 + 0.05 * vi) * tt + r.uniform(0, 6)))
        ph = 2 * np.pi * np.cumsum(f) / SR + r.uniform(0, 6)
        sig = np.zeros(n)
        for k in range(1, 8):
            if f0 * k > 9000: break
            sig += np.sin(k * ph) * (bright ** (k - 1)) / k
        pan = (-0.6, 0.0, 0.6)[vi]
        out[0] += sig * np.cos((pan + 1) * np.pi / 4); out[1] += sig * np.sin((pan + 1) * np.pi / 4)
    return out / 3
for ci, (a, b, notes, lvl, br) in enumerate(CH):
    rel = 2.2; n = int((b - a + rel) * SR); tt = np.arange(n) / SR
    env = np.minimum(1, tt / 1.6) * np.clip(((b - a + rel) - tt) / rel, 0, 1) ** 1.5
    env *= 1 + 0.08 * np.sin(2 * np.pi * 0.11 * tt)
    for ni, m in enumerate(notes):
        g = lvl * (0.9 if m >= 50 else 0.6) / np.sqrt(len(notes))
        x = pad_note(m, n, br, ci * 31 + ni) * env * g
        i = int(a * SR); j = min(N, i + n); score[:, i:j] += x[:, :j - i]
# sub bass
for (a, b, notes, lvl, br) in CH:
    root = min(notes)
    while root > 43: root -= 12
    n = int((b - a + 1.5) * SR); tt = np.arange(n) / SR
    env = np.minimum(1, tt / 1.2) * np.clip(((b - a + 1.5) - tt) / 1.5, 0, 1)
    x = (np.sin(2 * np.pi * midi(root) * tt) + 0.25 * np.sin(4 * np.pi * midi(root) * tt)) * env * 0.16 * lvl
    place(score, x, a, 1.0, 0.0)

# arpeggio plucks (with ping-pong delay)
BPM = 96.0; e8 = 60 / BPM / 2
arp = np.zeros((2, N))
def pluck(f, dur=0.6, bright=0.5):
    n = int(dur * SR); tt = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * tt) + bright * 0.5 * np.sin(4 * np.pi * f * tt) * np.exp(-tt / 0.08) + 0.2 * np.sin(6 * np.pi * f * tt) * np.exp(-tt / 0.04)
    return s * env_ad(n, 0.004, 0.22)
SECT = [(18.0, 31.0, 1, 0.10), (31.0, 50.5, 2, 0.07), (50.5, 68.0, 2, 0.085), (82.5, 96.5, 1, 0.09), (96.5, 106.0, 2, 0.12)]
for a, b, div, lvl in SECT:
    step = e8 / div; k = 0; tt0 = a
    while tt0 < b:
        ch = next((c for c in reversed(CH) if c[0] <= tt0 + 0.01), CH[0]); notes = sorted(ch[2])[1:]
        seq = notes + notes[::-1][1:-1]; m = seq[k % len(seq)] + 12
        ramp = 0.55 + 0.45 * (tt0 - a) / (b - a)
        acc = 1.0 if k % 4 == 0 else 0.7
        place(arp, pluck(midi(m), 0.5, 0.6), tt0, lvl * ramp * acc, 0.35 * np.sin(k * 1.7))
        k += 1; tt0 += step
# ping-pong delay
d = int(e8 * 1.5 * SR); dl = np.zeros_like(arp)
for rep in range(1, 5):
    g = 0.38 ** rep; ch = rep % 2; s = rep * d
    dl[ch, s:] += lp(arp[0, :-s] + arp[1, :-s], 3500) * 0.5 * g
arp = arp + dl

# soft pulse toward touchdown (low tom on half notes, crescendo), and risers
perc = np.zeros((2, N))
def tom(f=62, dur=0.7):
    n = int(dur * SR); tt = np.arange(n) / SR; fr = f * (1 + 0.6 * np.exp(-tt / 0.03))
    return np.sin(2 * np.pi * np.cumsum(fr) / SR) * env_ad(n, 0.002, 0.18)
tt0 = 96.5; k = 0
while tt0 < 105.9:
    place(perc, tom(), tt0, 0.18 + 0.32 * (tt0 - 96.5) / 9.4, 0); tt0 += e8 * 2; k += 1
def riser(dur, f0=300, f1=5000, gain=1.0, seed=1):
    n = int(dur * SR); x = np.random.default_rng(seed).standard_normal(n); tt = np.arange(n) / SR
    fc = f0 * (f1 / f0) ** (tt / dur); y = onepole_tv(x, fc, 256); y = hp(y, 200)
    return y * (tt / dur) ** 2.2 * gain
def boom(dur=4.0, f=42):
    n = int(dur * SR); tt = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * tt * (1 + 0.3 * np.exp(-tt / 0.2))) * env_ad(n, 0.005, 1.1)
    nz = lp(np.random.default_rng(9).standard_normal(n), 400) * env_ad(n, 0.002, 0.25) * 0.8
    return s + nz
place(perc, riser(3.0, gain=0.5, seed=2), 31.0 - 3.0, 1, 0)
place(perc, boom(3.5, 46), 31.0, 0.35, 0)
place(perc, riser(4.5, gain=0.6, seed=3), 106.2 - 4.5, 1, 0)
place(perc, boom(4.0, 40), 106.2, 0.45, 0)
place(perc, riser(2.0, 400, 3000, 0.35, 4), 78.7 - 1.6, 1, 0)
end_t = next(c['ft'] for c in cues if c['title'] > 0 and c['ft'] > 60)
place(perc, boom(5.0, 38), end_t, 0.55, 0)
place(perc, riser(2.5, gain=0.3, seed=5), end_t - 2.5, 1, 0)

music = verb(score * 0.9 + arp, 0.45) + verb(perc, 0.25)
# fades: in from silence over establish, out after end
fade_in = np.clip(t / 3.0, 0, 1) ** 1.5
music *= fade_in

# ================================================================= PLANE
dd = np.gradient(smooth(dist, 60), 1 / SR)
cutmask = np.zeros(N, bool)
for s in meta['shots']:
    i = int(s['start'] * SR); cutmask[max(0, i - 2400):i + 2400] = True
dd[cutmask | (np.abs(dd) > 60)] = 0
dopp = 343.0 / (343.0 + smooth(dd, 80))
fbp = (58 + 290 * rpm) * dopp
ph = 2 * np.pi * np.cumsum(fbp) / SR
prop = np.zeros(N)
for k in range(1, 12):
    prop += np.sin(k * ph + 0.3 * k) / k ** 1.15
slap = (0.5 + 0.5 * np.sin(ph)) ** 6
nz = rng.standard_normal(N)
prop += bp(nz, 300, 4000) * slap * 1.6
whine = np.sin(4.2 * ph) * 0.22 + np.sin(8.4 * ph + 1) * 0.07 + np.sin(13.1 * ph) * 0.03
motor = prop * 0.55 + whine
loud = np.clip(rpm, 0, 1) ** 1.3 * (0.35 + 0.65 * thr) * (rpm > 0.005)
SHOTF = {'headon': 0.22, 'climbout': 0.35, 'takeoff': 0.6, 'touchdown': 0.6, 'pilot': 0.5, 'survey': 0.5, 'classify': 0.6, 'candidates': 0.6, 'spiral': 0.6}
sfac = np.interp(t, cf, np.array([SHOTF.get(c['shot'], 1.0) for c in cues]))
dist_e = dist * sfac
dg = np.maximum(1.0 / (1.0 + dist_e / 5.0), 0.03)
gain = smooth(loud * np.where(belly, 0.42, dg), 25)
fc = smooth(np.where(belly, 1800, np.maximum(9500 / (1 + dist_e / 22), 750)), 25)
motor = onepole_tv(motor * gain, fc)
motor = onepole_tv(motor, fc)
# stereo: slight width
plane = np.vstack([motor, np.roll(motor, 18)]) * 0.9

# wind (camera travelling with plane, or onboard)
sid = [shot_at(x) for x in cf]
travel = np.interp(t, cf, np.array([1.0 if s in ('chase', 'formation', 'final', 'spool') and c['dist'] < 8 else 0.0 for s, c in zip(sid, cues)]))
w_amt = 0.02 + travel * 0.16 * (vel / 12) ** 2 + belly * 0.32 + 0.015 * (ui == 0)
w_amt = smooth(w_amt, 40)
gust = 0.75 + 0.25 * np.interp(t, np.arange(0, DUR + TAIL + 2, 0.7), rng.uniform(-1, 1, int((DUR + TAIL + 2) / 0.7) + 1))
wind = np.vstack([bp(rng.standard_normal(N), 120, 1400), bp(rng.standard_normal(N), 120, 1400)]) * w_amt * gust * 0.9

# ground roll rumble (takeoff run, rollout)
onground = (alt < 0.05) & (vel > 0.2)
rg = smooth(onground * np.clip(vel / 10, 0, 1) * np.clip(1.0 / (1 + dist / 12), 0, 1), 30)
rum = lp(np.cumsum(rng.standard_normal(N)) * 0.02, 260); rum -= smooth(rum, 50)
swish = hp(rng.standard_normal(N), 2500) * 0.25
rumble = np.vstack([rum + swish, rum + swish]) * rg * 0.85

# ================================================================= FOLEY / UI
fx = np.zeros((2, N)); fxv = np.zeros((2, N))
def click(f=2500, dur=0.03, g=1.0):
    n = int(dur * SR); tt = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * tt) * 0.6 + hp(rng.standard_normal(n), 3000) * 0.4) * env_ad(n, 0.0005, dur / 4) * g
def bell(f, dur=2.0):
    n = int(dur * SR); tt = np.arange(n) / SR; s = np.zeros(n)
    for ratio, a, dcy in ((1, 1, 1.2), (2.0, 0.35, 0.6), (2.76, 0.25, 0.4), (5.4, 0.08, 0.15)):
        s += a * np.sin(2 * np.pi * f * ratio * tt) * np.exp(-tt / dcy)
    return s * np.minimum(1, tt / 0.003)
def bloop(f0=230, f1=150, dur=0.22):
    n = int(dur * SR); tt = np.arange(n) / SR; fr = f0 * (f1 / f0) ** (tt / dur)
    return np.sin(2 * np.pi * np.cumsum(fr) / SR) * env_ad(n, 0.004, 0.07)
def whoosh(dur=0.9, f0=500, f1=6000, seed=11):
    n = int(dur * SR); x = np.random.default_rng(seed).standard_normal(n); tt = np.arange(n) / SR
    fc = f0 * (f1 / f0) ** (tt / dur); y = onepole_tv(x, fc, 128)
    return hp(y, 300) * np.sin(np.pi * tt / dur) ** 2
# touchdown: thump + rattle + grass
td = EV['touchdown'][0]
n = int(1.2 * SR); tt = np.arange(n) / SR
thump = np.sin(2 * np.pi * 75 * tt * (1 + 0.5 * np.exp(-tt / 0.02))) * env_ad(n, 0.002, 0.09) + lp(rng.standard_normal(n), 900) * env_ad(n, 0.001, 0.05) * 0.7
place(fxv, thump, td, 0.55, 0.1)
for k in range(7):
    place(fxv, click(rng.uniform(900, 1900), 0.02, 0.18), td + 0.03 + k * rng.uniform(0.02, 0.06), 1, rng.uniform(-0.3, 0.3))
place(fxv, hp(rng.standard_normal(int(0.8 * SR)), 1800) * env_ad(int(0.8 * SR), 0.01, 0.25), td, 0.12, 0)
# candidates
for x in EV.get('reject', []): place(fxv, bloop(), x, 0.22, -0.2)
for x in EV.get('win', []):
    place(fxv, bell(midi(81), 1.8), x, 0.10, 0.15); place(fxv, bell(midi(86), 1.8), x + 0.09, 0.08, 0.25)
for x in EV.get('path', []): place(fxv, whoosh(0.8, 700, 7000), x, 0.10, 0)
# approval UI
pr = EV['press'][0]; ap = EV['approved'][0]
place(fxv, click(1800, 0.04, 0.5), pr, 1, 0)
n = int((ap - pr) * SR); tt = np.arange(n) / SR; fr = 330 * (2 ** (tt / (ap - pr)))
hold = np.sin(2 * np.pi * np.cumsum(fr) / SR) * (tt / (ap - pr)) ** 1.5 * 0.5 + np.sin(4 * np.pi * np.cumsum(fr) / SR) * 0.15 * (tt / (ap - pr)) ** 2
place(fxv, hold, pr, 0.07, 0)
for i, m in enumerate((74, 78, 81, 86)): place(fxv, bell(midi(m), 2.6), ap + i * 0.045, 0.085, -0.3 + 0.2 * i)
for i, x in enumerate(EV.get('tick', [])): place(fxv, click(2100 + 180 * i, 0.035, 0.35), x, 1, 0.1 * i)
for x in EV.get('lock', []):
    place(fxv, click(700, 0.06, 0.5), x, 1, 0); place(fxv, click(1400, 0.04, 0.35), x + 0.07, 1, 0)
for x in EV.get('send', []):
    place(fxv, whoosh(1.0, 400, 8000, 13), x, 0.16, 0)
    for k in range(5): place(fxv, click(3000 + 400 * k, 0.025, 0.12), x + 0.15 + k * 0.07, 1, 0.4 * np.sin(k))
# survey reveal shimmer + belly scan pings + classification sweep
place(fxv, whoosh(1.4, 300, 9000, 17), 30.4, 0.12, 0)
bs = next(s for s in meta['shots'] if s['id'] == 'belly')
k = 0
while bs['start'] + k * 1.5 < bs['start'] + bs['dur']:
    place(fxv, bell(midi(93), 0.9) * 0.5, bs['start'] + k * 1.5, 0.035, 0.2 * np.sin(k)); k += 1
cs = next(s for s in meta['shots'] if s['id'] == 'classify')
place(fxv, whoosh(cs['dur'] * 0.8, 200, 4000, 19), cs['start'] + 0.4, 0.06, 0)
# end credits: soft bell motif as the four names fade in
for i, m in enumerate((74, 78, 81, 86)):
    place(fxv, bell(midi(m), 3.0), DUR + 0.9 + i * 0.38, 0.05, -0.35 + 0.23 * i)

# ================================================================= AMBIENCE (birds, breeze) at ground-level shots
amb = np.zeros((2, N))
ground_shots = {'establish': 0.7, 'spool': 1.0, 'takeoff': 0.9, 'pilot': 1.0, 'approve': 0.5, 'touchdown': 0.8, 'rollout': 1.0, 'pullback': 0.7, 'chase': 0.3, 'headon': 0.6}
def chirp(seed):
    r = np.random.default_rng(seed); out = []
    base = r.uniform(2800, 5200); nn = r.integers(2, 6)
    for k in range(nn):
        dur = r.uniform(0.04, 0.09); n = int(dur * SR); tt = np.arange(n) / SR
        f = base * (1 + r.uniform(-0.15, 0.25) * tt / dur) * (1 + 0.04 * np.sin(2 * np.pi * r.uniform(30, 60) * tt))
        out.append(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * tt / dur) ** 2)
        out.append(np.zeros(int(r.uniform(0.03, 0.08) * SR)))
    return np.concatenate(out)
ta = 0.4; seed = 100
while ta < DUR + 1:
    lv = ground_shots.get(shot_at(ta), 0.0)
    if lv > 0: place(amb, chirp(seed), ta, 0.022 * lv, rng.uniform(-0.8, 0.8))
    ta += rng.exponential(0.9); seed += 1
amb = verb(amb, 0.5)
gl = np.interp(t, cf, np.array([ground_shots.get(s, 0.15) for s in sid]))
breeze = np.vstack([lp(rng.standard_normal(N), 700), lp(rng.standard_normal(N), 700)]) * smooth(gl, 50) * 0.05 * gust
amb += breeze

# ================================================================= MIX
fxm = verb(fxv, 0.3) + fx
mix = music * 0.55 + plane * 0.62 + wind * 0.6 + rumble * 0.5 + fxm * 1.0 + amb * 1.0
# overall fade at very end
end = DUR + TAIL
mix *= np.clip((end - t) / 1.8, 0, 1)
mix = hp(mix, 25)
peak = np.abs(mix).max(); mix = mix / peak * 0.89
# gentle soft clip / glue
mix = np.tanh(mix * 1.15) / np.tanh(1.15)
rms = np.sqrt((mix ** 2).mean()); print(f'peak {peak:.3f} rms {20*np.log10(rms):.1f} dBFS, dur {N/SR:.2f}s')
import wave
pcm = (np.clip(mix.T, -1, 1) * 32767).astype('<i2')
with wave.open(f'{OUT}/audio.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print('wrote', f'{OUT}/audio.wav')

if os.environ.get('STEMS'):  # debug: per-stem loudness table
    stems = dict(music=music * 0.55, plane=plane * 0.62, wind=wind * 0.6, rumble=rumble * 0.5, fx=fxm, amb=amb)
    sc = 0.89 / peak
    def db(x): return 20 * np.log10(np.sqrt((x ** 2).mean()) * sc + 1e-9)
    print('sec  ' + ' '.join(f'{k:>7}' for k in stems) + '   shot')
    for s0 in range(0, int(DUR) + 2, 2):
        i, j = s0 * SR, min(N, (s0 + 2) * SR)
        print(f'{s0:4d} ' + ' '.join(f'{db(v[:, i:j]):7.1f}' for v in stems.values()) + f'   {shot_at(s0 + 0.5)}')
