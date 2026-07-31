---
name: yap-cut
description: Turn a long talking-head "yap" recording into a tight, vertical, TikTok-ready cut in DaVinci Resolve - removing silences, repeats, false starts and filler, then applying neutral colour correction and exporting at a target file size. This skill should be used when asked to cut down a selfie/talking-head video, remove silences or "ums", make a rambling recording postable, build a 60-90 second version of a long take, colour-correct handheld indoor footage, or export a video sized for texting or upload. Covers neutral white-balance correction only, not stylised or dramatic grading.
---

# Yap Cut

## Overview

Converts a long single-take talking-head recording into postable vertical cuts using
the `davinci-resolve` MCP server. The transcript decides what to keep; the audio
waveform decides where the cuts land. Produces a Resolve project with a raw reference
timeline, cut timelines, neutral colour correction, and delivery exports at requested
file sizes.

**Default deliverable is BOTH cuts**, exported as two files:

1. **Short** (`mode: spine`, `--split-gap 0.55`): a 60-90 second restructured
   scroll-stopper. This is the post.
2. **Full** (`mode: full`, `--split-gap 1.0-1.2`): the whole story with silences,
   repeats, and dead tangents removed but the source order kept.

Build one instead of both only when the user explicitly asks for a single version
(e.g. "just the short one", "only clean it up, don't restructure").

Scope is **neutral colour correction** - white balance, a touch of contrast, and
enough saturation to replace what neutralising removes. Stylised or "dramatic" looks
are deliberately out of scope; see the ceiling documented at the end of
`references/editorial-rules.md` if asked to push further.

## Prerequisites

Confirm before starting:

- **DaVinci Resolve Studio** running, with the `davinci-resolve` MCP server connected.
  External scripting must be Local (`System.Scripting.Mode = 1`).
- `whisper` CLI on PATH, plus `ffmpeg`/`ffprobe`, `numpy`, `pillow`.
- Read `references/resolve-mcp-recipes.md` **before the first Resolve call**. It
  documents traps that return `success: true` while producing broken output.

## Workflow

Work in a scratch directory. Defaults: 1080x1920 at 24fps for TikTok, and **both cut
versions** (short + full, per Overview). Ask only if aspect/resolution or delivery
size is unclear; do not ask which version to build - both is the default.

### 1. Probe the source

```bash
ffprobe -v error -show_entries stream=index,codec_type,codec_name,width,height,r_frame_rate \
        -show_entries format=duration -of default=nw=1 <source>
ffprobe -v error -select_streams v:0 -show_entries stream_side_data=rotation \
        -of default=nw=1 <source>
```

Note the frame rate (it must match the timeline), the `rotation` flag (iPhone vertical
footage is stored landscape with `rotation=-90`; Resolve honours it, so no correction
is needed), and how many audio streams exist.

### 2. Start transcription, then set up Resolve while it runs

```bash
scripts/prep_audio.sh <source> <work-dir>
```

This is the slow step (several minutes for ~9 minutes of audio). Run it in the
background and do step 3 in parallel. Do **not** rely on Resolve's own transcription
without checking - it fails silently on machines where the speech model was never
downloaded from the GUI (see the recipes reference).

### 3. Create the project and a raw timeline

Follow sections 1 and 2 of `references/resolve-mcp-recipes.md`. Set frame rate and
resolution **before** creating any timeline. Build a `YAP raw` timeline of the whole
clip as an untouched reference, and mute the extra iPhone spatial-audio tracks.

### 4. Read the transcript and choose the cuts

Print every segment with its index and timings, then read all of it:

```bash
python3 -c "import json,sys;[print(f'[{i:3d}] {s[\"start\"]:7.2f}-{s[\"end\"]:7.2f}  {s[\"text\"].strip()}') for i,s in enumerate(json.load(open(sys.argv[1]))['segments'])]" <work-dir>/tx/yap.json
```

Apply `references/editorial-rules.md` to pick removals. Write one plan file per
deliverable (both, by default):

```json
// plan_full.json - full story, source order, dead air and tangents dropped
{"mode": "full", "drop": [13, 15, 32, 46, 47]}
```

```json
// plan_short.json - 60-90s restructured spine
{"mode": "spine", "spine": [[0,null], [1,null], [19,[0,5]], [21,[0,11]]]}
```

Then print the kept text joined end to end and confirm every join lands on a complete
thought before building anything.

### 5. Build the cut list from the waveform

```bash
scripts/build_cut.py --transcript <work>/tx/yap.json --audio <work>/yap.wav \
  --plan plan.json --clip-id <resolve-clip-id> --fps 24 --out clip_infos.json
```

Run once per plan file. Match `--split-gap` to the cut: **0.55** for the tight 60-90s
short, **1.0-1.2** for the full watchable version so the delivery still breathes. Heed
the report - any clip under 0.5s means the threshold is too tight; rebuild at the value
the warning names rather than shipping a machine-gunned edit.

### 6. Create the cut timeline and verify

For each cut, pass its `clip_infos.json` to `media_pool.create_timeline_from_clips`
(e.g. timelines `_mcp_short` and `_mcp_full`), then **always**, per timeline:

- `timeline.detect_gaps_overlaps` must return `gap_count: 0, overlap_count: 0`
- `timeline.get_current`: `end_frame - start_frame` must equal the expected frames
- mute audio tracks 2-5 again (track state does not survive into a new timeline)

Skipping the gap check risks shipping a one-frame black flash at every cut.

### 7. Neutral colour correction

```bash
scripts/color_correct.py measure --source <source> --out cdl.json
```

Apply the CDL to clip 0 with `timeline_item_color.safe_set_cdl`, then to every other
clip (per-index calls, or `safe_copy_grade` with target ids) - on **both** cut
timelines. Render, then verify measurably rather than by eye:

```bash
scripts/color_correct.py verify --before ungraded.mp4 --after graded.mp4 --sheet compare.png
```

Expect neutral R/G to move toward 1.00 while stopping short of it, luma to hold within
~0.005, and clipping not to increase.

### 8. Export

Render both timelines from Resolve per section 5 of the recipes reference (name the
files `<source>_short.mp4` and `<source>_full.mp4`), then per file:

```bash
scripts/finalize_export.sh <resolve-render.mp4> <delivery.mp4> 96
```

Bitrate for a size target: `total_kbps = target_MB * 8192 / duration_seconds`.
Common targets are listed in the script's output. Resolve writes 320 kbps audio by
default, which `finalize_export.sh` fixes while copying the video stream untouched.

## Reporting back

For **each** delivered file, state the before/after duration, the clip count, that gaps verified at zero, and
**each judgement call made** - lines kept that arguably were mistakes, repetition left
in as deliberate emphasis, and anything dropped purely to hit a length target. Note
that only playback can settle whether a specific cut sounds clipped.

## References

- `references/resolve-mcp-recipes.md` - exact MCP call sequences, API traps, captions
- `references/editorial-rules.md` - what to cut, thresholds, spine structure, colour limits
