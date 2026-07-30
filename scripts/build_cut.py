#!/usr/bin/env python3
"""Build a Resolve clip_infos cut list from a transcript plus waveform measurement.

The transcript decides WHAT to keep (meaning). The waveform decides WHERE to cut
(timing). Transcript word timestamps under-report pauses around filler words, so
every boundary emitted here is derived from measured audio, never from the
transcript's own timings.

Usage:
  build_cut.py --transcript tx/yap.json --audio yap.wav --plan plan.json \
               --clip-id <resolve-media-pool-clip-id> --fps 24 --out clip_infos.json

plan.json is one of:
  {"mode": "full",  "drop": [13, 15, 32]}
      Keep every transcript segment except these indices. Use for the long cut.
  {"mode": "spine", "spine": [[0,null], [1,null], [19,[0,5]], [21,[0,11]]]}
      Keep only these segments, in this order. [start,end] slices the segment's
      words (Python slice semantics) to end a thought cleanly mid-segment.

Emits clip_infos JSON (end_frame is EXCLUSIVE - see references/resolve-mcp-recipes.md)
and prints a report to stderr.
"""
import argparse, json, re, subprocess, sys, statistics


def silences(audio, a, b, pad, noise, min_sil):
    """Measured silence ranges inside [a-pad, b+pad] of `audio`, in absolute seconds."""
    start = max(0.0, a - pad)
    dur = (b + pad) - start
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", f"{start}", "-t", f"{dur}", "-i", audio,
         "-af", f"silencedetect=noise={noise}:d={min_sil}", "-f", "null", "-"],
        capture_output=True, text=True)
    st = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", p.stderr)]
    en = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", p.stderr)]
    out = []
    for i, s in enumerate(st):
        e = en[i] if i < len(en) else dur
        out.append((start + s, start + e))
    return out, start, start + dur


def measured_speech(audio, a, b, args):
    """Real speech runs inside a candidate range, split on genuine dead air."""
    sil, w0, w1 = silences(audio, a, b, args.window_pad, args.noise, args.min_silence)
    segs, cur = [], w0
    for s, e in sil:
        if s > cur:
            segs.append((cur, s))
        cur = max(cur, e)
    if cur < w1:
        segs.append((cur, w1))
    segs = [(x, y) for x, y in segs if y - x >= args.min_keep]
    if not segs:
        return []
    grouped = [list(segs[0])]
    for x, y in segs[1:]:
        if x - grouped[-1][1] <= args.split_gap:
            grouped[-1][1] = y          # natural speech rhythm, keep as one clip
        else:
            grouped.append([x, y])      # genuine dead air, becomes a cut
    # A short leading chunk trailed by a real pause is a stranded filler ("um" + beat).
    if (len(grouped) > 1
            and grouped[0][1] - grouped[0][0] < args.filler_max
            and grouped[1][0] - grouped[0][1] > args.filler_gap):
        print(f"  dropped stranded filler {grouped[0][0]:.2f}-{grouped[0][1]:.2f}s "
              f"(+{grouped[1][0]-grouped[0][1]:.2f}s pause behind it)", file=sys.stderr)
        grouped = grouped[1:]
    return [tuple(g) for g in grouped]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--audio", required=True, help="mono 16k wav of the same source")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--clip-id", required=True, help="Resolve media pool clip id")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--source-duration", type=float, default=None,
                    help="clamp; defaults to last transcript timestamp + 2s")
    ap.add_argument("--out", default="clip_infos.json")
    # tuned on real footage - see references/editorial-rules.md before changing
    ap.add_argument("--split-gap", type=float, default=0.55,
                    help="cut internal pauses longer than this. Below ~0.45 it starts "
                         "slicing between words inside sentences and sounds machine-gunned.")
    ap.add_argument("--head-pad", type=float, default=0.05)
    ap.add_argument("--tail-pad", type=float, default=0.09)
    ap.add_argument("--noise", default="-36dB")
    ap.add_argument("--min-silence", type=float, default=0.12)
    ap.add_argument("--min-keep", type=float, default=0.14)
    ap.add_argument("--window-pad", type=float, default=0.25)
    ap.add_argument("--filler-max", type=float, default=0.55)
    ap.add_argument("--filler-gap", type=float, default=0.40)
    args = ap.parse_args()

    segs = json.load(open(args.transcript))["segments"]
    plan = json.load(open(args.plan))
    src_end = args.source_duration or (segs[-1]["end"] + 2.0)

    # ---- 1. transcript decides what to keep, and in what order
    if plan.get("mode") == "spine":
        order = [(i, sl) for i, sl in plan["spine"]]
    else:
        drop = set(plan.get("drop", []))
        order = [(i, None) for i in range(len(segs)) if i not in drop]

    raw = []
    for i, sl in order:
        ws = segs[i].get("words") or []
        if not ws:
            raw.append((segs[i]["start"], segs[i]["end"]))
            continue
        ws = ws[sl[0]:sl[1]] if sl else ws
        if ws:
            raw.append((ws[0]["start"], ws[-1]["end"]))

    # Merge kept segments that are contiguous in the source into ONE candidate range
    # before measuring. Without this, each transcript segment gets measured in its own
    # window: clips fragment needlessly and the stranded-filler heuristic misfires on
    # ordinary sentence-initial words. Only a real source discontinuity starts a new range.
    candidates = [list(raw[0])]
    for a, b in raw[1:]:
        if a >= candidates[-1][1] and (a - candidates[-1][1]) <= args.split_gap:
            candidates[-1][1] = b
        else:
            candidates.append([a, b])
    candidates = [tuple(c) for c in candidates]

    # ---- 2. waveform decides where the cuts actually land
    print("measuring waveform:", file=sys.stderr)
    runs = []
    for a, b in candidates:
        runs.extend(measured_speech(args.audio, a, b, args))
    if not runs:
        sys.exit("no speech found - check --noise and the audio path")

    # ---- 3. pad, but never re-open the silence just removed
    infos, rec = [], 0
    for k, (a, b) in enumerate(runs):
        head, tail = args.head_pad, args.tail_pad
        if k > 0 and runs[k - 1][1] < a:
            head = min(head, (a - runs[k - 1][1]) / 2)
        if k < len(runs) - 1 and runs[k + 1][0] > b:
            tail = min(tail, (runs[k + 1][0] - b) / 2)
        sf = int(round(max(0.0, a - head) * args.fps))
        ef = int(round(min(src_end, b + tail) * args.fps))   # EXCLUSIVE
        if ef - sf < 3:
            continue
        infos.append({"clip_id": args.clip_id, "start_frame": sf,
                      "end_frame": ef, "record_frame": rec})
        rec += ef - sf

    json.dump(infos, open(args.out, "w"), indent=1)

    durs = sorted((x["end_frame"] - x["start_frame"]) / args.fps for x in infos)
    tiny = [d for d in durs if d < 0.5]
    print(f"\nclips        : {len(infos)}", file=sys.stderr)
    print(f"duration     : {rec/args.fps:.1f}s ({rec} frames)", file=sys.stderr)
    print(f"clip lengths : min {durs[0]:.2f}s  median {statistics.median(durs):.2f}s  "
          f"max {durs[-1]:.2f}s", file=sys.stderr)
    print(f"wrote        : {args.out}", file=sys.stderr)
    if tiny:
        print(f"\nWARNING: {len(tiny)} clip(s) under 0.5s. That is the machine-gun "
              f"signature - rebuild with --split-gap {args.split_gap + 0.2:.2f} or higher.",
              file=sys.stderr)
    print("\nNext: create_timeline_from_clips with these clip_infos, then "
          "timeline.detect_gaps_overlaps to confirm 0 gaps / 0 overlaps.", file=sys.stderr)


if __name__ == "__main__":
    main()
