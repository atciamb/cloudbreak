"""Shared browser/server helpers + still renderer for review.

Usage:  python still.py <out_prefix> <t1> <t2> ...      (film seconds)
        python still.py <out_prefix> @shot[:frac] ...   (e.g. @touchdown:0.56)

Env:
  FILMQS      query string passed to film.html (render.py defaults to "?rs=0.8333")
  CHROME_PATH path to a Chrome/Chromium binary (default: Playwright's bundled Chromium)
  FILM_GPU=1  use the machine's GPU instead of SwiftShader (much faster if you have one)
  FILM_PORT   local HTTP port (default 8765)
"""
import asyncio, base64, os, subprocess, sys, time
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
OUT = ROOT / "out"
PORT = int(os.environ.get("FILM_PORT", "8765"))
QS = os.environ.get("FILMQS", "")
ARGS = ["--no-sandbox", "--ignore-gpu-blocklist", "--disable-web-security"]
if os.environ.get("FILM_GPU") != "1":
    ARGS += ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def serve():
    """Static server for web/ (the page loads JSON/textures and three.js modules over HTTP)."""
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"], cwd=WEB,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    return srv


async def launch(p):
    exe = os.environ.get("CHROME_PATH")
    return await p.chromium.launch(executable_path=exe, args=ARGS) if exe else await p.chromium.launch(args=ARGS)


async def open_page(p, page):
    b = await launch(p)
    pg = await b.new_page(viewport={"width": 1920, "height": 1080})
    logs = []
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    pg.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    await pg.goto(f"http://127.0.0.1:{PORT}/{page}")
    return b, pg, logs


async def open_film(p):
    b, pg, logs = await open_page(p, "film.html" + QS)
    t = time.time()
    st = [False, None]
    while time.time() - t < 240:
        st = await pg.evaluate("[window.READY===true, window.ERR||null]")
        if st[0] or st[1]:
            break
        await asyncio.sleep(0.5)
    if not st[0]:
        print("INIT FAILED", st[1]); print("\n".join(logs[-30:])); raise SystemExit(1)
    print(f"init {time.time() - t:.1f}s")
    return b, pg, logs


async def main():
    prefix = sys.argv[1]
    srv = serve()
    try:
        async with async_playwright() as p:
            b, pg, logs = await open_film(p)
            shots = await pg.evaluate("FILM.shots()")
            sid = {s['id']: s for s in shots}
            times = []
            for a in sys.argv[2:]:
                if a.startswith('@'):
                    name, _, frac = a[1:].partition(':'); s = sid[name]; times.append(s['start'] + s['dur'] * float(frac or 0.5))
                else:
                    times.append(float(a))
            for ft in times:
                t = time.time()
                r = await pg.evaluate(f"FILM.frame({ft})")
                fn = f"{prefix}_{ft:07.2f}.jpg"
                Path(fn).parent.mkdir(parents=True, exist_ok=True)
                open(fn, 'wb').write(base64.b64decode(r['jpg']))
                print(f"{fn} {time.time() - t:.2f}s shot={r['cue']['shot']} mt={r['cue']['mt']:.2f}")
            errs = [l for l in logs if 'error' in l.lower() and '404' not in l]
            if errs: print("\n".join(errs[-15:]))
            await b.close()
    finally:
        srv.terminate()


if __name__ == "__main__":
    asyncio.run(main())
