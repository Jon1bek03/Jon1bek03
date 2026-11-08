#!/usr/bin/env python3
"""Color-grade a video so it matches the look of a reference image/film still/video.

How it works
------------
1. Sample frames from the source video and from the reference (image or video).
2. Measure colour statistics in CIE Lab:
     * L (lightness)  -> quantile/curve matching (copies contrast, crushed or lifted blacks,
                          soft highlights of the reference)
     * a, b (colour)  -> mean/std transfer (Reinhard) (copies the tint: teal-orange,
                          warm, cold, green "Matrix", etc.)
3. Bake that transform into a 3D LUT (.cube) and apply it to every frame with
   ffmpeg's lut3d filter. Audio is copied untouched.

Only numpy + Pillow + ffmpeg are required.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}


# ---------------------------------------------------------------- colour math
def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]])
_M_XYZ2RGB = np.linalg.inv(_M_RGB2XYZ)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb):
    """rgb: (...,3) float in [0,1] sRGB -> Lab"""
    xyz = srgb_to_linear(rgb) @ _M_RGB2XYZ.T / _WHITE
    d = 6 / 29
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4 / 29)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1)


def lab_to_rgb(lab):
    d = 6 / 29
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > d, f ** 3, 3 * d * d * (f - 4 / 29)) * _WHITE
    return np.clip(linear_to_srgb(xyz @ _M_XYZ2RGB.T), 0, 1)


# ---------------------------------------------------------------- sampling
def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit(f"Command failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "json", path])
    try:
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXT


def sample_pixels(path, tmp, n_frames=16, size=320):
    """Return (N,3) float RGB pixels in [0,1] sampled from an image or video."""
    if is_image(path):
        img = Image.open(path).convert("RGB")
        img.thumbnail((size * 2, size * 2))
        imgs = [img]
    else:
        dur = max(duration(path), 0.1)
        d = tempfile.mkdtemp(dir=tmp)
        fps = n_frames / dur
        run(["ffmpeg", "-v", "error", "-i", path, "-vf",
             f"fps={fps:.6f},scale={size}:-2", "-frames:v", str(n_frames),
             os.path.join(d, "f_%03d.png")])
        imgs = [Image.open(p).convert("RGB") for p in sorted(glob.glob(os.path.join(d, "*.png")))]
        if not imgs:
            sys.exit(f"Could not read frames from {path}")
    px = np.concatenate([np.asarray(i, dtype=np.float32).reshape(-1, 3) / 255.0 for i in imgs])
    return px


def crop_letterbox(px_lab):
    """Drop near-black pixels (letterbox bars of film stills) from statistics."""
    keep = px_lab[:, 0] > 2.0
    return px_lab[keep] if keep.mean() > 0.3 else px_lab


# ---------------------------------------------------------------- transform
class Grade:
    def __init__(self, src_lab, ref_lab, tone="match", strength=0.8, saturation=1.0):
        self.tone = tone
        self.strength = strength
        self.saturation = saturation
        q = np.linspace(1, 99, 49)
        sq = np.percentile(src_lab[:, 0], q)
        rq = np.percentile(ref_lab[:, 0], q)
        sq = sq + np.arange(len(sq)) * 1e-4  # strictly increasing
        lo = max(0.0, rq[0] - sq[0])
        hi = min(100.0, rq[-1] + (100 - sq[-1]))
        self.xp = np.concatenate([[0], sq, [100]])
        self.fp = np.maximum.accumulate(np.concatenate([[lo], rq, [hi]]))

        self.s_mean = src_lab.mean(0)
        self.s_std = src_lab.std(0) + 1e-6
        self.r_mean = ref_lab.mean(0)
        self.r_std = ref_lab.std(0) + 1e-6
        # keep ratio sane so near-monochrome sources don't explode
        self.ratio = np.clip(self.r_std / self.s_std, 0.4, 2.5)

    def apply_lab(self, lab):
        out = lab.copy()
        if self.tone == "match":
            out[..., 0] = np.interp(lab[..., 0], self.xp, self.fp)
        elif self.tone == "stats":
            out[..., 0] = (lab[..., 0] - self.s_mean[0]) * self.ratio[0] + self.r_mean[0]
        # tone == "keep" -> leave lightness alone
        for c in (1, 2):
            out[..., c] = ((lab[..., c] - self.s_mean[c]) * self.ratio[c] + self.r_mean[c]) * self.saturation
        out[..., 0] = np.clip(out[..., 0], 0, 100)
        return out

    def apply_rgb(self, rgb):
        graded = lab_to_rgb(self.apply_lab(rgb_to_lab(rgb)))
        return np.clip(rgb + (graded - rgb) * self.strength, 0, 1)


def write_cube(path, grade, size=33):
    g = np.linspace(0, 1, size)
    # .cube order: red changes fastest, then green, then blue
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = grade.apply_rgb(rgb)
    with open(path, "w") as f:
        f.write('TITLE "color-grade match"\n')
        f.write(f"LUT_3D_SIZE {size}\n")
        f.write("DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n")
        for v in out:
            f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")


def ff_escape(p):
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, help="source video to grade")
    ap.add_argument("--ref", required=True, help="reference image / film still / video")
    ap.add_argument("--out", required=True, help="output video path (.mp4)")
    ap.add_argument("--strength", type=float, default=0.85, help="0..1 how strongly to apply the look")
    ap.add_argument("--tone", choices=["match", "stats", "keep"], default="match",
                    help="lightness handling: match=copy reference contrast curve (default), "
                         "stats=mean/std only (gentler), keep=only change colour")
    ap.add_argument("--saturation", type=float, default=1.0, help="extra saturation multiplier after matching")
    ap.add_argument("--lut-size", type=int, default=33)
    ap.add_argument("--save-lut", help="also save the .cube LUT here (usable in Premiere/Resolve/CapCut)")
    ap.add_argument("--preview", help="save a before|after comparison PNG here")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--lut-only", action="store_true", help="only build the LUT/preview, don't render video")
    a = ap.parse_args()

    for p in (a.video, a.ref):
        if not os.path.exists(p):
            sys.exit(f"File not found: {p}")

    tmp = tempfile.mkdtemp(prefix="cgrade_")
    try:
        src = crop_letterbox(rgb_to_lab(sample_pixels(a.video, tmp)))
        ref = crop_letterbox(rgb_to_lab(sample_pixels(a.ref, tmp)))
        grade = Grade(src, ref, tone=a.tone, strength=max(0.0, min(1.0, a.strength)),
                      saturation=a.saturation)

        lut = a.save_lut or os.path.join(tmp, "grade.cube")
        if os.path.dirname(lut):
            os.makedirs(os.path.dirname(lut), exist_ok=True)
        write_cube(lut, grade, a.lut_size)
        print(f"LUT: {lut}")
        print(f"source  Lab mean {np.round(grade.s_mean, 1)}  std {np.round(grade.s_std, 1)}")
        print(f"ref     Lab mean {np.round(grade.r_mean, 1)}  std {np.round(grade.r_std, 1)}")

        if a.preview:
            mid = max(duration(a.video) / 2, 0)
            fr = os.path.join(tmp, "mid.png")
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.2f}", "-i", a.video,
                 "-frames:v", "1", "-vf", "scale=960:-2", fr])
            before = Image.open(fr).convert("RGB")
            arr = np.asarray(before, dtype=np.float32) / 255.0
            after = Image.fromarray((grade.apply_rgb(arr) * 255 + 0.5).astype(np.uint8))
            refimg = Image.open(a.ref).convert("RGB") if is_image(a.ref) else None
            w, h = before.size
            tiles = [before, after] + ([refimg.resize((int(refimg.width * h / refimg.height), h))]
                                       if refimg else [])
            canvas = Image.new("RGB", (sum(t.width for t in tiles) + 8 * (len(tiles) - 1), h), "white")
            x = 0
            for t in tiles:
                canvas.paste(t, (x, 0))
                x += t.width + 8
            canvas.save(a.preview)
            print(f"Preview (before | after{' | reference' if refimg else ''}): {a.preview}")

        if not a.lut_only:
            if os.path.dirname(a.out):
                os.makedirs(os.path.dirname(a.out), exist_ok=True)
            cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-i", a.video,
                   "-vf", f"lut3d=file='{ff_escape(lut)}':interp=tetrahedral,format=yuv420p",
                   "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
                   "-crf", str(a.crf), "-c:a", "copy", "-movflags", "+faststart", a.out]
            r = subprocess.run(cmd)
            if r.returncode != 0:
                # audio codec might not fit mp4 -> re-encode audio
                cmd[cmd.index("-c:a") + 1] = "aac"
                run(cmd)
            print(f"Output video: {a.out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
