#!/usr/bin/env bash
# Post-process a Resolve export for delivery.
#
#   finalize_export.sh <resolve-render.mp4> <output.mp4> [audio-kbps]
#
# Does three things Resolve's render does not:
#   1. Re-encodes audio to a sane bitrate. Resolve writes 320 kbps AAC by default,
#      roughly 3x what a single voice needs. On a 90s clip that wastes ~2 MB.
#   2. Copies the video stream untouched, so the picture takes zero extra
#      compression passes.
#   3. Strips the stray iPhone data stream and adds +faststart so the file starts
#      playing before it finishes downloading.
set -euo pipefail

IN="${1:?usage: finalize_export.sh <in.mp4> <out.mp4> [audio-kbps]}"
OUT="${2:?usage: finalize_export.sh <in.mp4> <out.mp4> [audio-kbps]}"
ABR="${3:-96}"

HAS_AUDIO=$(ffprobe -v error -select_streams a -show_entries stream=index \
              -of csv=p=0 "$IN" | head -1)

if [ -n "$HAS_AUDIO" ]; then
  ffmpeg -y -v error -i "$IN" -map 0:v:0 -map 0:a:0 \
    -c:v copy -c:a aac -b:a "${ABR}k" -movflags +faststart "$OUT"
else
  echo "note: input has no audio stream; writing video only"
  ffmpeg -y -v error -i "$IN" -map 0:v:0 -c:v copy -movflags +faststart "$OUT"
fi

python3 - "$IN" "$OUT" <<'EOF'
import os, subprocess, sys
def info(p):
    v = subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
        "stream=width,height,bit_rate","-of","csv=p=0",p],capture_output=True,text=True).stdout.strip()
    d = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","csv=p=0",p],capture_output=True,text=True).stdout.strip()
    return os.path.getsize(p)/1024/1024, v, float(d)
for label, p in (("in ", sys.argv[1]), ("out", sys.argv[2])):
    mb, v, d = info(p)
    print(f"  {label} {os.path.basename(p):34s} {mb:7.2f} MB  {v}  {d:.1f}s")
EOF

cat <<'NOTE'

Sizing a delivery, for a 79.5s clip:
  total kbps = target_MB * 8192 / duration_seconds
  ~50 MB  -> ~5000 kbps video + 96 audio
  ~10 MB  ->  ~900 kbps video + 96 audio   (safe for iMessage / RCS / WhatsApp)
  ~3 MB   ->  ~250 kbps video + 64 audio at 540x960 (clears strict carrier MMS)
Set the video bitrate in Resolve via render setting VideoQuality (kbps) with
MultiPassEncode true, so the picture is encoded once from source.
NOTE
