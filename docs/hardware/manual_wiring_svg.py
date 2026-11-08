"""Generate docs/hardware/manual_wiring.svg: the Tutor's MANUAL-ONLY build (no Pi, no camera, no autonomy).

The XR1 Nano has only a CRSF serial output, so the FC stays in as the receiver -> servo/ESC board, locked to MANUAL.
Everything else is the as-built wiring in docs/hardware/WIRING.md (sections 1-5). Guide: docs/hardware/MANUAL_WIRING.md.
"""
import sys
from xml.sax.saxutils import escape

W, H = 1500, 1230
RED, BLK, AMB, BLU, GRN, ORG, BRN, GRY, PUR, HAZ = (
    "#d62728", "#222222", "#c98a00", "#1f77b4", "#2ca02c", "#ff7f0e", "#8c564b", "#8a8a8a", "#7b4fd6", "#c0392b")
FONT = "Helvetica, Arial, sans-serif"
out = []


def add(s):
    out.append(s)


def text(x, y, s, size=11, anchor="start", weight="normal", fill="#111", italic=False):
    st = ' font-style="italic"' if italic else ""
    add(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" text-anchor="{anchor}" '
        f'font-weight="{weight}" fill="{fill}"{st}>{escape(s)}</text>')


def lines(x, y, rows, size=11, gap=None, anchor="start", weight_first=True, fill="#111"):
    gap = gap or size + 4
    for i, r in enumerate(rows):
        text(x, y + i * gap, r, size=size, anchor=anchor,
             weight="bold" if (weight_first and i == 0) else "normal", fill=fill)


def box(x, y, w, h, fill="#ffffff", stroke="#333", rx=8, sw=1.5, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def path(pts, color, w=2.2, dash=None):
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"{ds}/>')


def pad(x, y, label, w=34, h=18, fill="#e8c35a"):
    box(x - w / 2, y - h / 2, w, h, fill=fill, stroke="#7a5d10", rx=3, sw=1)
    text(x, y + 4, label, size=10, anchor="middle", weight="bold")


def pin(x, y, r=5, fill="#e8c35a"):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="#7a5d10" stroke-width="1"/>')


def dot(x, y, c=BLK):
    add(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{c}"/>')


def xmark(x, y, s=7):
    path([(x - s, y - s), (x + s, y + s)], HAZ, w=3)
    path([(x - s, y + s), (x + s, y - s)], HAZ, w=3)


def tick(x, y):
    path([(x - 6, y), (x - 2, y + 5), (x + 7, y - 6)], GRN, w=3)


# ---------------------------------------------------------------- canvas + title
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')
add(f'<rect x="0" y="0" width="{W}" height="70" fill="#0f172a"/>')
text(24, 32, "Cloudbreak · Flite Test Tutor — MANUAL-ONLY build (no Pi, no camera, no autonomy)", size=22,
     weight="bold", fill="#ffffff")
text(24, 55, "v1 · 2026-11-08 13:30 · FC kept as the receiver → servo/ESC board, locked to MANUAL · everything not "
     "crossed out is the as-built wiring in WIRING.md §1–5 · PROP OFF on the bench · P1 runs every power event",
     size=12, fill="#cbd5e1")

# ---------------------------------------------------------------- power column (unchanged)
box(130, 100, 240, 62, fill="#fff4d6")
lines(250, 124, ["3S LiPo, fully charged", "NOT the pack that collapsed at 07:14"], size=11.5, anchor="middle")
box(222, 175, 56, 22, fill="#f6c343", stroke="#7a5d10", rx=4)
text(250, 190, "XT60", size=11, anchor="middle", weight="bold")
path([(250, 162), (250, 175)], "#7a5d10", w=2)
text(286, 190, "power owner plugs / unplugs", size=10, fill="#555")
path([(236, 197), (236, 217), (110, 217), (110, 272)], BLK, w=6)
path([(264, 197), (264, 217), (390, 217), (390, 272)], RED, w=6)
path([(110, 244), (238, 244)], BLK, w=2)
path([(258, 244), (390, 244)], RED, w=2)
dot(110, 244); dot(390, 244, RED)
add('<line x1="242" y1="232" x2="242" y2="256" stroke="#222" stroke-width="3"/>')
add('<path d="M254,232 Q248,244 254,256" fill="none" stroke="#222" stroke-width="3"/>')
text(402, 240, "470 µF cap", size=10, weight="bold")
text(402, 253, "(as built)", size=10, fill="#555")
box(70, 282, 360, 112, fill="#f1f5f9")
pad(110, 282, "B−", fill="#555555"); pad(390, 282, "B+", fill="#e57373")
lines(250, 310, ["PDB (stacked under the FC) — unchanged",
                 "FC BEC 5 V → FC + 4V5 pins (XR1, GPS)",
                 "Servo BEC 5 V → Vx rail (all 4 servos)",
                 "V + I sense → low-battery failsafe (10.5 V, 10 s)",
                 "Pad order: B− | ESC− | ESC− | ESC+ | ESC+ | B+"], size=10.5, anchor="middle")
for x, lab, f in [(150, "ESC−", "#777"), (210, "ESC−", "#777"), (290, "ESC+", "#e57373"), (350, "ESC+", "#e57373")]:
    pad(x, 394, lab, w=40, fill=f)
text(132, 420, "pair 1", size=9, anchor="end", fill="#555")
text(368, 420, "pair 1", size=9, fill="#555")
text(250, 418, "pair 2", size=9, anchor="middle", fill="#555")
# UBEC: input stays soldered, output capped
path([(210, 403), (210, 440)], BLK, w=3)
path([(290, 403), (290, 440)], RED, w=3)
box(170, 440, 160, 58, fill="#f3f4f6", stroke=GRY, dash="6 4")
lines(250, 458, ["UBEC (input stays soldered)", "OUTPUT NOT USED: it fed the Pi", "live 5 V when the pack is in"],
      size=10, anchor="middle", fill="#444")
path([(244, 498), (244, 516)], RED, w=2.5)
path([(256, 498), (256, 516)], BLK, w=2.5)
box(238, 516, 24, 20, fill="#fde2e1", stroke=HAZ, rx=3)
xmark(250, 526, 6)
lines(250, 554, ["Pi lead: unplug at the Pi,", "insulate the plug, tie it down"], size=9.5, anchor="middle",
      weight_first=False, fill=HAZ)
# ESC + motor
path([(150, 403), (150, 590)], BLK, w=6)
path([(350, 403), (350, 590)], RED, w=6)
box(110, 590, 280, 96, fill="#eef2ff")
lines(250, 614, ["ESC — unchanged", "XT60 pair to PDB ESC pair 1", "signal + GND → FC S1",
                 "red BEC wire stays lifted + insulated"], size=10.5, anchor="middle")
for x in (220, 250, 280):
    path([(x, 686), (x, 742)], BRN, w=3.5)
add('<circle cx="250" cy="786" r="44" fill="#f8fafc" stroke="#333" stroke-width="1.5"/>')
lines(250, 782, ["Motor", "CCW (front)"], size=10.5, anchor="middle")
lines(298, 720, ["phase order as tested", "(spun CCW 00:44–00:56)"], size=9.5, weight_first=False, fill=BRN)
text(250, 852, "Prop goes on only with the battery OUT", size=10.5, anchor="middle", weight="bold", fill=HAZ)
# ESC servo lead -> S1
path([(390, 636), (500, 636), (500, 812), (600, 812), (600, 760)], ORG, w=3.2)
path([(390, 664), (430, 672)], RED, w=2.5)
xmark(437, 674, 6)
text(452, 690, "red: lifted", size=9.5, fill=HAZ)
text(506, 804, "ESC → S1", size=10, fill=ORG, weight="bold")

# ---------------------------------------------------------------- FC board
box(560, 290, 440, 400, fill="#1e293b", stroke="#0f172a", rx=10, sw=2)
lines(580, 318, ["CoreWing F405 Wing Mini V2 — FC (kept)"], size=14, fill="#f8fafc")
lines(580, 340, ["Job in this build: XR1 CRSF in → PWM out to servos + ESC",
                 "ArduPlane 4.7.2 · MANUAL = sticks pass straight through",
                 "SERIAL5 = GPS · SERIAL6 = XR1 (CRSF) · SERIAL4 idle"],
      size=11, weight_first=False, fill="#cbd5e1")
box(574, 392, 412, 168, fill="#3b2f0b", stroke="#fde68a", rx=6, sw=1)
lines(586, 412, ["The ONLY setting change (USB, key laptop, no battery):",
                 "FLTMODE1 … FLTMODE6 = 0  →  MANUAL in every switch position",
                 "Unchanged: output map + reversals, radio cal, level trim,",
                 "Schuyler fence, pre-arm checks, signing, DataFlash log,",
                 "failsafes: RC lost → CIRCLE → RTL after 20 s · < 10.5 V → RTL",
                 "Get control back after any failsafe:",
                 "   flick the mode switch to another position (= MANUAL)",
                 "Arm: throttle down + full RIGHT rudder ≈ 2–3 s (pre-arm clear)",
                 "Disarm: throttle cut ON, power owner unplugs the pack"],
      size=10.5, gap=17, fill="#fde68a")
lines(580, 580, ["USB-ext connector → WEXT SE USB-C (settings, compass cal, status)",
                 "Vx = servo rail (servo BEC) · 4V5 = FC BEC, also live on USB"],
      size=10, weight_first=False, fill="#94a3b8")
# GPS (kept)
gps_fc = [(600, "SDA"), (640, "SCL"), (680, "4V5"), (720, "GND"), (760, "TX5"), (800, "RX5")]
gps_mod = ["SDA", "SCL", "VCC", "GND", "RX", "TX"]
gps_col = [BLU, GRN, RED, BLK, AMB, AMB]
box(578, 140, 244, 76, fill="#ecfdf5")
lines(700, 160, ["RMRC M10Q + 5883 GPS / compass (kept)", "fence + pre-arm need a 3D fix outdoors",
                 "compass cal at the field if still pending"], size=10.5, anchor="middle")
for (x, lab), mlab, c in zip(gps_fc, gps_mod, gps_col):
    text(x, 228, mlab, size=9, anchor="middle", weight="bold")
    path([(x, 232), (x, 276)], c, w=2.5)
    box(x - 15, 276, 30, 14, fill="#5ab4e8", stroke="#1d5f8a", rx=2, sw=1)
    text(x, 287, lab, size=9, anchor="middle", weight="bold")
lines(826, 250, ["GPS TX → RX5", "GPS RX → TX5"], size=10, weight_first=False, fill="#555")
# WEXT SE
box(860, 140, 190, 76, fill="#f5f3ff")
lines(955, 160, ["CoreWing WEXT SE (USB-C)", "key laptop on USB only:", "no Pi, no Wi-Fi link"], size=10.5,
      anchor="middle")
path([(930, 216), (930, 290)], "#475569", w=4)
# TELEM (now empty)
tel = [(350, "GND"), (380, "RX2"), (410, "TX2"), (440, "RX4"), (470, "TX4"), (500, "4V5")]
for y, lab in tel:
    box(1000, y - 7, 16, 14, fill="#5ab4e8", stroke="#1d5f8a", rx=2, sw=1)
    text(992, y + 4, lab, size=10, anchor="end", weight="bold", fill="#e2e8f0")
text(990, 330, "TELEM (GH1.25 6P)", size=10, anchor="end", fill="#94a3b8")
path([(1016, 425), (1050, 425)], GRY, w=4, dash="5 4")
xmark(1058, 425, 8)
lines(1024, 452, ["TELEM", "empty"], size=9.5, fill=HAZ)
# ELRS header + XR1
elrs = [(860, "T6", AMB), (895, "R6", AMB), (930, "4V5", RED), (965, "GND", BLK)]
for x, lab, c in elrs:
    text(x, 682, lab, size=9, anchor="middle", weight="bold", fill="#e2e8f0")
    pin(x, 698)
    path([(x, 703), (x, 790)], c, w=2.5)
text(912, 664, "ELRS header", size=10, anchor="middle", fill="#94a3b8")
box(842, 790, 146, 62, fill="#fff1f2")
for x, lab in [(860, "RX"), (895, "TX"), (930, "5V"), (965, "GND")]:
    text(x, 804, lab, size=9, anchor="middle", weight="bold")
lines(915, 824, ["RadioMaster XR1 Nano", "ELRS 2.4 GHz · CRSF only"], size=10.5, anchor="middle")
text(915, 868, "T6 → RX · R6 ← TX", size=9.5, anchor="middle", fill="#555")
path([(988, 796), (1010, 778)], "#333", w=2)
path([(1004, 772), (1016, 784)], "#333", w=2)
path([(1016, 790), (1060, 812)], PUR, w=2, dash="6 5")
text(1008, 832, "2.4 GHz", size=10, fill=PUR)
# Pocket
box(1060, 742, 290, 140, fill="#f5f3ff")
lines(1205, 762, ["RadioMaster Pocket (pilot)",
                  "same model, same bind: no re-bind",
                  "CH1 aileron · CH2 elevator · CH3 throttle · CH4 rudder",
                  "Mode switch (CH8): MANUAL in all 3 positions",
                  "NEW: throttle-cut switch → override CH3 = −100",
                  "   (not lower: < 950 µs = FC throttle failsafe)",
                  "NEW: flight timer 5 min on the first flight",
                  "CH7 consent switch: not used"], size=10.5, anchor="middle")
# servo header
cols = [(600, "S1"), (640, "S2"), (680, "S3"), (720, "S4"), (760, "S5"), (800, "S6")]
box(582, 690, 236, 72, fill="#334155", stroke="#0f172a", rx=4)
for x, lab in cols:
    text(x, 682, lab, size=10, anchor="middle", weight="bold", fill="#e2e8f0")
    for yy in (706, 728, 750):
        pin(x, yy, r=4.5)
text(826, 710, "sig", size=9, fill="#333")
text(826, 732, "Vx +", size=9, fill=RED)
text(826, 754, "G −", size=9, fill="#333")
text(640, 778, "empty", size=9, anchor="middle", fill="#555")
srv = [
    ([(680, 762), (680, 850), (560, 850), (560, 900)], 560, "L aileron", "S3 · not rev."),
    ([(720, 762), (720, 866), (650, 866), (650, 900)], 650, "R aileron", "S4 · not rev."),
    ([(760, 762), (760, 882), (740, 882), (740, 900)], 740, "Elevator", "S5 · REVERSED"),
    ([(800, 762), (800, 882), (830, 882), (830, 900)], 830, "Rudder", "S6 · REVERSED"),
]
for pts, cx, name, sub in srv:
    path(pts, ORG, w=3.2)
    box(cx - 41, 900, 82, 48, fill="#fff7ed")
    lines(cx, 920, [name, sub], size=9.5, anchor="middle")
text(560, 970, "Servo plugs unchanged: signal → top row · red → Vx · brown/black → G. Reversals stay in the FC "
     "(SERVO5/6_REVERSED + RC2_REVERSED): don't reverse anything on the Pocket.", size=10, fill="#555")

# ---------------------------------------------------------------- removed (right column)
box(1090, 100, 390, 300, fill="#f9fafb", stroke=GRY, dash="8 5", sw=2)
text(1106, 126, "REMOVED for the manual build", size=14, weight="bold", fill=HAZ)
removed = [
    ("Raspberry Pi 3 + Camera Module 3 + ribbon",
     "power OFF first; lift them out together; never",
     "unplug a camera ribbon with the Pi powered"),
    ("TELEM cable (FC GH1.25 → Pi pins 6 / 8 / 10)",
     "unplug it at the FC end; the port stays empty", None),
    ("UBEC → Pi lead (Pi pins 2 / 14)",
     "unplug at the Pi, insulate, tie down (left column)", None),
    ("Ground side: laptop link, Wi-Fi hotspot,",
     "governor, core, signed uplink: none of it is used", None),
]
y = 154
for title, l1, l2 in removed:
    xmark(1112, y - 4, 6)
    text(1128, y, title, size=11, weight="bold", fill="#333")
    text(1128, y + 16, l1, size=10, fill="#555")
    if l2:
        text(1128, y + 30, l2, size=10, fill="#555")
        y += 16
    y += 50
text(1106, 386, "→ CG moves: re-balance to 57–63 mm with the battery", size=11, weight="bold", fill=HAZ)

# kept summary (right column, middle)
box(1090, 420, 390, 300, fill="#f0fdf4", stroke="#86efac")
text(1106, 446, "KEPT as built (check each one before closing)", size=13, weight="bold", fill="#166534")
kept = ["Battery → XT60 → PDB B+/B−, 470 µF cap",
        "PDB ESC pair 1 → XT60 → ESC → motor",
        "ESC signal + GND → S1 (red lifted)",
        "Ailerons S3 / S4 · elevator S5 · rudder S6",
        "XR1 → ELRS header (TX → R6, RX → T6)",
        "GPS + compass → GPS socket (I2C + UART5)",
        "microSD card in the FC (flight log)",
        "First install broke 4 joints at once:",
        "   compass I2C · XR1 TX → R6 · TELEM · ribbon.",
        "   Push-check every plug, then fc_bench.py status:",
        "   compass present · RC 16 ch · GPS detected"]
for i, s in enumerate(kept):
    yy = 472 + i * 21
    if not s.startswith("   ") and i < 7:
        tick(1112, yy - 4)
    text(1128, yy, s.strip() if i < 7 else s, size=10.5,
         weight="bold" if i == 7 else "normal", fill="#14532d" if i < 7 else HAZ)

# ---------------------------------------------------------------- bottom: order of work, checks, legend
box(20, 990, 520, 225, fill="#f8fafc", stroke="#94a3b8")
lines(36, 1012, ["Order of work · target 16:00 at Schuyler · sunset ≈ 16:39",
                 "1  Battery out: Pi + camera, TELEM cable, UBEC→Pi lead out",
                 "2  USB only: FLTMODE1–6 = 0, reboot, fc_bench.py status",
                 "3  Pocket: throttle-cut switch + 5 min timer",
                 "4  Pack in (P1), prop off: surface checks (middle box)",
                 "5  CG 57–63 mm with the flight pack · pack out",
                 "6  Field: power up still → 3D fix → compass cal → reboot still",
                 "7  Pre-arm clear → prop-off arm test + TX-off test",
                 "8  Pack out → prop on → run-up held + range check",
                 "9  Go / no-go → hand launch in MANUAL → land by 16:30",
                 "Full steps: docs/hardware/MANUAL_WIRING.md"],
      size=10.5, gap=19)

box(560, 990, 440, 225, fill="#ffffff", stroke="#94a3b8")
lines(576, 1012, ["Bench + field checks (MANUAL, prop OFF)",
                  "Stick right → right aileron UP, left aileron DOWN",
                  "Stick back → elevator UP",
                  "Rudder stick right → rudder trailing edge RIGHT",
                  "Mode switch: MANUAL in all 3 positions",
                  "Throttle cut ON → RC3 ≈ 988 µs, motor won't run",
                  "Armed, low throttle → motor CCW from the front",
                  "Pocket OFF (armed, prop off) → motor stops",
                  "Pocket back ON → flick mode switch → MANUAL again",
                  "Range check before the first flight"],
      size=10.5, gap=19)

box(1020, 990, 460, 225, fill="#ffffff", stroke="#94a3b8")
text(1036, 1012, "Legend", size=12, weight="bold")
leg = [(RED, 6, None, "battery + (14 AWG)"), (BLK, 6, None, "battery − (14 AWG)"),
       (RED, 2.5, None, "+5 V / supply"), (BLK, 2.5, None, "GND"),
       (AMB, 2.5, None, "UART data"), (BLU, 2.5, None, "I2C SDA"), (GRN, 2.5, None, "I2C SCL"),
       (ORG, 3.2, None, "servo / ESC lead"), (BRN, 3.5, None, "motor phases"), (PUR, 2, "6 5", "radio link")]
for i, (c, w, d, lab) in enumerate(leg):
    yy = 1034 + i * 17
    path([(1036, yy - 4), (1076, yy - 4)], c, w=w, dash=d)
    text(1084, yy, lab, size=10)
xmark(1056, 1206, 5)
text(1084, 1210, "removed / not connected", size=10)
text(1250, 1012, "Hazards", size=12, weight="bold")
hz = ["Prop OFF until step 8;",
      "  prop on only with the pack OUT",
      "Power owner alone plugs the pack",
      "UBEC output is live: insulate it",
      "Pack 1 collapsed: don't fly it",
      "FC takes over (CIRCLE / RTL) on RC",
      "  loss, < 10.5 V, or leaving the fence",
      "  (100 m ceiling): flick mode switch",
      "Armed = live prop: throttle cut",
      "  ON before anyone approaches"]
for i, s in enumerate(hz):
    text(1250, 1034 + i * 17, s.strip() if not s.startswith("  ") else "   " + s.strip(), size=10,
         fill=HAZ if not s.startswith("  ") else "#444")

add("</svg>")
svg = "\n".join(out)
dest = sys.argv[1] if len(sys.argv) > 1 else "manual_wiring.svg"
open(dest, "w", encoding="utf-8").write(svg)
print("wrote", dest, len(svg), "bytes")
