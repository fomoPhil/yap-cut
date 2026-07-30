#!/usr/bin/env bash
# Extract a transcription-ready audio track and transcribe it with word timestamps.
#
#   prep_audio.sh <source-video> <work-dir> [model]
#
# Produces:
#   <work-dir>/yap.wav        mono 16k PCM (what build_cut.py measures)
#   <work-dir>/tx/yap.json    whisper transcript with word timestamps
#
# Transcription of ~9 min on CPU takes several minutes. Run it in the background
# and do the Resolve project setup while it works.
set -euo pipefail

SRC="${1:?usage: prep_audio.sh <source-video> <work-dir> [model]}"
WORK="${2:?usage: prep_audio.sh <source-video> <work-dir> [model]}"
MODEL="${3:-large-v3-turbo}"

mkdir -p "$WORK/tx"

# -map 0:a:0 takes the normal stereo track. iPhone spatial-audio files carry extra
# multichannel streams that ffmpeg will otherwise pick up.
echo "extracting audio..."
ffmpeg -y -v error -i "$SRC" -map 0:a:0 -ac 1 -ar 16000 -c:a pcm_s16le "$WORK/yap.wav"
ls -lh "$WORK/yap.wav"

echo "transcribing with $MODEL (this is the slow step)..."
cd "$WORK"
whisper yap.wav --model "$MODEL" --language en --word_timestamps True \
  --output_format json --output_dir "$WORK/tx" --fp16 False

echo "done: $WORK/tx/yap.json"
python3 - "$WORK/tx/yap.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
segs = d["segments"]
print(f"{len(segs)} segments, {sum(len(s.get('words',[])) for s in segs)} words, "
      f"{segs[-1]['end']:.1f}s covered")
print("\nRead the whole transcript before choosing cuts:")
print("  python3 -c \"import json;[print(f'[{i:3d}] {s[\\\"start\\\"]:7.2f}-{s[\\\"end\\\"]:7.2f}  "
      "{s[\\\"text\\\"].strip()}') for i,s in enumerate(json.load(open('tx/yap.json'))['segments'])]\"")
EOF
