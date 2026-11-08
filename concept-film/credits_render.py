"""Render the end-credits card (web/credits.html) to out/shot_18_credits.mp4 so assemble.sh appends it after the film."""
import asyncio, base64, os, subprocess
from still import open_page, serve, OUT
from playwright.async_api import async_playwright

FPS = int(os.environ.get('FPS', '24'))


async def main():
    OUT.mkdir(exist_ok=True)
    srv = serve()
    try:
        async with async_playwright() as p:
            b, pg, _ = await open_page(p, 'credits.html')
            await pg.evaluate('CRED.ready')
            n = round(await pg.evaluate('CRED.DUR') * FPS)
            ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', str(FPS), '-c:v', 'mjpeg', '-i', '-',
                                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', str(FPS),
                                   str(OUT / 'shot_18_credits.mp4')], stdin=subprocess.PIPE)
            for k in range(n):
                ff.stdin.write(base64.b64decode(await pg.evaluate(f'CRED.frame({(k + 0.5) / FPS})')))
            ff.stdin.close(); ff.wait(); await b.close()
            print('credits frames', n)
    finally:
        srv.terminate()

asyncio.run(main())
