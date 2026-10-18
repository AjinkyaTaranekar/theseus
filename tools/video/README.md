# Pitch video builder

Builds the ~3 minute Theseus pitch video from **real captures of the live product**, a narrated script and a
small set of drawn scenes. It is tooling, not part of the product: nothing under `theseus/` imports it, and its
dependencies are not in `pyproject.toml`.

What it never does: write to GitHub, post comments or open pull requests. It only reads the public Try-it page,
and the review and dashboard pages that the app's own PR comments link to.

## Files

| File | Job |
| --- | --- |
| `script.json` | One entry per scene: narration (`show`), tail pause, chapter, and, once `genvoice.py` has run, the length and per-word timings. Animations key off those word times, so a rewrite must keep each scene's cue words (the `tm.at(...)` calls in `scenes.py`). |
| `genvoice.py` | Makes the voice-over and word timings with the `edge-tts` package. |
| `kit.py` | Drawing kit: the black keynote palette and backdrop, framed windows with a keyframed camera, callouts that also set the spotlight, and subtitle captions cut at clauses. |
| `scenes.py` | The 19 scenes, one class each. |
| `render.py` | Assembles scenes, dims everything outside the active callouts, draws the chapter bar, mixes the audio (voice, music bed, cue sounds) and writes `theseus-pitch.mp4`. |
| `explore.js`, `capture3.js` ... `capture6.js` | Headless-Chrome captures at high resolution into `captures/`. |

## Run it

```bash
cd tools/video
python -m venv .venv && .venv/bin/pip install -r requirements.txt
npm install                      # puppeteer-core only; it drives your installed Chrome
export CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"   # default shown
# Windows (Git Bash): export CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe"

# 1. Captures. The dashboard needs a signed link, which the app puts in its PR comments.
export R124=$(gh api repos/<owner>/<repo>/issues/124/comments --jq '.[0].body' \
  | grep -oE "https://[^ )>\"]*/reviews/[^ )>\"]*" | head -1)
node explore.js        # finds the dashboard link and writes dash.url (git-ignored)
node capture3.js && node capture4.js && node capture5.js && node capture6.js

# 2. Voice-over and word timings (about 1 minute): Emily, Irish English, at +32%, about 159 words a minute
.venv/bin/python genvoice.py en-IE-EmilyNeural +32%

# 3. Look at stills, then render
.venv/bin/python render.py preview          # or: render.py preview n07
.venv/bin/python render.py                  # writes theseus-pitch.mp4 (about 2 minutes)
```

## Things to know

- **Secrets.** The `?k=` in a review or dashboard link is a signed key. `dash.url` is git-ignored, and the
  captures are element or viewport screenshots, so no address bar is ever shown. Do not commit `captures/`.
- **Network.** `genvoice.py` sends the narration text, which is public pitch copy, to Microsoft's online speech
  service through `edge-tts`. No account or key is needed. Do not put anything private in `script.json`.
- **Fonts.** On macOS, `kit.py` loads Avenir Next and Menlo from `/System/Library/Fonts`; elsewhere it falls back
  to Segoe UI and Consolas, so the video also renders on Windows (Avenir is the intended look).
- **Length.** Keep the timeline under 180 s: `render.py preview` prints `TOTAL`. The narration is about 440
  words; a longer script needs a faster rate or fewer words, never a cut cue word.
- **Every number on screen** comes from a live page or from the repo's own files: the 86 nodes and 188 edges,
  the AWS STS blast radius (14 go down, 11 lose access, 24 of 25 dependencies break), the fix verdicts. If the
  demo's data changes, recapture before re-rendering, and check the narration against the new numbers.
- **Alpha on text.** Pillow ignores the alpha of a text fill, so `kit.py` patches `ImageDraw.text` to make fades
  real. Import `kit` before drawing anything.
- **Not committed:** the rendered `.mp4`, `captures/`, `audio/` and `pv/` (all git-ignored).
