---
name: senariy-yoz
description: Turn a video of a person talking into a NEW shooting script (senariy) for re-recording a fresh video — transcribes the speech (Uzbek by default, also Russian/English), reads the frames, then rewrites it as a tighter scene-by-scene script with a strong hook, lines to say, shot/b-roll directions, on-screen text and a CTA. Use whenever the user sends a video (file or YouTube/Instagram/TikTok/Telegram link) and asks for a scenario/script, in Uzbek "senariy yozib ber", "shu videodan senariy", "qayta suratga olish uchun senariy", "ssenariy", "matnini yozib ber va senariy qil".
---

# senariy-yoz: videodan yangi rolik uchun senariy

The user sends a video where a person talks. Goal: a **new script to re-shoot
a better video** on the same idea — not a verbatim transcript. Keep the
speaker's ideas, facts and voice; improve structure, hook and pacing.

Reply to the user in the language they write in (usually Uzbek, Latin script,
with correct oʻ/gʻ/sh/ch). Write the script itself in the video's language
unless the user asks otherwise.

## 1. Ask (once, briefly) — only what is missing

Ask in one message, offer defaults, then proceed:
- **Yangi rolik uzunligi va platformasi?** default: same platform; Reels/TikTok/Shorts → 30–60 s, vertical; YouTube → close to original length.
- **Kim suratga tushadi / qanday sharoit?** default: one person to camera, phone, simple b-roll.
- **Maqsad (CTA)?** default: whatever the original asks for (obuna, izoh, xarid, Telegram kanal).

If the user already said "o'zing hal qil" or gave these, don't ask.

## 2. Prepare the video

Setup (once per session; the container is fresh each time):
```bash
pip install -q -U faster-whisper yt-dlp
```
Run (work in the scratchpad, one folder per video):
```bash
python3 .claude/skills/senariy-yoz/scripts/prepare.py \
  --input "<file or URL>" --out "<scratchpad>/senariy/<slug>" --lang uz
```
- `--lang`: `uz` (default), `ru`, `en`, or `auto`. Mixed uz/ru speech → `auto`.
- `--model`: `large-v3` (default, best for Uzbek, ~3 GB download, slow on CPU).
  For a quick draft or videos > 10 min offer `medium`; never use `*.en` models.
- `--every 3` frame interval; use `--every 1` for short reels (< 40 s),
  `--every 10` for videos > 10 min. Keep total sheets ≲ 15.
- If a link fails (private, login, 403), ask the user to upload the file.

Outputs: `transcript.txt` (timed), `frames/sheet-NN.jpg` + `frames/index.txt`, `meta.json`.

## 3. Understand the original

- Read `transcript.txt` fully. Whisper's Uzbek is imperfect: fix obvious
  mishearings by context, but **never invent facts, numbers or names** — if
  a word is unclear and matters, mark it `[aniq emas: ...]` and ask.
- Read every contact sheet with the Read tool (cell order = timestamps in
  `index.txt`). Note setting, framing, props, on-screen text, cuts, what is
  shown as proof.
- Extract: main idea in one sentence, key points (in order), facts/numbers,
  stories/examples, the original hook, the CTA, and what is weak (slow start,
  repetition, filler, missing proof, no clear ending).

## 4. Write the new script

Principles:
- **Hook in the first 3 seconds**: a sharp question, bold claim, result-first,
  or pain point — from the speaker's own material. Offer **3 hook variants**.
- One idea per scene; cut filler, repetition and "xullas, endi, mana" padding.
- Spoken lines short and natural — written to be *said*, in the speaker's
  register (sen/siz as in the original).
- Every scene says what is **seen** (shot, b-roll, on-screen text), not only what is said.
- Respect target length: ~2.3 words/second of speech (60 s ≈ 130–140 words).
- End with one clear CTA.

Save as `senariy.md` in the run folder, using this structure:

```markdown
# <Rolik nomi>

**Asl video:** <link or file> · <davomiyligi>
**Yangi rolik:** <platforma>, <format 9:16/16:9>, ~<N> soniya
**Asosiy g'oya:** <bir gap>
**Maqsad / CTA:** <...>

## Ilgak variantlari (birini tanlang)
1. "..."
2. "..."
3. "..."

## Senariy

| # | Vaqt | Kadr / plan | Aytiladigan matn | Ekrandagi yozuv | B-roll / izoh |
|---|------|-------------|------------------|-----------------|---------------|
| 1 | 0:00–0:03 | Yaqin plan, kameraga | "..." | ... | ... |
| ... |

## To'liq matn (suflyor uchun)
<the spoken lines only, continuous, for reading from a teleprompter>

## Suratga olish ro'yxati
- Kerakli kadrlar / b-roll: ...
- Rekvizit, joy, kiyim: ...
- Ovoz/yorug'lik bo'yicha maslahat: ...

## Asl videodan nima o'zgardi
- <3–6 bullet points: what was cut, reordered, strengthened and why>
```

If the user wants a file to print or send, also export `.docx` or PDF via the
matching skill. Deliver `senariy.md` inside the working directory (or send it
with SendUserFile) so the user can open it.

## 5. Report

In chat: the chosen hook, new length, scene count, and the file path — not the
whole script unless it is short (< 60 s rolik). Offer edits: "ilgakni
almashtiraymi?", "qisqartiraymi?", "rus tilida ham kerakmi?".
