#!/usr/bin/env python3
"""Measure a clip's colour cast and emit ASC CDL values that neutralise it.

Neutral correction only: white balance, a little contrast, enough saturation to
replace what neutralising removes. This deliberately does NOT produce a stylised
or "dramatic" look.

Two modes:

  measure - sample frames from the source, find the real neutral surfaces, and
            print CDL values ready for timeline_item_color.safe_set_cdl
      color_correct.py measure --source IMG.MOV --out cdl.json

  verify  - compare two renders (ungraded vs graded) and write a contact sheet
      color_correct.py verify --before a.mp4 --after b.mp4 --sheet compare.png

Requires: ffmpeg/ffprobe, numpy, pillow.
"""
import argparse, glob, json, os, subprocess, sys, tempfile
import numpy as np
from PIL import Image

W = np.array([0.2126, 0.7152, 0.0722])   # Rec.709 luma


def duration_of(path):
    """Seconds, with a readable error instead of a traceback when the file is unusable."""
    if not os.path.exists(path):
        sys.exit(f"no such file: {path}")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        sys.exit(f"ffprobe could not read a duration from {path} - not a video?")


def grab(path, times, outdir, width=540):
    """Extract one frame per timestamp."""
    files = []
    for t in times:
        f = os.path.join(outdir, f"f_{t:08.2f}.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", path,
                        "-frames:v", "1", "-vf", f"scale={width}:-1", f],
                       check=False)
        if os.path.exists(f):
            files.append(f)
    return files


def pixels(files):
    return np.concatenate([np.asarray(Image.open(f).convert("RGB"), dtype=np.float64)
                           .reshape(-1, 3) / 255.0 for f in files])


def neutral_mean(px, lo=0.18, hi=0.62, sat_max=0.22):
    """Mean RGB of low-saturation midtones: shirts, walls, floors. These should be grey."""
    mx, mn, L = px.max(1), px.min(1), px.mean(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    m = (L > lo) & (L < hi) & (sat < sat_max)
    if m.sum() < 1000:
        sys.exit("not enough neutral-ish pixels found; widen the thresholds")
    return px[m].mean(0), m.mean()


def report(name, px):
    L = (px * W).sum(1)
    mx, mn = px.max(1), px.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    skin = (L > 0.25) & (L < 0.75) & (px[:, 0] > px[:, 1]) & (px[:, 1] > px[:, 2])
    n, _ = neutral_mean(px)
    print(f"{name:10s} R/G {n[0]/n[1]:.3f}  B/G {n[2]/n[1]:.3f}  "
          f"contrast {L.std():.4f}  luma {L.mean():.3f}  "
          f"skinSat {sat[skin].mean():.3f}  "
          f"clipHi {100*(mx>=0.999).mean():.2f}%  clipLo {100*(mx<=0.004).mean():.2f}%")


def do_measure(a):
    dur = duration_of(a.source)
    times = [dur * f for f in (0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)]
    with tempfile.TemporaryDirectory() as td:
        files = grab(a.source, times, td)
        if not files:
            sys.exit("could not extract frames from --source")
        px = pixels(files)
        n, frac = neutral_mean(px)

        rg, bg = n[0] / n[1], n[2] / n[1]
        # Correct `strength` of the way to neutral. Going 100% makes indoor skin
        # look clinical; leaving a little warmth reads as healthy.
        s = a.strength
        slope = np.array([1.0 / (1 + (rg - 1) * s), 1.0, 1.0 / (1 + (bg - 1) * s)])
        # Neutralising drops red, which dims the image. Rescale to hold luma.
        before_luma = float((n * W).sum())
        after_luma = float(((n * slope) * W).sum())
        slope *= before_luma / max(after_luma, 1e-6)

        offset = np.array([-a.black * 1.2, -a.black, -a.black * 0.4])  # warm shadows are worst
        cdl = {"NodeIndex": "1",
               "Slope": " ".join(f"{v:.3f}" for v in slope),
               "Offset": " ".join(f"{v:.3f}" for v in offset),
               "Power": f"{a.power} {a.power} {a.power}",
               "Saturation": f"{a.saturation}"}

        print(f"neutral pixels sampled : {100*frac:.1f}% of {len(files)} frames")
        print(f"measured cast          : R/G {rg:.3f}   B/G {bg:.3f}")
        cast = "warm" if rg > 1 else "cool"
        print(f"correcting             : {round(s*100)}% toward neutral "
              f"(leaving {round((1-s)*100)}% of the {cast} cast)")
        report("source", px)
        print("\nCDL for timeline_item_color.safe_set_cdl:")
        print(json.dumps(cdl, indent=2))
        if a.out:
            json.dump(cdl, open(a.out, "w"), indent=2)
            print(f"\nwrote {a.out}")


def do_verify(a):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0", a.before],
                               capture_output=True, text=True).stdout.strip())
    times = [dur * f for f in (0.06, 0.22, 0.40, 0.58, 0.76, 0.92)]
    with tempfile.TemporaryDirectory() as td:
        bdir, adir = os.path.join(td, "before"), os.path.join(td, "after")
        os.makedirs(bdir, exist_ok=True)
        os.makedirs(adir, exist_ok=True)
        b = grab(a.before, times, bdir, width=360)
        g = grab(a.after, times, adir, width=360)
        if not b or not g:
            sys.exit("could not extract frames from --before/--after")
        report("before", pixels(b))
        report("after", pixels(g))
        if a.sheet:
            rows = []
            for x, y in zip(sorted(b), sorted(g)):
                u = np.asarray(Image.open(x).convert("RGB"), dtype=np.float64) / 255
                v = np.asarray(Image.open(y).convert("RGB"), dtype=np.float64) / 255
                h = min(u.shape[0], v.shape[0])
                rows.append(np.concatenate([u[:h], v[:h]], axis=1))
            h = min(r.shape[0] for r in rows)
            half = max(1, len(rows) // 2)
            top = np.concatenate([r[:h] for r in rows[:half]], axis=1)
            bot = np.concatenate([r[:h] for r in rows[half:]], axis=1)
            wid = min(top.shape[1], bot.shape[1])
            Image.fromarray((np.concatenate([top[:, :wid], bot[:, :wid]], axis=0)
                             * 255).astype(np.uint8)).save(a.sheet)
            print(f"\nwrote {a.sheet}  (each pair = before | after)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure")
    m.add_argument("--source", required=True)
    m.add_argument("--out", default=None)
    m.add_argument("--strength", type=float, default=0.8,
                   help="fraction of the cast to remove (default 0.8 keeps ~20% warmth)")
    m.add_argument("--black", type=float, default=0.010, help="black-point pull")
    m.add_argument("--power", type=float, default=1.02, help="gamma; >1 adds mid contrast")
    m.add_argument("--saturation", type=float, default=1.06)
    m.set_defaults(func=do_measure)

    v = sub.add_parser("verify")
    v.add_argument("--before", required=True)
    v.add_argument("--after", required=True)
    v.add_argument("--sheet", default=None)
    v.set_defaults(func=do_verify)

    a = ap.parse_args()
    a.func(a)
