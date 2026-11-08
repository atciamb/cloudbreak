#!/bin/bash
# Concat rendered shots (incl. the credits card), grade the active 2.39:1 area, add a short black tail,
# mux the soundtrack, then make a smaller shareable copy.
#   out/Cloudbreak_Concept_Film.mp4      master (crf 18, ~375 MB)
#   out/Cloudbreak_Concept_Film_web.mp4  share copy (crf 21, capped 9 Mb/s, ~120 MB)
set -e
cd "$(dirname "$0")/out"
ls shot_*.mp4 | grep -v part | sort > shots.txt
: > concat.txt
while read -r f; do echo "file '$PWD/$f'" >> concat.txt; done < shots.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i concat.txt -c copy film_raw.mp4

# grade: soft bloom (RGB screen blend), gentle colour balance, contrast, vignette, temporal grain
GR="crop=1920:804:0:138,format=gbrp,split[a][b];[b]curves=all='0/0 0.6/0 1/1',gblur=sigma=26[bl];[a][bl]blend=all_mode=screen:all_opacity=0.28,colorbalance=rs=-0.01:bs=0.02:rm=0.012:gm=-0.022:bm=-0.006:rh=0.028:gh=0.006:bh=-0.022,eq=contrast=1.05:saturation=0.95:gamma=0.98,vignette=angle=0.5,noise=alls=4:allf=t,format=yuv420p,pad=1920:1080:0:138:black,tpad=stop_mode=add:stop_duration=0.6:color=black"
ffmpeg -y -loglevel error -i film_raw.mp4 -i audio.wav -filter_complex "[0:v]${GR}[v]" -map "[v]" -map 1:a \
  -c:v libx264 -preset slow -crf 18 -profile:v high -pix_fmt yuv420p -r 24 \
  -c:a aac -b:a 256k -ar 48000 -movflags +faststart -shortest Cloudbreak_Concept_Film.mp4

ffmpeg -y -loglevel error -i Cloudbreak_Concept_Film.mp4 -c:v libx264 -preset slow -crf 21 -maxrate 9M -bufsize 18M \
  -profile:v high -pix_fmt yuv420p -c:a copy -movflags +faststart Cloudbreak_Concept_Film_web.mp4
for f in Cloudbreak_Concept_Film.mp4 Cloudbreak_Concept_Film_web.mp4; do
  echo "$f: $(ffprobe -v error -show_entries format=duration,size -of csv=p=0 "$f")"
done
