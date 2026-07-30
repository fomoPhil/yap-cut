# Editorial rules for cutting a yap video

What to remove, how tight to cut, and where the judgement calls are. Tuned on real
footage; the numbers here are defaults that produced an accepted cut, not guesses.

## Division of labour: transcript vs waveform

**The transcript decides WHAT to cut. The waveform decides WHERE.**

Whisper is accurate on real words and unreliable on filler sounds, which is exactly
where the pauses live. Observed on real footage: whisper reported a **0.00s** gap
after an "um" where the audio contained **1.02 seconds of dead silence**. A gap
filter reading transcript timings sailed straight past it and the dead air shipped.

So never derive cut points from `word.start` / `word.end`. Use the transcript to pick
segments, then let `scripts/build_cut.py` measure the actual speech boundaries with
`silencedetect`.

## Thresholds

| Setting | Default | Why |
|---|---|---|
| `--split-gap` | **0.55s** | Cut internal pauses longer than this. |
| `--head-pad` / `--tail-pad` | 0.05 / 0.09s | Enough to keep consonants intact. |
| padding cap | half the closed gap | Padding can never re-open the silence just removed. |
| `--noise` | -36dB | Speech floor for indoor handheld recordings. |
| filler drop | <0.55s chunk + >0.40s gap behind it | Signature of a stranded "um". |

**Do not drop `--split-gap` below about 0.45s.** At 0.34s it starts slicing *between
words inside sentences*: a 79s cut ballooned from 21 clips to 27 with five under half
a second, and it reads as machine-gunned - the first thing a reviewer objects to. Median
clip length around 3.5s is healthy. **If any clip comes out under 0.5s, the threshold
is too tight** - `build_cut.py` warns about this and names the value to retry.

### Match the threshold to the cut's job

Measured on one 8:46 source, keeping all substantive content:

| `--split-gap` | Clips | Result | Use for |
|---|---|---|---|
| 0.55s | 92 | 307.7s, 2 clips under 0.5s | **Short punchy cut** (with `mode: spine`) |
| 0.70s | 72 | 318.6s, 1 under 0.5s | |
| 0.90s | 55 | 330.5s, 1 under 0.5s | |
| 1.20s | 46 | 340.4s, none under 0.5s | **Long watchable cut** (`mode: full`) |

A tight 0.55s is right for a 60-90s scroll-stopper where every beat must land. It is
too aggressive for a 5-minute version someone actually sits through - use **1.0-1.2s**
there, so only obvious dead air goes and the delivery still breathes.

## What to remove

Read the full transcript before choosing. Removable, in rough order of confidence:

1. **Explicit self-corrections.** "how should I say this", "let me try that again",
   and the abandoned sentence immediately before them. Cut both.
2. **Repeated lines.** When a phrase is said twice with the second attempt extending
   it, cut the *first* instance if the second is cleaner, otherwise the second.
3. **False starts.** A fragment that restarts as a fuller version of itself
   ("and if I have certain projects" -> "and if I have certain projects coming out").
4. **Stranded filler.** A standalone "um" / "uh" / "like" as its own segment, or one
   with real dead air behind it. `build_cut.py` catches the timed ones automatically.
5. **Orphans created by the above.** Removing a stumble can leave a dangling
   fragment ("out of the bottle" with nothing before it). Re-read the joined text.

**Leave alone:** filler that flows straight into the sentence with no pause behind
it (reads as human, not as a mistake), and repetition that functions as deliberate
emphasis ("it's sick, it's so sick"). Flag these rather than cutting them silently.

## Phrase boundaries

Whisper segments break mid-thought. A segment can end on "there's a little" with
"magic there" starting the next one. **After choosing segments, read the joined text
end to end** and check every join lands on a complete thought. Use the word-slice
form in the plan (`[21, [0, 11]]`) to end a kept segment cleanly rather than
including a whole trailing segment.

## Verifying the edit without watching it

Print the kept transcript in order and read it. Every removal should be justifiable
and no join should read as broken. This catches orphans and mid-phrase truncation
that the numbers cannot.

## Building a short version

For a scroll-stopping 60-90s cut from a long ramble, use `"mode": "spine"` and select
for structure rather than trimming evenly:

**hook -> urgency -> proof -> tip -> argument -> close.**

Prefer a self-deprecating or surprising opener, keep anything time-sensitive early,
keep one concrete piece of evidence, and end on the strongest single line. Order the
spine for narrative, not source order - `build_cut.py` handles out-of-order source
ranges. Backward jumps in a static talking-head read as ordinary jump cuts, but say
so, since only playback settles whether they feel jarring.

State plainly what was dropped to hit the target length.

## Colour: correction only

This skill does neutral correction, **not** a stylised look. Measure the real neutral
surfaces (grey shirt, concrete, painted wall) and remove the cast.

**Leave 15-25% of the warmth in** (`--strength 0.8`). Correcting fully to R/G 1.000
makes indoor skin look clinical. **Hold luma constant**: neutralising a warm cast
pulls red down and dims the whole image, so the slope needs rescaling afterwards -
`color_correct.py` does this and verification should show before/after luma within
about 0.005.

If asked for something more dramatic, note the ceiling found on real footage: global
saturation above about 1.15 makes skin read sunburnt, and because handheld indoor
whites already sit near 0.96 there is no highlight headroom - saturation 1.20 clipped
4.4% of highlights and 1.27 clipped 15%. A gamma-led approach does not rescue this;
it came out darker and flatter. Contrast is the lever with room; saturation is not.
