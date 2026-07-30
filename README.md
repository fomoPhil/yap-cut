# yap-cut

**Turn a long, rambling talking-head recording into a tight vertical cut — automatically, in DaVinci Resolve.**

An [Agent Skill](https://code.claude.com/docs/en/skills) for Claude Code. Point an LLM agent at a 9-minute selfie video; get back a 79-second TikTok-ready cut with the silences, repeats, false starts and stray "ums" removed, neutrally colour-corrected, exported at whatever file size you need.

```
8:46 raw recording  ──▶  1:19 cut, 21 clips, 0 gaps, colour-corrected, 48 MB
```

---

## At a glance

|  |  |
|---|---|
| **What it does** | Silence removal, repeat/mistake removal, neutral colour correction, size-targeted export |
| **What it drives** | DaVinci Resolve **Studio** via the [davinci-resolve MCP](https://github.com/samuelgursky/davinci-resolve-mcp) |
| **Core idea** | The **transcript** decides *what* to keep. The **waveform** decides *where* to cut. |
| **Deliberately excluded** | Stylised / "cinematic" grading. Neutral correction only. |
| **Needs** | Resolve Studio, `whisper`, `ffmpeg`, Python + `numpy` + `pillow` |
| **Tested on** | 8:46 / 4K vertical / 24fps iPhone recording, Resolve Studio 21.0.3.7, macOS |

### The one non-obvious thing

**Transcript word timestamps lie about pauses.** Whisper reported a `0.00s` gap after an "um" where the audio held **1.02 seconds of dead silence**. Any tool that trims silence using transcript timings will sail straight past it. This skill measures the actual waveform for every cut boundary. That single decision is most of why it works.

### Why an agent, not a one-shot script

Deciding that `"and if I have certain projects"` is a false start for `"and if I have certain projects coming out"` is a language judgement. Deciding that the pause after it is 1.02 seconds is a measurement. This skill splits those: the agent reads the transcript and picks what goes; the bundled scripts do the measuring, frame math, and colour analysis deterministically.

---

## Install

Clone into your Claude Code skills directory:

```bash
git clone https://github.com/fomoPhil/yap-cut.git ~/.claude/skills/yap-cut
```

Then check the prerequisites:

```bash
whisper --help >/dev/null && echo "whisper ok"
ffmpeg -version | head -1
python3 -c "import numpy, PIL; print('numpy + pillow ok')"
```

DaVinci Resolve **Studio** must be running with external scripting enabled
(`Preferences → General → External scripting using → Local`) and the
[davinci-resolve MCP server](https://github.com/samuelgursky/davinci-resolve-mcp) connected.
The free edition of Resolve does not permit external scripting.

## Use

Just ask. The skill triggers on requests like:

- *"Cut this down and remove the silences"*
- *"Make a 90-second version of this for TikTok"*
- *"Remove the parts where I repeat myself or mess up"*
- *"Colour correct this, the white balance looks off"*
- *"Export a version small enough to text someone"*

---

## What's in the box

```
yap-cut/
├── SKILL.md                            8-step workflow the agent follows
├── scripts/
│   ├── prep_audio.sh                   extract audio + whisper transcript
│   ├── build_cut.py                    ★ waveform-measured cut list
│   ├── color_correct.py                measure colour cast → CDL; verify a render
│   └── finalize_export.sh              fix Resolve's audio, size for delivery
└── references/
    ├── resolve-mcp-recipes.md          exact MCP calls + API traps
    └── editorial-rules.md              what to cut, thresholds, colour limits
```

`build_cut.py` is the heart of it. Everything else supports it.

---

## How it works

```
  source video
       │
       ├─ prep_audio.sh ──▶ mono 16k wav ──▶ whisper ──▶ transcript.json
       │                          │
       │                          ▼
       │              agent reads the transcript and writes plan.json
       │              (which segments are repeats / mistakes / filler)
       │                          │
       ▼                          ▼
  build_cut.py ◀── measures the wav with silencedetect ──┐
       │           • real speech onsets and offsets       │
       │           • splits only on genuine dead air      │
       │           • drops stranded filler words          │
       │           • padding capped at ½ the closed gap   │
       ▼                                                  │
  clip_infos.json  ──▶ Resolve create_timeline_from_clips │
       │                          │                       │
       │                   detect_gaps_overlaps ──────────┘
       │                   (must be 0 / 0)
       ▼
  color_correct.py measure ──▶ ASC CDL ──▶ applied to every clip
       │
       ▼
  Resolve render ──▶ finalize_export.sh ──▶ delivery file
```

### The plan file

The agent's editorial decisions are captured in one small JSON file. Two forms:

```json
{"mode": "full",  "drop": [13, 15, 32, 46, 47]}
```
Keep every transcript segment except these. For a long, watchable cut.

```json
{"mode": "spine", "spine": [[0,null], [1,null], [19,[0,5]], [21,[0,11]]]}
```
Keep only these segments, **in this order**. `[0,5]` slices the segment's words so a
kept thought can end cleanly mid-segment. For a short, structured cut — and because
order is explicit, the agent can re-sequence the story rather than just trim it.

### Tuned defaults, and why

| Setting | Default | Reasoning |
|---|---|---|
| `--split-gap` | `0.55` | Cut pauses longer than this. Below ~0.45 it slices *between words inside sentences* and sounds machine-gunned. |
| `--head-pad` / `--tail-pad` | `0.05` / `0.09` | Enough to preserve consonants at the cut. |
| padding cap | ½ the closed gap | Padding can never re-open the silence just removed. |
| `--noise` | `-36dB` | Speech floor for indoor handheld audio. |
| filler drop | `<0.55s` chunk + `>0.40s` gap behind it | The signature of a stranded "um". |

**Match the threshold to the job.** Measured on one 8:46 source:

| `--split-gap` | Clips | Duration | Use for |
|---|---|---|---|
| `0.55` | 92 | 307.7s | Short punchy cut (with `mode: spine`) |
| `0.70` | 72 | 318.6s | |
| `0.90` | 55 | 330.5s | |
| `1.20` | 46 | 340.4s | Long watchable cut (`mode: full`) |

A 0.55s threshold is right when every beat must land in 90 seconds. It is too
aggressive for a five-minute version someone actually sits through.

### Colour correction

`color_correct.py measure` samples ten frames, isolates the genuinely neutral
surfaces (grey shirt, concrete, painted wall — low-saturation midtones), and measures
how far off-neutral they are. On the test footage: **red 13% hot against green**, from
warm indoor lighting.

It then emits ASC CDL values that:

- correct **80% of the way** to neutral by default — going all the way makes indoor skin look clinical
- **rescale slope to hold luminance constant**, because pulling red down to neutralise a warm cast dims the whole image
- pull the black point down slightly, weighted toward red, since warm lifted shadows are the worst offender

Verified end to end on a real render:

| | Before | After |
|---|---|---|
| Neutral R/G (1.000 = neutral) | 1.134 | **1.047** |
| Neutral B/G | 0.993 | **1.000** |
| Mean luma | 0.439 | **0.438** |
| Clipped highlights | 0.054% | 0.036% |

It works in both directions — given footage with a *cool* cast (R/G 0.908) it correctly warms it.

**Stylised grading is out of scope, and here is the measured reason.** On handheld
indoor footage, whites already sit near 0.96, so there is no highlight headroom:
saturation 1.20 clipped **4.4%** of highlights, 1.27 clipped **15%**, and skin read
sunburnt well before that. A gamma-led approach does not rescue it — it came out
darker *and* flatter. Contrast is the lever with room; saturation is not.

### Export sizing

```
total_kbps = target_MB * 8192 / duration_seconds
```

| Target | Settings | Good for |
|---|---|---|
| ~50 MB | 5000 kbps @ 1080x1920 | Upload to TikTok (it re-encodes anyway; give it a rich source) |
| ~10 MB | 900 kbps @ 1080x1920 | iMessage, RCS, WhatsApp, Signal, email |
| ~3 MB | 250 kbps @ 540x960 | Strict carrier MMS |

`finalize_export.sh` then does what Resolve won't: **Resolve writes 320 kbps AAC by
default**, roughly triple what one voice needs. The script re-encodes audio only and
**copies the video stream untouched** — verified by identical decoded-video MD5 before
and after, so the picture takes zero extra compression passes. It also strips the
stray iPhone data stream and adds `+faststart`.

---

## Resolve API traps

Every one of these returns `success: true` while producing wrong output. Full detail in
[`references/resolve-mcp-recipes.md`](references/resolve-mcp-recipes.md).

| Trap | Consequence | Guard |
|---|---|---|
| **`end_frame` in `clip_infos` is EXCLUSIVE** | Every clip lands one frame short → **1-frame black flash at every cut** | Always run `timeline.detect_gaps_overlaps`, require `gap_count: 0` |
| `safe_set_project_settings` defaults to probe mode | Writes, reads back, then **reverts** | Pass `restore: false` |
| `safe_*` actions reject non-`_mcp_` names | Call fails | Pass `allow_non_mcp_name: true` |
| Timeline frame rate locks after the first timeline | Wrong fps for the whole project | Set fps *before* creating any timeline |
| Timeline items have **no duration control** | Per-clip title bars are impossible | Put Text+ in each clip's own Fusion comp; it inherits clip length |
| iPhone spatial audio → **5 audio tracks** | Duplicate voice layered in the export | Mute A2–A5, and again on every new timeline |
| Resolve's own transcription | Fails in ~3ms with no explanation when the speech model was never downloaded | Download once from the Resolve GUI, or transcribe externally (what this skill does) |

---

## Reproducibility

`build_cut.py` was validated by replaying the real editorial plan from the session it
was extracted from. It reproduces the shipped 21-clip / 1908-frame cut **exactly,
frame for frame**, including identifying precisely the two stranded filler words a
human reviewer had flagged by ear.

An earlier revision that measured each transcript segment in its own window produced
33 clips and fired the filler heuristic five times, three of them eating real words.
Merging source-contiguous segments before measuring fixed it. The regression is worth
knowing about if you modify the measurement stage.

---

## Limitations

- **Resolve Studio only.** The free edition blocks external scripting entirely.
- **English defaults.** `prep_audio.sh` passes `--language en`; change it for other languages.
- **Single speaker assumed.** No diarisation; two-person interviews are out of scope.
- **Transcription is the slow step.** Several minutes for ~9 minutes of audio on CPU. Run it in the background while the Resolve project is set up.
- **Cuts are hard cuts.** No transitions, no b-roll, no captions burned in by default (the recipes reference does document the Fusion Text+ approach if asked).
- **Playback is the final judge.** Zero gaps and good numbers do not prove a specific cut sounds natural.

## License

MIT
