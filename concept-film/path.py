"""Generate the Cloudbreak concept-film mission trajectory.

World frame (matches three.js): x = east, y = up, z = south. Heading h: direction (cos h, sin h) in (x, z).
Left turn => h decreases. Output: web/mission.json with 60 Hz samples in mission time.
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # outputs go to web/ next to this script
import json, math
import numpy as np
from scipy.ndimage import gaussian_filter1d

G = 9.81

# ---------- 2D ground track from tangent-continuous primitives ----------
class Turtle:
    def __init__(self, x, z, h):
        self.x, self.z, self.h = x, z, h
        self.pts = [(x, z, h, 0.0)]  # x, z, heading, curvature(signed: +right)
        self.marks = {}

    def straight(self, L, ds=0.25):
        n = max(1, int(round(L / ds)))
        for i in range(1, n + 1):
            d = L * i / n
            self.pts.append((self.x + d * math.cos(self.h), self.z + d * math.sin(self.h), self.h, 0.0))
        self.x += L * math.cos(self.h); self.z += L * math.sin(self.h)

    def arc(self, R, deg, side, ds=0.25):
        sgn = 1 if side == 'R' else -1
        ang = math.radians(deg)
        L = R * ang
        n = max(1, int(round(L / ds)))
        # centre: to the right of heading for right turn
        cx = self.x + R * math.cos(self.h + sgn * math.pi / 2)
        cz = self.z + R * math.sin(self.h + sgn * math.pi / 2)
        a0 = math.atan2(self.z - cz, self.x - cx)
        for i in range(1, n + 1):
            a = a0 + sgn * ang * i / n
            h = self.h + sgn * ang * i / n
            self.pts.append((cx + R * math.cos(a), cz + R * math.sin(a), h, sgn / R))
        self.h += sgn * ang
        self.x = cx + R * math.cos(a0 + sgn * ang); self.z = cz + R * math.sin(a0 + sgn * ang)

    def mark(self, name):
        self.marks[name] = len(self.pts) - 1


T = Turtle(-55.0, 70.0, 0.0)          # takeoff strip, heading east
T.mark('roll_start')
T.straight(205)                         # roll + climb-out east to x=150
T.arc(50, 90, 'L')                      # -> heading north at (200, 20)
T.straight(90)                          # -> (200, -70)
T.arc(50, 90, 'L')                      # -> heading west at (150, -120)
T.mark('survey_start')
T.straight(300); T.mark('leg1_end')     # leg 1 west  z=-120
T.arc(25, 180, 'L')                     # -> east at z=-70
T.straight(300); T.mark('leg2_end')     # leg 2 east
T.arc(25, 180, 'R')                     # -> west at z=-20
T.straight(300); T.mark('leg3_end')     # leg 3 west
T.arc(25, 180, 'L')                     # -> east at z=30
T.straight(300); T.mark('survey_end')   # leg 4 east to x=150
T.straight(40)                          # to (190, 30): south point of loiter circle
T.mark('loiter_start')
T.arc(40, 900, 'L')                     # 2.5 turns CCW around (190,-10) -> north point heading west
T.mark('final_start')                   # (190, -50) heading west
T.straight(250)                         # final + rollout (trimmed later)

P = np.array(T.pts)
xz = P[:, :2]
seg = np.hypot(np.diff(xz[:, 0]), np.diff(xz[:, 1]))
S = np.concatenate([[0], np.cumsum(seg)])
heading = np.unwrap(P[:, 2])
kappa = P[:, 3]
M = {k: S[i] for k, i in T.marks.items()}

# ---------- altitude profile y(s) ----------
LIFTOFF = 18.0
CLIMB_END = M['survey_start'] - 15
s_loiter, s_final = M['loiter_start'], M['final_start']
L_loiter = s_final - s_loiter

def smoother(u):
    u = np.clip(u, 0, 1)
    return u * u * u * (u * (u * 6 - 15) + 10)

GLIDE = 0.10
AIM_X = 35.0            # glide-line ground intercept (x), final runs west along z=-50
FLARE_H = 2.0
x_final0 = 190.0
H_FINAL0 = GLIDE * (x_final0 - AIM_X)     # 15.5 m at final start

def altitude(s):
    y = np.zeros_like(s)
    # climb: rotate into an 18% gradient over 25 m, hold, then ease onto 40 m
    yc = np.zeros_like(s)
    acc = 0.0
    for i in range(1, len(s)):
        si = s[i]
        if si <= LIFTOFF or si > s_loiter:
            yc[i] = acc if si > LIFTOFF else 0.0
            continue
        g = 0.18 * float(smoother((si - LIFTOFF) / 25.0))
        g = min(g, 0.18 * max(0.0, (40.0 - acc)) / 9.0) if acc > 31 else g
        acc = min(40.0, acc + g * (si - s[i - 1]))
        yc[i] = acc
    c = (s > LIFTOFF) & (s <= s_loiter)
    y = np.where(c, yc, y)
    # loiter: climb to 48 in first 150 m, hold, then descend to H_FINAL0 over last 520 m
    l = (s > s_loiter) & (s <= s_final)
    u1 = smoother((s - s_loiter) / 150.0)
    u2 = smoother((s - (s_final - 520)) / 520.0)
    y_l = 40 + 8 * u1
    y_l = y_l * (1 - u2) + H_FINAL0 * u2
    y = np.where(l, y_l, y)
    # final: glide then quadratic flare, then ground
    f = s > s_final
    d = s - s_final                      # distance flown along final
    x_now = x_final0 - d
    h_glide = GLIDE * (x_now - AIM_X)
    flare_len = 2 * FLARE_H / GLIDE      # 40 m: matches slope at flare entry
    x_flare = AIM_X + FLARE_H / GLIDE    # 55
    x_td = x_flare - flare_len           # 15
    u = (x_flare - x_now) / flare_len
    h_flare = FLARE_H * (1 - np.clip(u, 0, 1)) ** 2
    y_f = np.where(x_now > x_flare, h_glide, h_flare)
    y = np.where(f, y_f, y)
    return y, x_td

Y, X_TD = altitude(S)
s_td = s_final + (x_final0 - X_TD)
ROLLOUT = 20.0
s_stop = s_td + ROLLOUT
keep = S <= s_stop + 0.01
S, xz, heading, kappa, Y = S[keep], xz[keep], heading[keep], kappa[keep], Y[keep]

# ---------- speed profile v(s) ----------
A_ROLL = 11.0 ** 2 / (2 * LIFTOFF)
def speed(s):
    v = np.full_like(s, 12.0)
    v = np.where(s < LIFTOFF, np.sqrt(2 * A_ROLL * np.maximum(s, 0)), v)
    v = np.where((s >= LIFTOFF) & (s < LIFTOFF + 40), 11 + (s - LIFTOFF) / 40, v)
    fs = s - s_final
    v = np.where((fs > -120) & (s < s_td), 12 - 1.0 * smoother((fs + 120) / 120.0), v)    # 11 on final
    fl = (s > s_td - 40) & (s < s_td)
    v = np.where(fl, 11 - 2 * smoother((s - (s_td - 40)) / 40.0), v)                      # 9 at touchdown
    ro = s >= s_td
    a_ro = 9.0 ** 2 / (2 * ROLLOUT)
    v = np.where(ro, np.sqrt(np.maximum(9.0 ** 2 - 2 * a_ro * (s - s_td), 0)), v)
    return v

V = speed(S)
# time along path
dt_seg = np.zeros_like(S)
vmid = np.maximum(0.5 * (V[1:] + V[:-1]), 0.3)
dt_seg[1:] = np.diff(S) / vmid
# exact ground-roll time near zero speed
Tm = np.cumsum(dt_seg)
roll = S < LIFTOFF
Tm[roll] = np.sqrt(2 * S[roll] / A_ROLL)
Tm[~roll] = Tm[~roll] - Tm[np.argmax(~roll)] + math.sqrt(2 * LIFTOFF / A_ROLL)
# final approach to a stop: last samples' v->0 inflate dt; clamp tail
T_STOP = Tm[-1]

# ---------- resample at 60 Hz ----------
FPS = 60
PRE = 6.0      # seconds parked before roll
POST = 6.0     # seconds parked after stop
tt = np.arange(-PRE, T_STOP + POST, 1 / FPS)
tc = np.clip(tt, 0, T_STOP)
s_t = np.interp(tc, Tm, S)
x_t = np.interp(s_t, S, xz[:, 0]); z_t = np.interp(s_t, S, xz[:, 1])
y_t = np.interp(s_t, S, Y)
h_t = np.interp(s_t, S, heading)
k_t = np.interp(s_t, S, kappa)
v_t = np.interp(tc, Tm, V)
v_t[tt < 0] = 0; v_t[tt > T_STOP] = 0

# derived
sig = FPS * 0.35
gamma = np.arctan(np.gradient(gaussian_filter1d(y_t, 3), s_t + 1e-9 * np.arange(len(s_t))))
gamma[v_t < 1] = 0
gamma = gaussian_filter1d(np.nan_to_num(gamma), 6)
bank = np.arctan(v_t ** 2 * k_t / G)
bank[y_t < 0.05] = 0
bank = gaussian_filter1d(bank, sig)

t_liftoff = float(np.interp(LIFTOFF, S, Tm))
t_td = float(np.interp(s_td, S, Tm))
# angle of attack schedule
alpha = np.full_like(tt, math.radians(3.0))
alpha = np.where(tt < 0, 0, alpha)
rot = (tt >= 0) & (tt < t_liftoff + 1.0)
alpha = np.where(rot, np.radians(7.0) * smoother((tt - (t_liftoff - 0.8)) / 0.8), alpha)
climb = (tt >= t_liftoff + 1.0) & (y_t < 39)
alpha = np.where(climb & (tt < t_td - 20), math.radians(5.0), alpha)
t_flare = float(np.interp(s_td - 40, S, Tm))
fl = (tt >= t_flare) & (tt < t_td)
alpha = np.where(fl, np.radians(4 + 5 * smoother((tt - t_flare) / (t_td - t_flare))), alpha)
post = tt >= t_td
alpha = np.where(post, np.radians(9.0) * (1 - smoother((tt - t_td) / 1.4)) - gamma, alpha)
alpha = gaussian_filter1d(alpha, 10)
pitch = gamma + alpha
pitch[tt < 0] = 0
on_ground = (y_t < 0.02).astype(int)

# throttle
thr = np.full_like(tt, 0.55)
thr = np.where(tt < 0, np.clip((tt + 3.5) / 2.0, 0, 1) * 0.12, thr)       # idle spool before roll
thr = np.where((tt >= 0) & (tt < 1.0), 0.12 + 0.88 * smoother(tt / 1.0), thr)
thr = np.where((tt >= 1.0) & (y_t < 39) & (s_t < M['survey_start']), 1.0 - 0.25 * smoother((y_t - 5) / 30), thr)
t_loiter = float(np.interp(s_loiter, S, Tm)); t_final = float(np.interp(s_final, S, Tm))
desc = (s_t > s_final - 520) & (s_t <= s_final)
thr = np.where(desc, 0.32, thr)
thr = np.where((s_t > s_final) & (tt < t_flare), 0.3, thr)
thr = np.where((tt >= t_flare), 0.3 * (1 - smoother((tt - t_flare) / 2.0)), thr)
thr = np.where(tt > t_td, 0.0, thr)
thr = gaussian_filter1d(thr, 12)

# control-surface deflections (visual only, radians)
roll_rate = np.gradient(bank, 1 / FPS)
pitch_rate = np.gradient(pitch, 1 / FPS)
ail = np.clip(0.35 * roll_rate, -0.35, 0.35)
ele = np.clip(-0.5 * pitch_rate - 0.6 * (np.cos(bank) ** -1 - 1), -0.35, 0.35)
rud = np.clip(0.15 * v_t * k_t, -0.25, 0.25)
ail, ele, rud = (gaussian_filter1d(a, 6) for a in (ail, ele, rud))

def t_of(name):
    return round(float(np.interp(M[name], S, Tm)), 3)

events = {k: t_of(k) for k in T.marks if M[k] <= s_stop}
events.update(liftoff=round(t_liftoff, 3), touchdown=round(t_td, 3), flare=round(t_flare, 3), stop=round(T_STOP, 3),
              loiter=round(t_loiter, 3), final=round(t_final, 3))

r3 = lambda a: [round(float(v), 3) for v in a]
out = dict(fps=FPS, t0=float(tt[0]), n=len(tt), events=events,
           layout=dict(x_td=X_TD, aim_x=AIM_X, final_z=-50.0, glide=GLIDE, final_x0=x_final0, h_final0=H_FINAL0),
           x=r3(x_t), y=r3(y_t), z=r3(z_t), h=r3(h_t), pitch=r3(pitch), bank=r3(bank), v=r3(v_t), thr=r3(thr),
           ail=r3(ail), ele=r3(ele), rud=r3(rud), gnd=on_ground.tolist())
with open('web/mission.json', 'w') as f:
    json.dump(out, f, separators=(',', ':'))
print('events', json.dumps(events, indent=1))
print('samples', len(tt), 'duration', round(tt[-1] - tt[0], 1), 's')
print('max bank deg', round(math.degrees(np.abs(bank).max()), 1), 'max pitch deg', round(math.degrees(pitch.max()), 1), round(math.degrees(pitch.min()), 1))

# ---------- plot check ----------
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 3, figsize=(18, 6))
ax[0].plot(x_t, -z_t, lw=1); ax[0].set_aspect('equal'); ax[0].set_title('ground track (north up)')
for name, t in events.items():
    i = int((t - tt[0]) * FPS); i = min(max(i, 0), len(tt) - 1)
    ax[0].plot(x_t[i], -z_t[i], 'o', ms=3); ax[0].annotate(name, (x_t[i], -z_t[i]), fontsize=7)
ax[1].plot(tt, y_t); ax[1].set_title('altitude vs time'); ax[1].grid()
ax[2].plot(tt, np.degrees(bank), label='bank'); ax[2].plot(tt, np.degrees(pitch), label='pitch'); ax[2].plot(tt, thr * 20, label='thr*20'); ax[2].plot(tt, v_t, label='v'); ax[2].legend(); ax[2].grid()
plt.tight_layout(); plt.savefig('path_check.png', dpi=80)
fig, ax = plt.subplots(1, 1, figsize=(10, 4))
m = tt > events['final'] - 5
ax.plot(x_t[m], y_t[m]); ax.invert_xaxis(); ax.set_title('final approach profile (alt vs x)'); ax.grid()
plt.savefig('final_check.png', dpi=80)
