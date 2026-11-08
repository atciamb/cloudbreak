"""Time a few frames of given shots:  python bench.py establish final   (uses FILMQS like render.py)"""
import asyncio, os, sys, time
os.environ.setdefault("FILMQS", "?rs=0.8333")
from still import open_film, serve  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402


async def main():
    srv = serve()
    try:
        async with async_playwright() as p:
            b, pg, logs = await open_film(p)
            shots = {s['id']: s for s in await pg.evaluate("FILM.shots()")}
            for sid in sys.argv[1:]:
                s = shots[sid]; tt = []; ms = []
                for k in range(8):
                    ft = s['start'] + 1.0 + k / 30
                    t = time.time(); r = await pg.evaluate(f"FILM.frame({ft})"); tt.append(time.time() - t); ms.append(r['cue']['ms'])
                print(sid, 'total %.2f s/frame' % (sum(tt[2:]) / 6), 'scene %.0f ms' % (sum(ms[2:]) / 6), r['cue'].get('prof'))
            await b.close()
    finally:
        srv.terminate()

asyncio.run(main())
