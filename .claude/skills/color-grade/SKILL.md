---
name: color-grade
description: Color-grade (rangga ishlov berish) a user's video so it matches the colours and mood of a reference — a film still, a screenshot from a movie, any colourful photo, or another video. Use whenever the user sends a video plus a reference image/film and asks to "make it look like this", copy a film look, apply a colour grade/LUT, or in Uzbek "rangini shunaqa qil", "color grade qil", "shu filmdagidek rang ber", "videoga rang ber". Also builds a reusable .cube LUT for Premiere, DaVinci Resolve, CapCut or VN.
---

# Color grade: match a video to a reference look

The user gives a **video** and a **reference** (film still, photo, or another
video). Produce the same video re-coloured to match the reference's look.

Tools: `ffmpeg`, `python3` with `numpy` + `Pillow` (no OpenCV needed).
Script: `scripts/color_grade.py` (next to this file).

## Workflow

1. **Find the inputs.** Files the user attached/uploaded, or paths they give.
   If the reference is a film *name* only (no image), ask them to send a still
   from that film — don't invent one. Work in the scratchpad directory; put
   final outputs where the user can open them.

2. **Build the LUT + preview first** (fast, no full render):
   ```bash
   python3 .claude/skills/color-grade/scripts/color_grade.py \
     --video INPUT.mp4 --ref REF.jpg --out OUT.mp4 \
     --save-lut OUT_look.cube --preview OUT_preview.png --lut-only
   ```
   Look at the preview PNG (before | after | reference). Check:
   - skin tones aren't green/grey/neon,
   - highlights/sky aren't clipped, shadows aren't crushed to pure black,
   - the overall tint actually resembles the reference.

3. **Tune if needed** and re-run the preview:
   | Problem | Fix |
   |---|---|
   | Too strong / unnatural | `--strength 0.6` (default 0.85) |
   | Contrast wrong, faces too dark/bright | `--tone stats` (gentler) or `--tone keep` (colour only) |
   | Washed out | `--saturation 1.15` |
   | Too saturated | `--saturation 0.85` |

4. **Render** the final video (drop `--lut-only`). Audio is copied unchanged;
   resolution and frame rate stay the same; output is H.264 MP4 (`--crf 18`).

5. **Deliver**: send the graded video, the preview image and the `.cube` LUT
   (the user can reuse the LUT in CapCut / Premiere / Resolve on other clips).
   Briefly say what changed (e.g. "issiq to'q sariq soyalar, ko'kimtir
   yashil soyalar, kontrast pasaytirildi"). Reply in the user's language.

## Notes
- Several references (e.g. 3 stills from one film): grade with the most
  representative one, or merge them first:
  `ffmpeg -i a.jpg -i b.jpg -i c.jpg -filter_complex "[0]scale=640:360[a];[1]scale=640:360[b];[2]scale=640:360[c];[a][b][c]hstack=3" ref.png`
- A reference *video* works too: `--ref film_clip.mp4` (16 frames are sampled).
- Letterbox black bars in film stills are ignored automatically.
- Very long/4K videos: render can take a while — run it with a long timeout
  or in the background.
- The method: Lab colour space; lightness via percentile curve matching,
  colour (a/b) via mean/std transfer; baked to a 33³ 3D LUT applied with
  ffmpeg `lut3d` (tetrahedral).
