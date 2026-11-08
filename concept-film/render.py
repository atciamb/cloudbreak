"""Render the film shot by shot (resumable).

Writes out/shot_XX_<id>.mp4 plus out/cues.json + out/meta.json (timing/events the soundtrack is built from).
A finished shot is skipped on the next run; pass shot ids to force re-rendering just those:
    python render.py                 # everything not yet rendered
    python render.py pilot pullback  # only these shots
Env: FPS (default 24), FILMQS (default "?rs=0.8333" = render at 83% scale, upscaled), see still.py for the rest.
"""
import asyncio, base64, json, os, subprocess, sys, time

os.environ.setdefault("FILMQS", "?rs=0.8333")
from still import open_film, serve, OUT  # noqa: E402  (FILMQS must be set first)
from playwright.async_api import async_playwright  # noqa: E402

OUT.mkdir(exist_ok=True)
ONLY = set(sys.argv[1:])
FPS = int(os.environ.get('FPS', '24'))


async def main():
    srv = serve()
    log = open(OUT / 'render.log', 'a')
    try:
        async with async_playwright() as p:
            b, pg, logs = await open_film(p)
            shots = await pg.evaluate("FILM.shots()")
            total = round(sum(s['dur'] for s in shots) * 30)
            cues = await pg.evaluate(f"FILM.cues({total})")  # cues are always sampled at 30 Hz
            json.dump(dict(shots=shots, events=await pg.evaluate("FILM.events()"), total=total), open(OUT / 'meta.json', 'w'))
            json.dump(cues, open(OUT / 'cues.json', 'w'))
            for i, s in enumerate(shots):
                fn = str(OUT / f"shot_{i:02d}_{s['id']}.mp4")
                if (ONLY and s['id'] not in ONLY) or (not ONLY and os.path.exists(fn)):
                    continue
                n = round(s['dur'] * FPS); tmp = fn.replace('.mp4', '.part.mp4')
                ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', str(FPS), '-c:v', 'mjpeg', '-i', '-',
                                       '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', str(FPS), tmp], stdin=subprocess.PIPE)
                t0 = time.time()
                for k in range(n):
                    ft = s['start'] + (k + 0.5) / FPS
                    r = await pg.evaluate(f"FILM.frame({ft})")
                    ff.stdin.write(base64.b64decode(r['jpg']))
                    if k % 24 == 0:
                        print(f"{s['id']} {k}/{n} {time.time() - t0:.0f}s", file=log, flush=True)
                ff.stdin.close(); rc = ff.wait()
                if rc == 0:
                    os.replace(tmp, fn)
                    msg = f"DONE {s['id']} {n} frames in {time.time() - t0:.0f}s ({(time.time() - t0) / n:.2f}s/f)"
                else:
                    msg = f"FAIL {s['id']} rc={rc}"
                print(msg, file=log, flush=True); print(msg)
            errs = [l for l in logs if 'error' in l.lower() and '404' not in l]
            if errs: print("ERRORS", errs[-10:], file=log, flush=True)
            print("ALL DONE", file=log, flush=True)
            await b.close()
    finally:
        srv.terminate()

asyncio.run(main())
