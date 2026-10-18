import json
import math
import os
import subprocess
import sys
import wave

import imageio_ffmpeg
import numpy as np
from kit import (
    AV,
    FPS,
    SPOT,
    H,
    Timing,
    W,
    caption_layer,
    clamp,
    over,
    spotlight,
)
from PIL import Image, ImageDraw
from scenes import SCENES

FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 44100
LEAD = 0.2
sc = json.load(open("script.json"))
plan, g = [], 0.0
for s in sc:
    D = LEAD + s["dur"] + s["tail"]
    plan.append((s, D, g))
    g += D
TOTAL = g
tms = [Timing(s, LEAD) for s in sc]
# Chapters, in order of first appearance, each with the time span of its scenes
CH = []
for s, D, g0 in plan:
    if CH and CH[-1][0] == s["chapter"]:
        CH[-1][2] = g0 + D
    else:
        CH.append([s["chapter"], g0, g0 + D])
objs = [None] * len(sc)


def obj(i):
    if objs[i] is None:
        objs[i] = SCENES[i](tms[i])
    return objs[i]


def frame_at(i, t):
    s, D, g0 = plan[i]
    SPOT.clear()
    im = spotlight(obj(i).frame(min(t, D)), SPOT).convert("RGBA")
    cap, a = tms[i].cap(t)
    over(im, caption_layer(cap or "", a if cap else 0))
    f = min(1, t / 0.22, (D - t) / 0.25)
    im = im.convert("RGB")
    if f < 1:
        im = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), im, clamp(f))
    if tms[i].show:  # the title card has no captions and no chapter bar
        chapter_bar(im, g0 + t)
    return im


def chapter_bar(im, g):
    """Thin segments across the top, one per chapter, filling as it plays, with the chapter names."""
    px = np.zeros((96, W, 4), np.uint8)  # a dark strip, so the names read over any screenshot
    px[..., 3] = np.concatenate([np.full(52, 235), np.linspace(235, 0, 44)]).astype(np.uint8)[:, None]
    lay = Image.fromarray(px, "RGBA")
    d = ImageDraw.Draw(lay, "RGBA")
    n, gap, x = len(CH), 12, 64
    sw = (W - 128 - gap * (n - 1)) / n
    f = AV(17, "demi")
    for name, a, b in CH:
        k = clamp((g - a) / (b - a))
        now = a <= g < b
        d.rounded_rectangle([x, 18, x + sw, 21], 2, fill=(255, 255, 255, 46))
        if k > 0:
            d.rounded_rectangle([x, 18, x + sw * k, 21], 2, fill=(255, 255, 255, 235 if now else 150))
        d.text((x, 30), name.upper(), font=f, fill=(245, 245, 247, 235 if now else 100))
        x += sw + gap
    base = im.convert("RGBA")
    base.alpha_composite(lay, (0, 0))
    im.paste(base.convert("RGB"))


# ------------------------------------------------------------------ audio
def build_audio(path):
    n = int((TOTAL + 1.0) * SR)
    voice = np.zeros(n, np.float32)
    for s, _D, g0 in plan:
        w = wave.open(f"audio/{s['id']}.wav")
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        a = int((g0 + LEAD) * SR)
        voice[a : a + len(pcm)] += pcm
    voice *= 0.9 / max(0.01, np.abs(voice).max())
    tt = np.arange(n) / SR
    # music bed: slow pad + soft pulsing arpeggio
    chords = [
        [110, 164.8, 196, 246.9, 261.6],
        [87.3, 130.8, 220, 261.6, 329.6],
        [130.8, 196, 261.6, 329.6, 392],
        [98, 146.8, 246.9, 293.7, 370],
    ]
    pad = np.zeros(n, np.float32)
    seg = 8.0
    for k in range(int(TOTAL / seg) + 2):
        c = chords[k % 4]
        t0 = k * seg
        env = np.clip((tt - (t0 - 1.5)) / 2.5, 0, 1) * np.clip(((t0 + seg + 1.5) - tt) / 2.5, 0, 1)
        env = np.where((tt > t0 - 1.5) & (tt < t0 + seg + 1.5), env, 0)
        for j, f in enumerate(c):
            pad += env * np.sin(2 * math.pi * f * tt + j) * (0.05 if f < 150 else 0.03)
            pad += env * np.sin(2 * math.pi * (f * 1.004) * tt + j * 2) * 0.02
    pad *= 0.7 + 0.3 * np.sin(2 * math.pi * 0.12 * tt)
    arp = np.zeros(n, np.float32)
    step = 0.25
    rng = np.random.RandomState(7)
    for k in range(int(TOTAL / step)):
        t0 = k * step
        if t0 < 1.0:
            continue
        c = chords[int(t0 // seg) % 4]
        f = c[(k * 3 + int(rng.randint(0, 3))) % len(c)] * 4
        a = int(t0 * SR)
        L = int(0.35 * SR)
        e = np.exp(-np.arange(L) / (0.09 * SR)).astype(np.float32)
        arp[a : a + L] += (
            np.sin(2 * math.pi * f * np.arange(L) / SR).astype(np.float32)[: max(0, min(L, n - a))]
            * e[: max(0, min(L, n - a))]
            * 0.012
        )
    music = pad + arp
    music *= np.clip(tt / 2.0, 0, 1) * np.clip((TOTAL + 0.8 - tt) / 2.5, 0, 1)
    # duck under the voice
    env = np.convolve(np.abs(voice), np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    duck = 1 - 0.55 * np.clip(env / 0.12, 0, 1)
    music *= duck.astype(np.float32)
    # cue sounds
    sfx = np.zeros(n, np.float32)

    def put(t0, x):
        a = int(t0 * SR)
        if a < n:
            m = min(len(x), n - a)
            sfx[a : a + m] += x[:m]

    for i, (s, _D, g0) in enumerate(plan):  # noqa: B007
        for ts, kind, f in getattr(obj(i), "sfx", []):
            t0 = g0 + ts
            if kind == "ping":
                L = int(1.0 * SR)
                x = np.arange(L) / SR
                put(
                    t0,
                    (np.sin(2 * math.pi * f * x) + 0.3 * np.sin(2 * math.pi * 2 * f * x))
                    * np.exp(-x / 0.25)
                    * 0.10,
                )
            elif kind == "chime":
                L = int(1.4 * SR)
                x = np.arange(L) / SR
                put(
                    t0,
                    (
                        np.sin(2 * math.pi * f * x)
                        + 0.5 * np.sin(2 * math.pi * f * 1.5 * (x - 0.08)) * (x > 0.08)
                    )
                    * np.exp(-x / 0.4)
                    * 0.08,
                )
            elif kind == "whoosh":
                L = int(0.6 * SR)
                z = np.random.RandomState(int(t0 * 100) % 999).randn(L).astype(np.float32)
                k = np.cumsum(z)
                k -= np.convolve(k, np.ones(400) / 400, mode="same")
                e = np.sin(np.linspace(0, math.pi, L)) ** 2
                put(t0, k / (np.abs(k).max() + 1e-6) * e * 0.07)
    mix = voice + music * 0.9 + sfx
    mix = np.clip(mix * 0.95, -1, 1)
    out = wave.open(path, "wb")
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(SR)
    out.writeframes((mix * 32767).astype(np.int16).tobytes())
    out.close()


def main():
    a = sys.argv[1:]
    if a and a[0] == "preview":
        only = a[1] if len(a) > 1 else None
        os.makedirs("pv", exist_ok=True)
        for i, (s, D, _g0) in enumerate(plan):
            if only and s["id"] != only:
                continue
            for k in (0.3, 0.55, 0.9):
                frame_at(i, D * k).save(f"pv/{s['id']}_{int(k * 100)}.png")
            print("preview", s["id"], round(D, 1))
        print("TOTAL", round(TOTAL, 1))
        return
    build_audio("audio/mix.wav")
    print("audio done; total", round(TOTAL, 1), flush=True)
    p = subprocess.Popen(
        [
            FF,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{W}x{H}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-i",
            "audio/mix.wav",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            "theseus-pitch.mp4",
        ],
        stdin=subprocess.PIPE,
    )
    for i, (s, D, _g0) in enumerate(plan):
        nf = int(D * FPS)
        print(s["id"], nf, flush=True)
        for k in range(nf):
            p.stdin.write(frame_at(i, k / FPS).tobytes())
    p.stdin.close()
    p.wait()
    print("done", p.returncode)


if __name__ == "__main__":
    main()
