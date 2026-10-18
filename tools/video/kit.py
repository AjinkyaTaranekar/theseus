"""Drawing kit for the Theseus pitch: palette, fonts, backdrop, windows, camera, callouts, captions."""

import math
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 24
FD = "/System/Library/Fonts/"
IDX = {"bold": 0, "demi": 2, "med": 5, "reg": 7, "heavy": 8}
# Without macOS fonts (Windows), Segoe UI and Consolas stand in for Avenir Next and Menlo.
MAC = os.path.exists(FD + "Avenir Next.ttc")
WD = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "")
WIN = {
    "bold": "segoeuib.ttf",
    "demi": "seguisb.ttf",
    "med": "seguisb.ttf",
    "reg": "segoeui.ttf",
    "heavy": "seguibl.ttf",
}
_fc = {}


def AV(s, k="reg"):
    if (s, k) not in _fc:
        if MAC:
            _fc[(s, k)] = ImageFont.truetype(FD + "Avenir Next.ttc", s, index=IDX[k])
        else:
            _fc[(s, k)] = ImageFont.truetype(WD + WIN[k], s)
    return _fc[(s, k)]


def MO(s):
    if ("m", s) not in _fc:
        _fc[("m", s)] = ImageFont.truetype(FD + "Menlo.ttc" if MAC else WD + "consola.ttf", s)
    return _fc[("m", s)]


# A keynote palette: a black stage, neutral greys, one accent per meaning (blue info, red risk, green pass)
FG = (245, 245, 247)
DIM = (150, 150, 158)
BLUE = (41, 151, 255)
RED = (255, 77, 79)
GRN = (48, 209, 88)
YEL = (255, 196, 46)
PANEL = (22, 22, 24)
LINE = (58, 58, 64)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def sm(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ss(t, a, b):
    return sm((t - a) / (b - a)) if b > a else (1.0 if t >= a else 0.0)


def lerp(a, b, k):
    return a + (b - a) * k


def mixc(c1, c2, k):
    return tuple(int(lerp(a, b, k)) for a, b in zip(c1, c2, strict=False))


# ---------------------------------------------------------------- backdrop
_bgc = {}


def bg(w=W, h=H):
    if (w, h) in _bgc:
        return _bgc[(w, h)].copy()
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    base = np.zeros((h, w, 3), np.float32)

    def glow(cx, cy, r, col, a):
        d = np.sqrt(((x - cx) * w / h) ** 2 + (y - cy) ** 2)
        return (np.clip(1 - d / r, 0, 1) ** 2 * a)[..., None] * np.array(col, np.float32)

    # black, with one soft neutral light from above; a little dither keeps the encoder from banding it
    base += glow(0.5, -0.18, 1.1, (40, 42, 50), 1.0)
    base += np.random.default_rng(7).uniform(-1.2, 1.2, base.shape).astype(np.float32)
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    _bgc[(w, h)] = im
    return im.copy()


# ---------------------------------------------------------------- text helpers
def wrap(d, text, font, maxw):
    out, line = [], ""
    for w in text.split():
        t = (line + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            line = t
        else:
            out.append(line)
            line = w
    return out + [line] if line else out


def center(d, text, y, font, fill, cx=W // 2):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)


def fade(c, a):
    """RGBA color with alpha a (0..1)."""
    return (c[0], c[1], c[2], int(255 * clamp(a)))


def pill(d, x, y, text, col, a=1.0, fs=26, filled=False, pad=18):
    f = AV(fs, "demi")
    w = d.textlength(text, font=f)
    h = fs + 20
    if (x, y) == (64, 52):
        x = W - 64 - (w + pad * 2)
    d.rounded_rectangle(
        [x, y, x + w + pad * 2, y + h],
        h // 2,
        fill=fade(col, 0.18 * a) if not filled else fade(col, a),
        outline=fade(col, a),
        width=2,
    )
    d.text((x + pad, y + 9), text, font=f, fill=fade((0, 0, 0) if filled else col, a))
    return w + pad * 2


def card(d, x, y, w, h, title=None, sub=None, col=LINE, a=1.0, fs=34, fill=PANEL, subfs=None, glow=False):
    if glow:
        for i, al in ((12, 0.03), (7, 0.05), (3, 0.10)):
            d.rounded_rectangle(
                [x - i, y - i, x + w + i, y + h + i], 22 + i, outline=fade(col, al * a), width=3
            )
    d.rounded_rectangle([x, y, x + w, y + h], 20, fill=fade(fill, 0.96 * a), outline=fade(col, a), width=2)
    ty = y + 24
    if title:
        for l in wrap(d, title, AV(fs, "demi"), w - 44):  # noqa: E741
            d.text((x + 24, ty), l, font=AV(fs, "demi"), fill=fade(FG, a))
            ty += fs + 8
    if sub:
        sf = AV(subfs or max(20, int(fs * 0.62)), "reg")
        for l in wrap(d, sub, sf, w - 44):  # noqa: E741
            d.text((x + 24, ty + 2), l, font=sf, fill=fade(DIM, a))
            ty += sf.size + 8


def arrow(d, x1, y1, x2, y2, col, w=5, k=1.0, a=1.0):
    xe, ye = lerp(x1, x2, k), lerp(y1, y2, k)
    d.line([x1, y1, xe, ye], fill=fade(col, a), width=w)
    if k >= 0.999:
        ang = math.atan2(y2 - y1, x2 - x1)
        for s in (0.5, -0.5):
            d.line(
                [x2, y2, x2 - 20 * math.cos(ang + s), y2 - 20 * math.sin(ang + s)], fill=fade(col, a), width=w
            )


def dot_on(d, x1, y1, x2, y2, t, col, speed=0.7, n=3):
    for i in range(n):
        k = (t * speed + i / n) % 1.0
        x, y = lerp(x1, x2, k), lerp(y1, y2, k)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=fade(col, 0.95))


def rgba_canvas():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def over(base, layer):
    base.paste(layer, (0, 0), layer)
    return base


# ---------------------------------------------------------------- windows + camera
def make_window(content, ww, title="", barh=76, r=36):
    s = ww / content.width
    ch = int(content.height * s)
    c = content.convert("RGB").resize((ww, ch), Image.LANCZOS)
    wh = ch + barh
    body = Image.new("RGBA", (ww, wh), (14, 18, 28, 255))
    d = ImageDraw.Draw(body)
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([38 + i * 50, 26, 38 + i * 50 + 26, 52], fill=col)
    if title:
        f = AV(30, "med")
        d.text(((ww - d.textlength(title, font=f)) / 2, 22), title, font=f, fill=(140, 152, 170, 255))
    body.paste(c, (0, barh))
    mask = Image.new("L", (ww, wh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, ww - 1, wh - 1], r, fill=255)
    win = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))
    win.paste(body, (0, 0), mask)
    ImageDraw.Draw(win).rounded_rectangle([0, 0, ww - 1, wh - 1], r, outline=(70, 82, 106, 255), width=3)
    return win, barh, ch


class Win:
    """A framed screenshot on a backdrop, with a keyframed camera in content coordinates (u,v in 0..1)."""

    CW = 3840

    def __init__(self, content, ww=3000, title="", keys=None, top=190):
        win, barh, ch = make_window(content, ww, title)
        CH = max(2160, win.height + top + 360)
        self.CH = CH
        comp = bg(self.CW, CH).convert("RGBA")
        wx = (self.CW - ww) // 2
        sh = Image.new("RGBA", (ww + 400, win.height + 400), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([200, 240, 200 + ww, 240 + win.height], 40, fill=(0, 0, 0, 200))
        sh = sh.filter(ImageFilter.GaussianBlur(70))
        comp.paste(sh, (wx - 200, top - 200), sh)
        comp.paste(win, (wx, top), win)
        self.comp = comp.convert("RGB")
        self.X0, self.Y0, self.cw, self.chh = wx, top + barh, ww, ch
        self.keys = keys or [(0, 0.5, 0.5, 1.05)]

    def cam(self, t):
        k = self.keys
        if t <= k[0][0]:
            u, v, z = k[0][1], k[0][2], self.CW / (self.cw * k[0][3])
        elif t >= k[-1][0]:
            u, v, z = k[-1][1], k[-1][2], self.CW / (self.cw * k[-1][3])
        else:
            for a, b in zip(k, k[1:], strict=False):
                if a[0] <= t <= b[0]:
                    e = sm((t - a[0]) / (b[0] - a[0]))
                    u, v = lerp(a[1], b[1], e), lerp(a[2], b[2], e)
                    z = self.CW / (self.cw * math.exp(lerp(math.log(a[3]), math.log(b[3]), e)))
                    break
        Vw = self.CW / z
        Vh = Vw * 9 / 16
        cx, cy = self.X0 + u * self.cw, self.Y0 + v * self.chh
        x0 = clamp(cx - Vw / 2, 0, self.CW - Vw)
        y0 = clamp(cy - Vh * 0.43, 0, self.CH - Vh)
        return x0, y0, Vw, Vh

    def frame(self, t):
        x0, y0, Vw, Vh = self.cam(t)
        return self.comp.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + Vw, y0 + Vh))

    def to_screen(self, t, u, v):
        x0, y0, Vw, Vh = self.cam(t)
        return ((self.X0 + u * self.cw - x0) * W / Vw, (self.Y0 + v * self.chh - y0) * W / Vw)


# Callouts drawn while a frame renders; render.py dims everything outside them (`spotlight`)
SPOT = []


def spotlight(im, spots, strength=0.55):
    """`im` with everything outside the union of `spots` ((x0, y0, x1, y1), progress) dimmed, so the eye goes
    where the narration is."""
    if not spots:
        return im
    m = Image.new("L", (W, H), int(255 * strength * max(p for _, p in spots)))
    d = ImageDraw.Draw(m)
    for box, _p in spots:
        d.rounded_rectangle(box, 26, fill=0)
    m = m.filter(ImageFilter.GaussianBlur(16))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im.convert("RGB"), m)


def callout(layer, box, label, col, p, side="top", fs=30):
    """Glowing rectangle around box=(x0,y0,x1,y1) in screen px, with a label; p is progress 0..1."""
    if p <= 0.01:
        return
    d = ImageDraw.Draw(layer, "RGBA")
    x0, y0, x1, y1 = box
    g = 10 * (1 - p)
    x0, y0, x1, y1 = x0 - g - 8, y0 - g - 8, x1 + g + 8, y1 + g + 8
    for i, al in ((16, 0.06), (9, 0.11), (4, 0.18)):
        d.rounded_rectangle([x0 - i, y0 - i, x1 + i, y1 + i], 16 + i, outline=fade(col, al * p), width=3)
    d.rounded_rectangle([x0, y0, x1, y1], 16, outline=fade(col, p), width=4)
    if label:
        f = AV(fs, "demi")
        tw = d.textlength(label, font=f)
        lx = x0
        ly = y0 - fs - 26 if side == "top" else y1 + 12
        d.rounded_rectangle([lx, ly, lx + tw + 32, ly + fs + 18], 12, fill=fade(col, 0.95 * p))
        d.text((lx + 16, ly + 7), label, font=f, fill=(8, 10, 16, int(255 * p)))
        x1, y0, y1 = max(x1, lx + tw + 32), min(y0, ly), max(y1, ly + fs + 18)
    SPOT.append(((x0 - 22, y0 - 22, x1 + 22, y1 + 22), p))


# ---------------------------------------------------------------- captions
_cap_grad = None


def caption_layer(text, a):
    global _cap_grad
    if _cap_grad is None:
        Image.new("RGBA", (W, 300), (0, 0, 0, 0))
        px = np.zeros((300, W, 4), np.uint8)
        al = (np.linspace(0, 1, 300) ** 1.6 * 170).astype(np.uint8)
        px[..., 3] = al[:, None]
        _cap_grad = Image.fromarray(px, "RGBA")
    lay = rgba_canvas()
    lay.paste(_cap_grad, (0, H - 300))
    if a > 0.01:
        # A subtitle box, so the words stay readable over busy screenshots
        d = ImageDraw.Draw(lay, "RGBA")
        f = AV(38, "demi")
        ls = wrap(d, text, f, 1400)
        lh = 52
        bw = max(d.textlength(l, font=f) for l in ls) + 64  # noqa: E741
        bh = len(ls) * lh + 26
        y = H - 46 - bh
        d.rounded_rectangle(
            [(W - bw) / 2, y, (W + bw) / 2, y + bh],
            16,
            fill=(6, 9, 18, int(215 * a)),
            outline=(255, 255, 255, int(30 * a)),
            width=2,
        )
        for i, l in enumerate(ls):  # noqa: E741
            w = d.textlength(l, font=f)
            d.text(((W - w) / 2, y + 11 + i * lh), l, font=f, fill=(255, 255, 255, int(255 * a)))
    return lay


# ---------------------------------------------------------------- word timing
def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def spoken(t):
    t = re.sub(r"\bLLM\b", "L L M", t)
    t = re.sub(r"\bMCP\b", "M C P", t)
    t = re.sub(r"\bCNCF\b", "C N C F", t)
    t = re.sub(r"\bSRE\b", "S R E", t)
    return (
        t.replace("STS", "S T S")
        .replace("GRAPH.COPY", "graph copy")
        .replace("theseus.yaml", "theseus dot yaml")
        .replace("FalkorDB", "Falkor D B")
    )


def captions(text, most=12):
    """Caption chunks: sentences, then clauses at ; or :, then halves at the comma nearest the middle,
    until no chunk is longer than `most` words, so a caption never runs past two lines."""
    out = []
    for s in re.split(r"(?<=[.!?;:])\s+", text):
        parts = [s.strip()] if s.strip() else []
        while True:
            long = [p for p in parts if len(p.split()) > most and "," in p[:-1]]
            if not long:
                break
            p = long[0]
            ws = p.split()
            commas = [i for i, w in enumerate(ws[:-1]) if w.endswith(",")]
            i = min(commas, key=lambda i: abs(i + 1 - len(ws) / 2))
            k = parts.index(p)
            parts[k : k + 1] = [" ".join(ws[: i + 1]), " ".join(ws[i + 1 :])]
        out += [p.rstrip(",;") for p in parts]
    return out


class Timing:
    """Word times (seconds from scene start, lead included) and caption sentences for one scene."""

    def __init__(self, sc, lead=0.3):
        self.lead = lead
        self.ev = [(a + lead, b + lead, norm(w)) for a, b, w in sc["words"]]
        self.dur = sc["dur"]
        self.show = sc.get("captions", True)  # a title card already shows its words
        sents = captions(sc["show"])
        counts = [len(spoken(s).split()) for s in sents]
        tot = sum(counts)
        n = len(self.ev)
        self.caps = []
        c = 0
        for s, k in zip(sents, counts, strict=False):
            i0 = min(n - 1, round(c * n / tot))
            i1 = min(n, max(i0 + 1, round((c + k) * n / tot)))
            self.caps.append((self.ev[i0][0] - 0.05, self.ev[i1 - 1][1] + 0.25, s))
            c += k

    def at(self, phrase, nth=1, default=0.0):
        toks = [norm(p) for p in phrase.split()]
        hits = 0
        for i in range(len(self.ev) - len(toks) + 1):
            if all(self.ev[i + j][2] == toks[j] for j in range(len(toks))):
                hits += 1
                if hits == nth:
                    return self.ev[i][0]
        return default

    def end(self):
        return self.ev[-1][1]

    def cap(self, t):
        for a, b, s in self.caps if self.show else []:
            if a <= t <= b:
                return s, min(1, (t - a) / 0.18, (b - t) / 0.2)
        return None, 0


# ---- Pillow ignores the alpha of a text fill; make fades real
_orig_Draw = ImageDraw.Draw
_orig_text = ImageDraw.ImageDraw.text


def _Draw(im, mode=None):
    d = _orig_Draw(im, mode)
    d._pil = im
    return d


def _text(self, xy, text, fill=None, font=None, anchor=None, **kw):
    if isinstance(fill, tuple) and len(fill) == 4 and fill[3] < 255 and hasattr(self, "_pil"):
        a = fill[3]
        if a <= 2:
            return
        bb = self.textbbox(xy, text, font=font, **kw)
        x0, y0, x1, y1 = int(bb[0]) - 3, int(bb[1]) - 3, int(bb[2]) + 3, int(bb[3]) + 3
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        m = Image.new("L", (w, h), 0)
        _orig_Draw(m).text((xy[0] - x0, xy[1] - y0), text, font=font, fill=255, **kw)
        m = m.point(lambda v: v * a // 255)
        self._pil.paste(Image.new("RGB", (w, h), tuple(fill[:3])), (x0, y0), m)
        return
    return _orig_text(self, xy, text, fill=fill, font=font, anchor=anchor, **kw)


ImageDraw.Draw = _Draw
ImageDraw.ImageDraw.text = _text
