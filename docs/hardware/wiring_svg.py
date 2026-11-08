"""Generate docs/hardware/wiring.svg: Cloudbreak Tutor electrical wiring diagram.

Pad labels follow the ArduPilot CoreWingF405WMiniV2 README/pinout images (Plane-4.7.2),
the team's TELEM wiring in docs/CHECKLIST.md and P1's power plan (docs/updates/P1_*).
"""
import sys
from xml.sax.saxutils import escape

W, H = 1520, 1190
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


def path(pts, color, w=2.2, dash=None, cap="round"):
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="{cap}"{ds}/>')


def hop_h(x0, y, x1, xc, color, w=2.5, r=6):
    """Horizontal wire from x0 to x1 (x0 > x1) at y, hopping over a vertical wire at xc."""
    add(f'<path d="M{x0},{y} L{xc + r},{y} A{r},{r} 0 0 0 {xc - r},{y} L{x1},{y}" fill="none" '
        f'stroke="{color}" stroke-width="{w}" stroke-linecap="round"/>')


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


def hazard(x, y, n):
    add(f'<circle cx="{x}" cy="{y}" r="11" fill="{HAZ}"/>')
    text(x, y + 4, str(n), size=12, anchor="middle", weight="bold", fill="#fff")


# ---------------------------------------------------------------- canvas + title
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')
add(f'<rect x="0" y="0" width="{W}" height="70" fill="#0f172a"/>')
text(24, 32, "Cloudbreak · Flite Test Tutor — electrical wiring", size=22, weight="bold", fill="#ffffff")
text(24, 55, "CoreWing F405 Wing Mini V2 (ArduPlane 4.7.2) · v1 · 2026-11-07 · pad labels from the ArduPilot board README/pinout, "
     "TELEM wiring from docs/CHECKLIST.md, power plan from P1 · PROP OFF for all bench work", size=12, fill="#cbd5e1")

# ---------------------------------------------------------------- power column
# Battery + XT60
box(130, 128, 240, 62, fill="#fff4d6")
lines(250, 152, ["3S LiPo 1300 mAh", "11.1 V nominal · 12.6 V full"], size=12, anchor="middle")
box(222, 203, 56, 22, fill="#f6c343", stroke="#7a5d10", rx=4)
text(250, 218, "XT60", size=11, anchor="middle", weight="bold")
path([(250, 190), (250, 203)], "#7a5d10", w=2)
text(286, 218, "14 AWG lead (P1)", size=10, fill="#555")
# battery leads to B- / B+ (top-edge pads)
path([(236, 225), (236, 245), (110, 245), (110, 300)], BLK, w=6)
path([(264, 225), (264, 245), (390, 245), (390, 300)], RED, w=6)
# capacitor across B- / B+
path([(110, 272), (238, 272)], BLK, w=2)
path([(258, 272), (390, 272)], RED, w=2)
dot(110, 272); dot(390, 272, RED)
add('<line x1="242" y1="260" x2="242" y2="284" stroke="#222" stroke-width="3"/>')
add('<path d="M254,260 Q248,272 254,284" fill="none" stroke="#222" stroke-width="3"/>')
text(264, 266, "+", size=11, weight="bold", fill=RED)
text(226, 266, "−", size=12, weight="bold")
lines(402, 266, ["470 µF 35 V cap", "stripe (−) → B−"], size=10, weight_first=True)
hazard(452, 300, 5)
# PDB
box(70, 310, 360, 112, fill="#f1f5f9")
pad(110, 310, "B−", fill="#555555"); pad(390, 310, "B+", fill="#e57373")
lines(250, 338, ["PDB (power board) — stacked under the FC",
                 "FC BEC 5 V / 2 A → FC + all 4V5 pins",
                 "Servo BEC 5 V / 4 A → Vx rail (jumper: keep 5 V)",
                 "V + I sense → BATT_MONITOR 4 (board defaults)",
                 "Real pad order: B− | ESC− | ESC− | ESC+ | ESC+ | B+"], size=10.5, anchor="middle")
for x, lab, f in [(150, "ESC−", "#777"), (210, "ESC−", "#777"), (290, "ESC+", "#e57373"), (350, "ESC+", "#e57373")]:
    pad(x, 422, lab, w=40, fill=f)
text(132, 448, "pair 1", size=9, anchor="end", fill="#555")
text(368, 448, "pair 1", size=9, fill="#555")
text(250, 446, "pair 2", size=9, anchor="middle", fill="#555")
# PDB connector to FC
path([(430, 366), (560, 366)], "#475569", w=5, dash="10 6")
text(495, 356, "PDB connector", size=10, anchor="middle", fill="#475569")
text(495, 384, "(board stack)", size=10, anchor="middle", fill="#475569")
# UBEC
path([(210, 431), (210, 490)], BLK, w=3)
path([(290, 431), (290, 490)], RED, w=3)
box(180, 490, 140, 60, fill="#fff4d6")
lines(250, 512, ["UBEC 5 V", "selector at 5 V (P1)", "powers the Pi only"], size=10.5, anchor="middle")
# UBEC output -> top channel -> Pi
hop_h(180, 510, 40, 150, BLK)
path([(40, 510), (40, 108), (1150, 108), (1150, 390), (1210, 390)], BLK, w=2.5)
hop_h(180, 530, 28, 150, RED)
path([(28, 530), (28, 96), (1170, 96), (1170, 360), (1210, 360)], RED, w=2.5)
text(600, 90, "UBEC +5 V → Pi pin 2", size=10, fill=RED)
text(600, 122, "UBEC GND → Pi pin 14", size=10, fill=BLK)
# ESC + motor
path([(150, 431), (150, 620)], BLK, w=6)
path([(350, 431), (350, 620)], RED, w=6)
box(110, 620, 280, 100, fill="#eef2ff")
lines(250, 646, ["ESC (model per P1's label photo)", "thick leads → PDB ESC pair 1",
                 "signal + GND → FC S1", "red BEC wire NOT connected"], size=10.5, anchor="middle")
for x in (220, 250, 280):
    path([(x, 720), (x, 785)], BRN, w=3.5)
add('<circle cx="250" cy="830" r="48" fill="#f8fafc" stroke="#333" stroke-width="1.5"/>')
lines(250, 826, ["Motor", "(power pod)"], size=11, anchor="middle")
lines(292, 752, ["3 phase wires: any order,", "swap any 2 to reverse"], size=10, weight_first=False, fill=BRN)
text(306, 852, "PROP OFF on the bench", size=11, weight="bold", fill=HAZ)
hazard(316, 878, 7)
# ESC servo lead -> S1 (route bottom)
path([(390, 668), (500, 668), (500, 1050), (600, 1050), (600, 770)], ORG, w=3.2)
path([(390, 692), (440, 700)], RED, w=2.5)
xmark(447, 702)
text(408, 724, "BEC red: lift + insulate", size=10, fill=HAZ)
hazard(468, 684, 1)
text(508, 1072, "ESC lead → S1 (only after the output map is set and checked)", size=10, fill=ORG)

# ---------------------------------------------------------------- FC board
box(560, 290, 440, 410, fill="#1e293b", stroke="#0f172a", rx=10, sw=2)
lines(580, 330, ["CoreWing F405 Wing Mini V2 — FC board"], size=14, fill="#f8fafc")
lines(580, 352, ["ArduPlane 4.7.2 · MAV_SYSID 42 · signed MAVLink2",
                 "SERIAL4 = TELEM → Pi (MAVLink2 @ 230400)",
                 "SERIAL5 = GPS · SERIAL6 = ELRS (CRSF, default 23)",
                 "Geofence ON (Schuyler): arming off-site fails pre-arm"],
      size=11, weight_first=False, fill="#cbd5e1")
lines(580, 440, ["Output map — set by P4, checked on screen by P1",
                 "BEFORE the ESC goes on S1:",
                 "S1 ESC (SERVO1_FUNCTION 70) · S2 empty (0)",
                 "S3 L aileron (4) · S4 R aileron (4)",
                 "S5 elevator (19) · S6 rudder (21)",
                 "Reverse per servo with SERVOn_REVERSED (check in FBWA)"],
      size=11, fill="#fde68a")
hazard(566, 800, 2)
lines(580, 560, ["USB-ext connector (8-pin): RX1 BOOT0 BZ− TX1 D+ D− GND 4V5",
                 "Vx = servo rail (servo BEC) · 4V5 = FC BEC, also live on USB"],
      size=10, weight_first=False, fill="#94a3b8")
# GPS connector (top edge) + GPS module
gps_fc = [(600, "SDA"), (640, "SCL"), (680, "4V5"), (720, "GND"), (760, "TX5"), (800, "RX5")]
gps_mod = ["SDA", "SCL", "VCC", "GND", "RX", "TX"]
gps_col = [BLU, GRN, RED, BLK, AMB, AMB]
box(578, 146, 244, 70, fill="#ecfdf5")
lines(700, 166, ["RMRC SAM-M10Q GPS + 5883 compass", "wire by FUNCTION — module pad order differs"],
      size=10.5, anchor="middle")
for (x, lab), mlab, c in zip(gps_fc, gps_mod, gps_col):
    text(x, 210, mlab, size=9, anchor="middle", weight="bold")
    path([(x, 216), (x, 276)], c, w=2.5)
    box(x - 15, 276, 30, 14, fill="#5ab4e8", stroke="#1d5f8a", rx=2, sw=1)
    text(x, 287, lab, size=9, anchor="middle", weight="bold")
lines(826, 240, ["GPS TX → RX5", "GPS RX → TX5"], size=10, weight_first=False, fill="#555")
text(820, 300, "GPS connector (with compass)", size=10, fill="#94a3b8")
# WEXT SE
box(860, 146, 200, 70, fill="#f5f3ff")
lines(960, 166, ["CoreWing WEXT SE", "USB-C → laptop (Mission Planner)", "BLE / Wi-Fi module"], size=10.5, anchor="middle")
path([(930, 216), (930, 290)], "#475569", w=4)
# TELEM connector (right edge)
tel = [(350, "GND"), (385, "RX2"), (420, "TX2"), (465, "RX4"), (500, "TX4"), (535, "4V5")]
for y, lab in tel:
    box(1000, y - 7, 16, 14, fill="#5ab4e8", stroke="#1d5f8a", rx=2, sw=1)
    text(992, y + 4, lab, size=10, anchor="end", weight="bold", fill="#e2e8f0")
text(990, 330, "TELEM (GH1.25 6P)", size=10, anchor="end", fill="#94a3b8")
for y in (385, 420, 535):
    path([(1016, y), (1040, y)], GRY, w=2)
    xmark(1047, y, 5)
lines(1022, 572, ["TELEM pins 2, 3, 6 (RX2, TX2, 4V5):", "tape — NOT connected"], size=10, weight_first=False, fill=HAZ)
text(1060, 548, "4V5 never to the Pi", size=10, fill=HAZ)
hazard(1072, 382, 3)
# TELEM -> Pi
path([(1016, 350), (1110, 350), (1110, 440), (1210, 440)], BLK, w=2.5)
path([(1016, 465), (1210, 465)], AMB, w=2.5)
path([(1016, 500), (1210, 500)], AMB, w=2.5, dash="7 4")
text(1120, 459, "RX4 ← Pi TXD", size=10, fill=AMB)
text(1120, 494, "TX4 → Pi RXD", size=10, fill=AMB)
# ELRS header (bottom edge) + receiver
elrs = [(860, "T6", AMB), (895, "R6", AMB), (930, "4V5", RED), (965, "GND", BLK)]
for x, lab, c in elrs:
    text(x, 692, lab, size=9, anchor="middle", weight="bold", fill="#e2e8f0")
    pin(x, 706)
    path([(x, 711), (x, 800)], c, w=2.5)
text(912, 676, "ELRS header", size=10, anchor="middle", fill="#94a3b8")
box(842, 800, 146, 62, fill="#fff1f2")
for x, lab in [(860, "RX"), (895, "TX"), (930, "5V"), (965, "GND")]:
    text(x, 814, lab, size=9, anchor="middle", weight="bold")
lines(915, 834, ["RadioMaster XR1 Nano", "ELRS 2.4 GHz · CRSF"], size=10.5, anchor="middle")
text(915, 878, "FC T6 → RX · FC R6 ← TX", size=9.5, anchor="middle", fill="#555")
hazard(1004, 742, 6)
# receiver antenna + Pocket
path([(988, 806), (1010, 788)], "#333", w=2)
path([(1004, 782), (1016, 794)], "#333", w=2)
path([(1016, 800), (1050, 826)], PUR, w=2, dash="6 5")
box(1050, 800, 190, 72, fill="#f5f3ff")
lines(1145, 820, ["RadioMaster Pocket (pilot)", "mode switch: FBWA / AUTO / RTL", "RC7: autonomy consent"],
      size=10.5, anchor="middle")
text(1004, 862, "2.4 GHz", size=10, anchor="middle", fill=PUR)
# Servo header block (bottom edge)
cols = [(600, "S1"), (640, "S2"), (680, "S3"), (720, "S4"), (760, "S5"), (800, "S6")]
box(582, 700, 236, 72, fill="#334155", stroke="#0f172a", rx=4)
for x, lab in cols:
    text(x, 692, lab, size=10, anchor="middle", weight="bold", fill="#e2e8f0")
    for yy in (716, 738, 760):
        pin(x, yy, r=4.5)
text(826, 720, "sig", size=9, fill="#333")
text(826, 742, "Vx +", size=9, fill=RED)
text(826, 764, "G −", size=9, fill="#333")
text(640, 790, "empty", size=9, anchor="middle", fill="#555")
text(700, 676, "PWM outputs (S7–S9 unused)", size=10, anchor="middle", fill="#94a3b8")
# servo cables
srv = [
    ([(680, 772), (680, 960)], 680, "L aileron", "S3 · fn 4"),
    ([(720, 772), (720, 920), (770, 920), (770, 960)], 770, "R aileron", "S4 · fn 4"),
    ([(760, 772), (760, 905), (860, 905), (860, 960)], 860, "Elevator", "S5 · fn 19"),
    ([(800, 772), (800, 890), (950, 890), (950, 960)], 950, "Rudder", "S6 · fn 21"),
]
for pts, cx, name, sub in srv:
    path(pts, ORG, w=3.2)
    box(cx - 40, 960, 80, 48, fill="#fff7ed")
    lines(cx, 980, [f"Servo · {name}", sub], size=9.5, anchor="middle")
text(800, 1030, "plug: signal → top row · red → Vx · brown/black → G", size=10, anchor="middle", fill="#555")
text(800, 1046, "aileron leads may need extensions to reach S3/S4", size=10, anchor="middle", fill="#555")

# ---------------------------------------------------------------- Pi + camera + laptop
box(1210, 296, 260, 264, fill="#f0fdf4")
lines(1340, 318, ["Raspberry Pi Zero 2 W"], size=13, anchor="middle")
lines(1340, 336, ["capture · frameserver · mavbridge"], size=10, anchor="middle", weight_first=False, fill="#555")
for y, lab in [(360, "pin 2 · +5 V (UBEC)"), (390, "pin 14 · GND (UBEC)"), (440, "pin 6 · GND (TELEM)"),
               (465, "pin 8 · TXD GPIO14"), (500, "pin 10 · RXD GPIO15")]:
    pin(1210, y, r=4.5)
    text(1222, y + 4, lab, size=10)
lines(1222, 528, ["header pins drawn out of order", "UART: PL011 /dev/serial0 @ 230400"], size=9.5, weight_first=False,
      fill="#555")
hazard(1452, 392, 4)
# camera ribbon
add('<rect x="1335" y="560" width="16" height="66" fill="#bdbdbd" stroke="#8a8a8a"/>')
text(1360, 590, "22-pin Pi Zero ribbon", size=10, fill="#555")
text(1360, 604, "(38 or 150 mm — confirm length)", size=10, fill="#555")
box(1250, 626, 200, 62, fill="#f8fafc")
lines(1350, 648, ["Camera Module 3 (IMX708)", "nadir, recessed, foam soft-mount"], size=10.5, anchor="middle")
# laptop + wifi
box(1250, 146, 220, 76, fill="#f8fafc")
lines(1360, 166, ["Ground laptop", "core :8700 · governor :8710", "signed uplink via Pi :14560 / :14561"],
      size=10.5, anchor="middle")
path([(1400, 296), (1400, 222)], PUR, w=2, dash="6 5")
text(1408, 244, "Wi-Fi", size=10, fill=PUR)
text(1408, 258, "field hotspot", size=10, fill=PUR)
text(1408, 272, "(bench: eth 169.254.77.2)", size=9.5, fill=PUR)

# ---------------------------------------------------------------- notes (bottom-left)
box(20, 905, 460, 270, fill="#f8fafc", stroke="#94a3b8")
lines(36, 928, ["Bring-up order (prop off, P1 runs every power event)",
                "G1 cold meter checks: joints, XT60 polarity, no shorts, UBEC out open",
                "G2 first power: stack + ESC + UBEC only, ESC signal UNPLUGGED",
                "     log: pack V · FC 5 V pad 5.2±0.1 · 4V5 4.5–5.0 · Vx 5.0±0.1 · UBEC ≈5.0",
                "     (4V5 / 5 V readings also clear the wiring-incident question)",
                "Output map set + checked → ESC on S1 → receiver bound → radio cal",
                "G3 servos: FC centres, reset pushrods, throws, MANUAL + FBWA directions",
                "G3b GPS + compass (outdoor fix, compass cal) · log card in",
                "G4 Pi Zero on the UBEC + TELEM: ≥5.1 V at the Pi under camera load",
                "G5 integrated bench run → F0 ground checks → F1",
                "ESC cal + motor direction need the FC ARMED: plan around the fence (§2 #6)",
                "Servo BEC jumper: 5 V default · servo power source: servo BEC (default)",
                "Nothing on the CAM / VTX pads (Vsw = battery voltage by default)"],
      size=10.5, gap=19)

# ---------------------------------------------------------------- legend + hazards (bottom-right)
box(1030, 905, 470, 270, fill="#ffffff", stroke="#94a3b8")
text(1046, 928, "Legend", size=12, weight="bold")
leg = [(RED, 6, None, "battery + (14 AWG)"), (BLK, 6, None, "battery − (14 AWG)"),
       (RED, 2.5, None, "+5 V / supply"), (BLK, 2.5, None, "GND"),
       (AMB, 2.5, None, "UART data"), (BLU, 2.5, None, "I2C SDA"), (GRN, 2.5, None, "I2C SCL"),
       (ORG, 3.2, None, "servo/ESC lead (sig, +, −)"), (BRN, 3.5, None, "motor phases"),
       (PUR, 2, "6 5", "wireless link"), ("#475569", 5, "10 6", "board stack")]
for i, (c, w, d, lab) in enumerate(leg):
    yy = 948 + i * 19
    path([(1046, yy - 4), (1086, yy - 4)], c, w=w, dash=d)
    text(1094, yy, lab, size=10)
xmark(1066, 1160, 5)
text(1094, 1164, "do not connect", size=10)
text(1270, 928, "Hazards", size=12, weight="bold")
hz = ["ESC red BEC wire lifted: Vx is fed",
      "  by the servo BEC (ArduPilot README)",
      "Output map before ESC on S1 (now S1",
      "  = aileron centre ≈ half throttle)",
      "TELEM pins 2, 3, 6 taped (4V5!)",
      "UBEC GND not on Pi pin 6 (TELEM",
      "  GND uses it) → pin 14 / 9 / 20",
      "Cap polarity: stripe = −",
      "4V5 live on USB: unplug GPS + Pi",
      "  link, or power both boards",
      "Prop OFF; P1 owns every power event"]
n = 0
for i, s in enumerate(hz):
    yy = 948 + i * 19
    if not s.startswith("  "):
        n += 1
        hazard(1282, yy - 4, n)
    text(1300, yy, s.strip(), size=10)

add("</svg>")
svg = "\n".join(out)
dest = sys.argv[1] if len(sys.argv) > 1 else "wiring.svg"
open(dest, "w", encoding="utf-8").write(svg)
print("wrote", dest, len(svg), "bytes")
