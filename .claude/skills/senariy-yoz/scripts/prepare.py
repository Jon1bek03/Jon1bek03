#!/usr/bin/env python3
"""senariy-yoz: prepare a talking-head video for script writing.

Steps: (download if URL) -> 16 kHz mono WAV -> contact sheets -> Whisper transcript.

Writes into --out:
  media/video.<ext>      the source (downloaded or copied)
  audio.wav              16 kHz mono
  frames/sheet-NN.jpg    contact sheets, one cell every --every seconds
  frames/index.txt       which timestamp each cell is
  transcript.json        [{start, end, text}, ...]
  transcript.txt         "[mm:ss-mm:ss] text" per line
  meta.json              duration, size, orientation, language, model, ...

Usage:
  python3 prepare.py --input VIDEO_OR_URL --out RUN_DIR [--lang uz] [--model large-v3] [--every 3]
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL, **kw)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", path],
        check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    dur = float(data["format"]["duration"])
    w = h = None
    has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and w is None:
            w, h = s.get("width"), s.get("height")
        if s.get("codec_type") == "audio":
            has_audio = True
    return dur, w, h, has_audio


def fmt(t):
    t = int(round(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def get_media(src, media_dir):
    os.makedirs(media_dir, exist_ok=True)
    if os.path.exists(src):
        ext = os.path.splitext(src)[1] or ".mp4"
        dst = os.path.join(media_dir, "video" + ext)
        shutil.copyfile(src, dst)
        return dst, {"source": "local file", "path": os.path.abspath(src)}
    if not shutil.which("yt-dlp"):
        sys.exit("yt-dlp topilmadi: pip install -U yt-dlp")
    info = subprocess.run(
        ["yt-dlp", "--no-warnings", "--print",
         "%(title)s|%(uploader)s|%(duration)s|%(webpage_url)s", src],
        capture_output=True, text=True)
    meta = {"source": "url", "url": src}
    if info.returncode == 0 and info.stdout.strip():
        parts = info.stdout.strip().splitlines()[0].split("|")
        if len(parts) == 4:
            meta.update(title=parts[0], uploader=parts[1], url=parts[3])
    run(["yt-dlp", "-q", "--no-warnings",
         "-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4",
         "-o", os.path.join(media_dir, "video.%(ext)s"), src])
    files = [f for f in os.listdir(media_dir) if f.startswith("video.")]
    if not files:
        sys.exit("Video yuklanmadi.")
    return os.path.join(media_dir, files[0]), meta


def sheets(video, frames_dir, dur, w, h, every):
    os.makedirs(frames_dir, exist_ok=True)
    vertical = (h or 0) > (w or 0)
    scale, tile, per = (250, "10x3", 30) if vertical else (304, "6x5", 30)
    run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", video,
         "-vf", f"fps=1/{every},scale={scale}:-1,tile={tile}",
         "-q:v", "4", os.path.join(frames_dir, "sheet-%02d.jpg")])
    n_frames = max(1, math.ceil(dur / every))
    lines = []
    for i in range(n_frames):
        sheet, cell = i // per + 1, i % per + 1
        lines.append(f"sheet-{sheet:02d}.jpg cell {cell:2d} (chapdan o'ngga, yuqoridan pastga) = {fmt(i * every)}")
    with open(os.path.join(frames_dir, "index.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return n_frames, math.ceil(n_frames / per), tile


def transcribe(wav, lang, model_name):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segs, info = model.transcribe(
        wav, language=None if lang == "auto" else lang,
        vad_filter=True, beam_size=5,
        initial_prompt="Assalomu alaykum. Bugun sizlarga o'zbek tilida gapirib beraman."
        if lang == "uz" else None)
    out = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
    return out, info.language, info.language_probability


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="video fayl yoki havola")
    ap.add_argument("--out", required=True, help="natija papkasi")
    ap.add_argument("--lang", default="uz", help="uz, ru, en ... yoki auto")
    ap.add_argument("--model", default="large-v3", help="faster-whisper modeli (large-v3, medium, small)")
    ap.add_argument("--every", type=int, default=3, help="har necha soniyada bitta kadr")
    ap.add_argument("--skip-transcribe", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    video, meta = get_media(a.input, os.path.join(a.out, "media"))
    dur, w, h, has_audio = probe(video)
    meta.update(duration=round(dur, 2), duration_mmss=fmt(dur), width=w, height=h,
                orientation="vertikal" if (h or 0) > (w or 0) else "gorizontal",
                has_audio=has_audio)

    n_frames, n_sheets, tile = sheets(video, os.path.join(a.out, "frames"), dur, w, h, a.every)
    meta.update(frames_every_s=a.every, frames=n_frames, sheets=n_sheets, tile=tile)
    print(f"[senariy-yoz] {meta['duration_mmss']}, {meta['orientation']}, {n_sheets} ta kadr varag'i")

    if not has_audio:
        meta["transcript"] = "ovoz yo'q"
    elif not a.skip_transcribe:
        wav = os.path.join(a.out, "audio.wav")
        run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", video,
             "-vn", "-ac", "1", "-ar", "16000", wav])
        print(f"[senariy-yoz] Whisper {a.model} ({a.lang}) ishlayapti...")
        segs, lang, prob = transcribe(wav, a.lang, a.model)
        meta.update(model=a.model, language=lang, language_prob=round(prob, 3), segments=len(segs))
        with open(os.path.join(a.out, "transcript.json"), "w") as f:
            json.dump(segs, f, ensure_ascii=False, indent=1)
        with open(os.path.join(a.out, "transcript.txt"), "w") as f:
            for s in segs:
                f.write(f"[{fmt(s['start'])}-{fmt(s['end'])}] {s['text']}\n")
        print(f"[senariy-yoz] {len(segs)} ta segment -> transcript.txt")

    with open(os.path.join(a.out, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"[senariy-yoz] tayyor: {a.out}")


if __name__ == "__main__":
    main()
