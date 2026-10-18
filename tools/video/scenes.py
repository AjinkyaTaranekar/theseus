"""The 14 scenes. Each factory takes a Timing and returns an object with .frame(t) -> RGB and .sfx."""

import os

from kit import (
    AV,
    BLUE,
    DIM,
    FG,
    GRN,
    LINE,
    MO,
    PANEL,
    RED,
    YEL,
    W,
    Win,
    arrow,
    bg,
    callout,
    card,
    center,
    clamp,
    dot_on,
    fade,
    lerp,
    mixc,
    over,
    pill,
    rgba_canvas,
    ss,
    wrap,
)
from PIL import Image, ImageDraw, ImageFilter

HI = "captures/"
REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "theseus", "web") + os.sep
_img = {}


def load(p):
    if p not in _img:
        _img[p] = Image.open(p).convert("RGB")
    return _img[p]


def stack(imgs, gap=50, bgc=(10, 10, 12)):
    w = max(i.width for i in imgs)
    h = sum(i.height for i in imgs) + gap * (len(imgs) - 1)
    out = Image.new("RGB", (w, h), bgc)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


class Scene:
    sfx = []

    def chip(self, layer, text, col=BLUE, a=1.0):
        pill(ImageDraw.Draw(layer, "RGBA"), 64, 52, text, col, a, fs=24)


# ===================================================================== 1 hook
class S01(Scene):
    def __init__(s, tm):
        s.a = tm.at
        s.t_int, s.t_pr, s.t_pol = tm.at("intern"), tm.at("pull"), tm.at("policy")
        s.t_app, s.t_mer, s.t_db = tm.at("approve"), tm.at("merge"), tm.at("database")
        s.sfx = [(s.t_pr, "whoosh", 0), (s.t_db + 0.1, "ping", 330)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        p = ss(t, 0.15, 0.7)
        pill(d, 126, 60, "THE POSTMORTEM", RED, p, fs=24)
        d.text((120, 110 - (1 - p) * 20), "A routine change.", font=AV(120, "bold"), fill=fade(FG, p))
        q = ss(t, s.t_int, s.t_int + 0.5)
        d.text((126, 262), "An intern joins the support team.", font=AV(44, "reg"), fill=fade(DIM, q))
        # diff card
        cp = ss(t, s.t_pr - 0.2, s.t_pr + 0.6)
        x0, y0, w, h = 380, 340 + (1 - cp) * 50, 1160, 370
        red = ss(t, s.t_mer, s.t_mer + 0.5)
        ok = ss(t, s.t_app, s.t_app + 0.4) * (1 - red)
        col = mixc(mixc(LINE, GRN, ok), RED, red)
        card(d, x0, y0, w, h, col=col, a=cp, glow=ok > 0.3 or red > 0.3)
        d.text(
            (x0 + 30, y0 + 22),
            "Add Priya to support-engineers for prod log access",
            font=AV(34, "demi"),
            fill=fade(FG, cp),
        )
        d.text((x0 + 30, y0 + 74), "terraform/people.tf", font=MO(22), fill=fade(DIM, cp))
        d.text((x0 + w - 150, y0 + 70), "+5  -0", font=MO(22), fill=fade(GRN, cp))
        code = [
            'resource "aws_iam_user_group_membership" "priya_support" {',
            '  user   = "priya-intern"',
            '  groups = ["support-engineers"]',
            "}",
        ]
        typ = ss(t, s.t_pr + 0.2, s.t_pr + 1.6)
        for i, c in enumerate(code):
            ly = y0 + 126 + i * 56
            rowc = mixc((20, 52, 34), (80, 24, 30), red)
            d.rectangle(
                [x0 + 18, ly, x0 + w - 18, ly + 48], fill=fade(rowc, cp * (1 if typ * 4 > i else 0.0))
            )
            n = int(len(c) * clamp(typ * 4 - i))
            d.text((x0 + 36, ly + 8), "+", font=MO(28), fill=fade(GRN, cp))
            d.text((x0 + 76, ly + 8), c[:n], font=MO(28), fill=fade(FG, cp))
        pp = ss(t, s.t_pol, s.t_pol + 0.4)
        if pp > 0:
            pill(d, 1130, 150, "IAM policies changed: 0", GRN, pp, fs=30)
        if ok > 0.01:
            pill(d, x0 + w - 230, y0 + h - 70, "looks fine", GRN, ok, fs=26)
        # path
        names = ["priya-intern", "support-engineers", "prod-support", "prod-db-credentials", "customer-db"]
        wd, gap, px0, py = 290, 80, 70, 800
        T0 = s.t_mer + 0.15
        T1 = s.t_db
        for i, n in enumerate(names):
            ta = lerp(T0, T1, i / 4)
            ap = ss(t, ta, ta + 0.3)
            if ap <= 0:
                continue
            x = px0 + i * (wd + gap)
            hot = i == 4
            card(
                d,
                x,
                py,
                wd,
                96,
                None,
                None,
                col=RED if hot else BLUE,
                a=ap,
                fill=(60, 18, 26) if hot else PANEL,
                glow=hot,
            )
            center(d, n, py + 28, AV(28, "demi"), fade(FG, ap), x + wd / 2)
            if i > 0:
                arrow(d, x - gap + 8, py + 48, x - 8, py + 48, RED, 5, ss(t, ta - 0.25, ta + 0.1), ap)
        if t > T1:
            k = (t - T1) * 2
            if k < 3:
                r = 60 + 80 * (k % 1)
                x = px0 + 4 * (wd + gap) + wd / 2
                d.ellipse(
                    [x - r, py + 48 - r, x + r, py + 48 + r], outline=fade(RED, 0.8 * (1 - (k % 1))), width=4
                )
        return im.convert("RGB")


# ===================================================================== 2 problem
class S02(Scene):
    def __init__(s, tm):
        s.tg = [tm.at("group"), tm.at("role"), tm.at("secret"), tm.at("database")]
        s.t_sc, s.t_no, s.t_end = tm.at("scanners"), tm.at("nobody"), tm.end()
        s.sfx = [(s.t_no, "whoosh", 0), (s.t_no + 0.9, "ping", 330)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        h = ss(t, 0.2, 0.7)
        d.text((110, 100 - (1 - h) * 16), "The danger is in the path.", font=AV(84, "bold"), fill=fade(FG, h))
        names = [
            ("support-engineers", "group"),
            ("prod-support", "role"),
            ("prod-db-credentials", "secret"),
            ("customer-db", "database"),
        ]
        cw, gap, x0, y0 = 380, 60, 110, 330
        red = ss(t, s.t_no, s.t_no + 1.0)
        for i, (n, k) in enumerate(names):
            ap = ss(t, s.tg[i] - 0.1, s.tg[i] + 0.35)
            if ap <= 0:
                continue
            x = x0 + i * (cw + gap)
            hot = i == 3
            col = mixc(LINE, RED, red)
            card(
                d,
                x,
                y0,
                cw,
                190,
                n,
                k,
                col=col,
                a=ap,
                fill=mixc(PANEL, (58, 20, 28), red),
                fs=34,
                glow=red > 0.5 and hot,
            )
            if red < 0.5:
                d.ellipse([x + 26, y0 + 148, x + 40, y0 + 162], fill=fade(GRN, ap))
                d.text((x + 50, y0 + 140), "fine on its own", font=AV(24), fill=fade(DIM, ap))
            if i > 0:
                arrow(
                    d,
                    x - gap + 6,
                    y0 + 95,
                    x - 6,
                    y0 + 95,
                    RED,
                    6,
                    ss(t, s.t_no + i * 0.25 - 0.25, s.t_no + i * 0.25 + 0.2),
                    red,
                )
        # scanner brackets
        sp = ss(t, s.t_sc, s.t_sc + 0.2) * (1 - ss(t, s.t_no - 0.1, s.t_no + 0.3))
        if sp > 0:
            k = clamp((t - s.t_sc) / max(0.5, s.t_no - s.t_sc - 0.3)) * 3.99
            i = int(k)
            x = x0 + i * (cw + gap)
            d.rounded_rectangle([x - 12, y0 - 12, x + cw + 12, y0 + 202], 26, outline=fade(BLUE, sp), width=5)
            pill(d, x, y0 - 78, "scanner: one resource at a time", BLUE, sp, fs=26)
        nb = ss(t, s.t_no + 0.7, s.t_no + 1.3)
        if nb > 0:
            center(d, "The path nobody reviews.", 650 - (1 - nb) * 16, AV(78, "bold"), fade(RED, nb))
        return im.convert("RGB")


# ===================================================================== 3 title
class S03(Scene):
    def __init__(s, tm):
        s.logo = Image.open(HI + "logo.png").convert("RGBA")
        s.sfx = [(0.35, "whoosh", 0)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        a = ss(t, 0.2, 0.9)
        lg = s.logo.resize((300, 300), Image.LANCZOS)
        glow = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([150, 150, 450, 450], fill=(70, 120, 255, 55))
        glow = glow.filter(ImageFilter.GaussianBlur(60))
        im.paste(glow, (W // 2 - 300, 70 - 150), glow)
        la = lg.copy()
        la.putalpha(la.getchannel("A").point(lambda v: int(v * a)))
        im.paste(la, (W // 2 - 150, 90 - int((1 - a) * 30)), la)
        center(d, "THESEUS", 410, AV(170, "heavy"), fade(FG, ss(t, 0.5, 1.1)))
        center(
            d,
            "A graph agent that reviews infrastructure changes before they merge.",
            640,
            AV(46, "reg"),
            fade(DIM, ss(t, 1.0, 1.6)),
        )
        center(
            d, "Built on FalkorDB  ·  Graph Hacks Track 01", 730, AV(34, "demi"), fade(BLUE, ss(t, 1.5, 2.1))
        )
        k = ss(t, 2.0, 2.6)
        d.line([(W // 2 - 220, 808), (W // 2 + 220, 808)], fill=fade(LINE, k), width=2)
        center(d, "TEAM PROJECT HAIL MARY", 832, AV(28, "demi"), fade(DIM, k))
        center(d, "Ajinkya Taranekar  ·  Sakshi Chitnis", 876, AV(40, "demi"), fade(FG, k))
        return im.convert("RGB")


# ===================================================================== 4 sources -> graph
class S04(Scene):
    def __init__(s, tm):
        s.t_g, s.t_1, s.t_2, s.t_3 = tm.at("graph"), tm.at("pull"), tm.at("terraform"), tm.at("code")
        s.t_c, s.t_gap = tm.at("cites"), tm.at("gap")
        s.sfx = [(s.t_g, "whoosh", 0), (s.t_gap + 0.3, "ping", 330)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        L = [
            ("What the PR says", "title and description, read as untrusted data", s.t_1, BLUE),
            ("What Terraform allows", "IAM, trust and secrets from the plan", s.t_2, BLUE),
            ("What the code calls", "SDK calls and service URLs from app code", s.t_3, YEL),
        ]
        gx, gy, gw, gh = 760, 300, 420, 360
        ga = ss(t, s.t_g, s.t_g + 0.5)
        for i, (n, sub, tt, col) in enumerate(L):
            ap = ss(t, tt - 0.1, tt + 0.4)
            y = 250 + i * 210
            if ap > 0:
                card(d, 100, y, 540, 160, n, sub, col=col, a=ap, fs=36, glow=True)
                arrow(
                    d, 640, y + 80, gx - 6, gy + gh / 2 + (i - 1) * 60, col, 4, ss(t, tt + 0.1, tt + 0.5), ap
                )
                if t > tt + 0.5:
                    dot_on(d, 640, y + 80, gx - 6, gy + gh / 2 + (i - 1) * 60, t, col, 0.6, 2)
        if ga > 0:
            for k in (2, 1, 0):
                card(
                    d,
                    gx + k * 22,
                    gy - k * 22,
                    gw,
                    gh,
                    None,
                    None,
                    col=BLUE,
                    a=ga * (0.45 if k else 1),
                    fill=(14, 30, 58),
                )
            center(d, "FalkorDB", gy + 120, AV(66, "heavy"), fade(FG, ga), gx + gw / 2 + 0)
            center(d, "one graph per commit", gy + 210, AV(32), fade(DIM, ga), gx + gw / 2)
            center(d, "a GRAPH.COPY per fix", gy + 252, AV(32), fade(DIM, ga), gx + gw / 2)
        ec = ss(t, s.t_c, s.t_c + 0.5)
        if ec > 0:
            pill(d, gx - 10, gy + gh + 50, "terraform/people.tf:83", GRN, ec, fs=30)
            d.text(
                (gx + 20, gy + gh + 112),
                "every edge keeps its file and line",
                font=AV(26),
                fill=fade(DIM, ec),
            )
        gp = ss(t, s.t_gap, s.t_gap + 0.5)
        if gp > 0:
            arrow(d, gx + gw + 30, gy + gh / 2, 1370, gy + gh / 2, RED, 5, gp, gp)
            d.text((1390, 190), "Every gap is a finding", font=AV(42, "bold"), fill=fade(RED, gp))
            G = [
                ("Grants beyond intent", "the PR says logs, the change grants customer-db"),
                ("Use beyond intent", "the code reads data the PR never named"),
                ("Allowed but never called", "the fix that breaks nobody"),
            ]
            for i, (n, sub) in enumerate(G):
                a2 = ss(t, s.t_gap + 0.3 + i * 0.25, s.t_gap + 0.7 + i * 0.25)
                card(d, 1390, 260 + i * 190, 440, 150, n, sub, col=RED, a=a2, fill=(44, 18, 26), fs=32)
        return im.convert("RGB")


# ===================================================================== 5 who decides what
class S05(Scene):
    def __init__(s, tm):
        s.t = [tm.at("person"), tm.at("l l m"), tm.at("jev"), tm.at("engine")]
        s.sfx = [(s.t[3], "ping", 262), (s.t[2], "ping", 330), (s.t[1], "ping", 392), (s.t[0], "chime", 523)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        d.text((110, 70), "Who decides what", font=AV(66, "bold"), fill=FG)
        rows = [
            (
                "A person",
                "decides what ships",
                "approves one tested fix, or rejects them all",
                "is skipped: silence never counts as approval",
                GRN,
            ),
            (
                "System Two · the LLM",
                "proposes and explains",
                "proposes fixes, writes the report, cites evidence",
                "commits, or states a fact the engine did not return",
                BLUE,
            ),
            (
                "System One · Jev",
                "ranks and vetoes",
                "rates sensitivity, urgency, likely-needed access",
                "approves a fix, or counts as evidence",
                YEL,
            ),
            (
                "Engine + FalkorDB",
                "establishes the facts",
                "decides paths, the diff, required access, UNKNOWN",
                "guesses: the same inputs give the same answer",
                RED,
            ),
        ]
        for r, (title, sub, does, never, col) in enumerate(rows):
            tt = s.t[r]
            ap = ss(t, tt - 0.1, tt + 0.45)
            if ap <= 0:
                continue
            y = 190 + r * 190
            card(d, 140, y, 1640, 160, None, None, col=col, a=ap, glow=t < tt + 1.4)
            d.text((180, y + 22), title, font=AV(38, "demi"), fill=fade(col, ap))
            d.text((180, y + 80), sub, font=AV(28), fill=fade(DIM, ap))
            d.text((720, y + 26), "Does", font=AV(24, "demi"), fill=fade(GRN, ap))
            d.text((810, y + 22), does, font=AV(30), fill=fade(FG, ap))
            d.text((720, y + 88), "Never", font=AV(24, "demi"), fill=fade(RED, ap))
            d.text((810, y + 84), never, font=AV(30), fill=fade(FG, ap))
        return im.convert("RGB")


# ===================================================================== 6 live run
def _seg_scene(segs, t, tm_end):
    """segs: [(t0, Win, overlay_fn)] -> crossfade between windows."""
    cur = 0
    for i, (t0, w, ov) in enumerate(segs):  # noqa: B007
        if t >= t0:
            cur = i
    t0, w, ov = segs[cur]
    f = w.frame(t - t0)
    lay = rgba_canvas()
    if ov:
        ov(lay, w, t - t0, t)
    im = f.convert("RGBA")
    over(im, lay)
    if cur > 0 and t - t0 < 0.3:  # crossfade from previous
        pt0, pw, pov = segs[cur - 1]
        pf = pw.frame(t - pt0).convert("RGBA")
        pl = rgba_canvas()
        if pov:
            pov(pl, pw, t - pt0, t)
        over(pf, pl)
        im = Image.blend(pf, im, (t - t0) / 0.3)
    return im.convert("RGB")


class S06(Scene):
    def __init__(s, tm):
        s.tm = tm
        s.t_two = tm.at("here")
        s.t_hops = tm.at("four")
        rev = load(REPO + "shot-review.jpg")
        s.w1 = Win(
            rev,
            ww=2300,
            title="Theseus · review of a pull request",
            keys=[(0, 0.5, 0.5, 1.12), (tm.at("diffs"), 0.5, 0.5, 1.0), (s.t_two - 0.2, 0.45, 0.55, 0.72)],
        )
        pg = stack([load(HI + "try-verdict.png"), load(HI + "try-path1.png")], gap=50)
        s.w2 = Win(
            pg,
            ww=3100,
            title="Theseus · Try it · live run",
            keys=[
                (0, 0.5, 0.13, 1.05),
                (s.t_hops - 0.1, 0.5, 0.62, 0.98),
                (s.t_hops + 0.6, 0.5, 0.62, 0.98),
                (tm.at("line") - 0.2, 0.38, 0.84, 0.62),
            ],
        )
        s.sfx = [(tm.at("open"), "whoosh", 0), (s.t_two, "ping", 330)]

    def frame(s, t):
        tm = s.tm

        def ov1(lay, w, tt, tabs):
            Ww = ImageDraw.Draw(lay, "RGBA")
            pill(Ww, 64, 52, "LIVE · review page", BLUE, 1.0, fs=24)
            p = ss(tabs, s.t_two, s.t_two + 0.5)
            x0, y0 = w.to_screen(tt, 0.165, 0.485)
            x1, y1 = w.to_screen(tt, 0.345, 0.525)
            callout(lay, (x0, y0, x1, y1), "", RED, p, "top", 26)
            x0, y0 = w.to_screen(tt, 0.375, 0.335)
            x1, y1 = w.to_screen(tt, 0.51, 0.37)
            callout(
                lay,
                (x0, y0, x1, y1),
                "3 new ways in",
                RED,
                ss(tabs, s.t_two + 0.4, s.t_two + 0.9),
                "bottom",
                26,
            )

        def ov2(lay, w, tt, tabs):
            pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · Try-it page", BLUE, 1.0, fs=24)
            p = ss(tabs, s.t_hops + 0.35, s.t_hops + 0.85)
            x0, y0 = w.to_screen(tt, 0.02, 0.49)
            x1, y1 = w.to_screen(tt, 0.98, 0.70)
            callout(lay, (x0, y0, x1, y1), "four hops to customer-db", RED, p, "top", 30)
            q = ss(tabs, tm.at("line") - 0.1, tm.at("line") + 0.5)
            x0, y0 = w.to_screen(tt, 0.02, 0.74)
            x1, y1 = w.to_screen(tt, 0.60, 1.0)
            callout(lay, (x0, y0, x1, y1), "every hop cites its Terraform line", GRN, q, "top", 30)

        return _seg_scene([(0, s.w1, ov1), (s.t_hops + 0.2, s.w2, ov2)], t, 0)


# ===================================================================== 7 the fix
class S07(Scene):
    def __init__(s, tm):
        s.tm = tm
        s.t_rm, s.t_mf, s.t_role = tm.at("removing"), tm.at("max"), tm.at("narrower")
        s.t_one, s.t_ver = tm.at("one passes") if tm.at("one passes") else tm.at("passes"), tm.at("verified")
        fx, tr = load(HI + "try-fixes.png"), load(HI + "try-trace.png")
        s.st = stack([fx, tr], gap=60)
        s.frac = fx.height / s.st.height
        s.tfrac = (fx.height + 60) / s.st.height
        s.hh = 1.0
        s.w = Win(
            s.st,
            ww=3000,
            title="Theseus · fixes tested on graph copies",
            keys=[
                (0, 0.5, s.frac * 0.5, 1.05),
                (s.t_rm - 0.3, 0.5, s.frac * 0.5, 1.05),
                (s.t_rm + 0.2, 0.4, s.frac * 0.76, 0.8),
                (s.t_mf + 0.5, 0.5, s.frac * 0.5, 1.0),
                (s.t_role - 0.2, 0.4, s.frac * 0.43, 0.8),
                (s.t_ver - 0.3, 0.4, s.frac * 0.43, 0.8),
                (s.t_ver + 0.4, 0.5, s.tfrac + (1 - s.tfrac) * 0.4, 1.0),
            ],
        )
        s.sfx = [(s.t_rm, "ping", 220), (s.t_mf, "whoosh", 0), (s.t_role + 0.2, "chime", 523)]

    def frame(s, t):
        f = s.w.frame(t).convert("RGBA")
        lay = rgba_canvas()
        d = ImageDraw.Draw(lay, "RGBA")
        pill(d, 64, 52, "LIVE · fix verdicts from the engine", BLUE, 1.0, fs=24)

        def rv(a, b):
            return (s.w.to_screen(t, 0.01, s.frac * a), s.w.to_screen(t, 0.99, s.frac * b))

        # revert row
        p = ss(t, s.t_rm, s.t_rm + 0.4) * (1 - ss(t, s.t_mf - 0.2, s.t_mf + 0.2))
        (x0, y0), (x1, y1) = rv(0.72, 0.84)
        callout(lay, (x0, y0, x1, y1), "closes the paths, breaks her onboarding", RED, p, "top", 30)
        # max flow card
        mp = ss(t, s.t_mf, s.t_mf + 0.5) * (1 - ss(t, s.t_role - 0.6, s.t_role - 0.2))
        if mp > 0.01:
            cx, cy, cw, ch = 1010, 280, 800, 330
            d.rounded_rectangle(
                [cx, cy + (1 - mp) * 30, cx + cw, cy + ch + (1 - mp) * 30],
                28,
                fill=fade((8, 12, 24), 0.96 * mp),
                outline=fade(BLUE, mp),
                width=4,
            )
            yy = cy + (1 - mp) * 30
            d.text((cx + 40, yy + 28), "algo.maxFlow in FalkorDB", font=AV(34, "demi"), fill=fade(DIM, mp))
            val = int(1_000_000 * ss(t, s.t_mf + 0.1, s.t_mf + 1.0))
            d.text((cx + 40, yy + 86), f"{val:,}", font=AV(110, "heavy"), fill=fade(RED, mp))
            d.text((cx + 40, yy + 224), "required access is uncuttable:", font=AV(32), fill=fade(FG, mp))
            d.text((cx + 40, yy + 266), "no single permission can go", font=AV(32, "demi"), fill=fade(FG, mp))
        # winner row
        wp = ss(t, s.t_role, s.t_role + 0.4)
        (x0, y0), (x1, y1) = rv(0.35, 0.51)
        callout(
            lay,
            (x0, y0, x1, y1),
            "a new, narrower role: passes",
            GRN,
            wp * (1 - ss(t, s.t_ver, s.t_ver + 0.3)),
            "top",
            30,
        )
        # trace
        tp = ss(t, s.t_ver, s.t_ver + 0.5)
        if tp > 0.01:
            a, b = s.tfrac, 1.0
            x0, y0 = s.w.to_screen(t, 0.01, a + (b - a) * 0.50)
            x1, y1 = s.w.to_screen(t, 0.99, a + (b - a) * 0.78)
            callout(lay, (x0, y0, x1, y1), "the engine verified it, not the model", GRN, tp, "top", 30)
        over(f, lay)
        return f.convert("RGB")


# ===================================================================== 8 GitHub
class S08(Scene):
    def __init__(s, tm):
        s.t_apply, s.t_app, s.t_rev, s.t_flag = (
            tm.at("replies"),
            tm.at("commits"),
            tm.at("reviews"),
            tm.at("flagged"),
        )
        c = load(REPO + "shot-comment.jpg")
        top = c.crop((0, 0, 814, 250))
        diag = c.crop((0, 296, 814, 578))
        s.comment = stack([top, diag], gap=14, bgc=(13, 17, 23))
        s.sfx = [(s.t_apply, "whoosh", 0), (s.t_rev + 0.5, "chime", 659)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        pill(d, 64, 52, "Real thread on GitHub", BLUE, 1.0, fs=24)
        a = ss(t, 0.1, 0.7)
        cw = 880
        c = s.comment.resize((cw, int(s.comment.height * cw / s.comment.width)), Image.LANCZOS).convert(
            "RGBA"
        )
        sh = Image.new("RGBA", (cw + 120, c.height + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([60, 70, 60 + cw, 70 + c.height], 20, fill=(0, 0, 0, 190))
        sh = sh.filter(ImageFilter.GaussianBlur(24))
        im.paste(sh, (90 - 60, 150 - 40), sh)
        mask = Image.new("L", c.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, c.width - 1, c.height - 1], 16, fill=int(255 * a))
        im.paste(c, (90, 150 - int((1 - a) * 24)), mask)
        d.text(
            (90, 150 + c.height + 18),
            "Theseus blocks the merge: the PR says logs, the change reaches customer-db",
            font=AV(24),
            fill=fade(DIM, a),
        )
        # right: thread
        x0, w = 1090, 740
        u = ss(t, s.t_apply - 0.1, s.t_apply + 0.5)
        card(d, x0, 190, w, 120, None, None, col=LINE, a=u)
        d.text((x0 + 28, 208), "reviewer", font=AV(24), fill=fade(DIM, u))
        txt = "/theseus apply"
        n = int(len(txt) * ss(t, s.t_apply, s.t_apply + 0.6))
        d.text((x0 + 28, 244), txt[:n], font=MO(40), fill=fade(GRN, u))
        b = ss(t, s.t_app - 0.1, s.t_app + 0.5)
        card(d, x0, 350, w, 290, None, None, col=BLUE, a=b, glow=True)
        d.text((x0 + 28, 368), "theseus-graph-review  BOT", font=AV(24, "demi"), fill=fade(BLUE, b))
        lines = wrap(
            d,
            "Committed the fix (the agent's fix) to demo/intern-e2e as 29fb960 (people.tf, theseus_fixes.tf). "  # noqa: E501
            "Theseus reviews the new head now; the comment and the check update when it finishes.",
            AV(30),
            w - 56,
        )
        for i, l in enumerate(lines):  # noqa: E741
            d.text((x0 + 28, 412 + i * 40), l, font=AV(30), fill=fade(FG, b))
        g = ss(t, s.t_rev, s.t_rev + 0.5)
        if g > 0:
            card(d, x0, 680, w, 190, None, None, col=GRN, a=g, glow=True, fill=(14, 40, 26))
            d.ellipse([x0 + 30, 716, x0 + 66, 752], fill=fade(GRN, g))
            d.text((x0 + 86, 710), "No new access to sensitive data", font=AV(38, "demi"), fill=fade(FG, g))
            d.text(
                (x0 + 30, 780),
                "Every path to sensitive data in this commit was traced:",
                font=AV(26),
                fill=fade(DIM, g),
            )
            d.text((x0 + 30, 814), "none of them is new.", font=AV(26), fill=fade(DIM, g))
        lay = rgba_canvas()
        callout(
            lay,
            (128, 286, 884, 324),
            "text that tries to steer the review is flagged and ignored",
            YEL,
            ss(t, s.t_flag - 0.1, s.t_flag + 0.4),
            "bottom",
            28,
        )
        over(im, lay)
        return im.convert("RGB")


# ===================================================================== 9 reads the code
class S09(Scene):
    def __init__(s, tm):
        s.tm = tm
        s.t_blk, s.t_line, s.t_no = tm.at("blocked"), tm.at("line"), tm.at("cited")
        s.w = Win(
            load(HI + "r124-top.png"),
            ww=3000,
            title="Theseus · review of a typo-fix pull request",
            keys=[
                (0, 0.33, 0.14, 0.66),
                (tm.at("starts"), 0.33, 0.14, 0.66),
                (s.t_blk, 0.47, 0.47, 0.97),
                (s.t_line + 0.3, 0.37, 0.45, 0.6),
                (s.t_no - 0.1, 0.5, 0.2, 1.0),
            ],
        )
        s.sfx = [(s.t_blk, "ping", 262), (s.t_line, "chime", 523)]

    def frame(s, t):
        f = s.w.frame(t).convert("RGBA")
        lay = rgba_canvas()
        pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · review page", BLUE, 1.0, fs=24)
        x0, y0 = s.w.to_screen(t, 0.685, 0.02)
        x1, y1 = s.w.to_screen(t, 0.776, 0.058)
        callout(lay, (x0, y0, x1, y1), "merge blocked", RED, ss(t, s.t_blk, s.t_blk + 0.4), "bottom", 28)
        x0, y0 = s.w.to_screen(t, 0.24, 0.415)
        x1, y1 = s.w.to_screen(t, 0.5, 0.455)
        callout(
            lay,
            (x0, y0, x1, y1),
            "its code now takes this route · export.py:40",
            RED,
            ss(t, s.t_line, s.t_line + 0.4),
            "top",
            30,
        )
        x0, y0 = s.w.to_screen(t, 0.02, 0.185)
        x1, y1 = s.w.to_screen(t, 0.50, 0.225)
        callout(
            lay,
            (x0, y0, x1, y1),
            "the PR says it changes no access",
            YEL,
            ss(t, s.t_no, s.t_no + 0.4),
            "bottom",
            28,
        )
        over(f, lay)
        return f.convert("RGB")


# ===================================================================== 10 plugin terminal
class S10(Scene):
    def __init__(s, tm):
        s.t_cmd, s.t_hook = tm.at("plugin"), tm.at("hook")
        s.sfx = [(s.t_cmd, "whoosh", 0), (s.t_hook, "ping", 262)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        pill(d, 64, 52, "Claude Code plugin · real output", BLUE, 1.0, fs=24)
        a = ss(t, 0.1, 0.6)
        x0, y0, w, h = 130, 150, 1660, 700
        d.rounded_rectangle([x0 - 8, y0 - 8, x0 + w + 8, y0 + h + 8], 30, fill=(0, 0, 0, int(110 * a)))
        d.rounded_rectangle(
            [x0, y0, x0 + w, y0 + h], 26, fill=fade((14, 14, 16), 0.97 * a), outline=fade(LINE, a), width=3
        )
        for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([x0 + 28 + i * 40, y0 + 22, x0 + 28 + i * 40 + 22, y0 + 44], fill=fade(col, a))
        d.text((x0 + w / 2 - 120, y0 + 18), "claude · theseus plugin", font=AV(26, "med"), fill=fade(DIM, a))
        lines = [
            ("> /theseus:check give priya-intern read access to the production logs", GRN, 0.4),
            ("● theseus · check_change", DIM, 1.9),
            ("Theseus check: BLOCKED. priya-intern can reach customer-db.", RED, 2.5),
            ("It opens 3 dangerous paths and closes 0.", FG, 3.4),
            (
                "priya-intern is in support-engineers (people.tf:83, new) → can become prod-support (people.tf:56)",  # noqa: E501
                FG,
                4.4,
            ),
            ("   → can read prod-db-credentials (roles.tf:36) → opens customer-db (data.tf:31)", FG, 5.2),
            ("Built in FalkorDB: 86 nodes, 189 edges; 6.3 s.", DIM, 6.4),
        ]
        yy = y0 + 90
        base = s.t_cmd - 0.3
        for text, col, dt in lines:
            tt = base + dt * 0.62
            k = ss(t, tt, tt + (0.9 if dt < 1 else 0.35))
            if k > 0:
                f = MO(23)
                wrap(d, text, f, 1560) if False else [text]
                n = int(len(text) * (k if dt < 1 else 1))
                d.text((x0 + 36, yy), text[:n], font=f, fill=fade(col, 1 if dt < 1 else k))
            yy += 62 if text.startswith("It opens") or text.startswith("Theseus check") else 56
        hp = ss(t, s.t_hook, s.t_hook + 0.5)
        if hp > 0:
            card(
                d, x0 + 36, y0 + h - 130, w - 72, 96, None, None, col=RED, a=hp, fill=(56, 16, 24), glow=True
            )
            d.text(
                (x0 + 70, y0 + h - 108),
                "hook: commit stopped before it reaches a pull request",
                font=AV(38, "demi"),
                fill=fade(FG, hp),
            )
        return im.convert("RGB")


# ===================================================================== 11 findings
class S11(Scene):
    def __init__(s, tm):
        s.tm = tm
        s.t_tr, s.t_urg, s.t_pr, s.t_rot = (
            tm.at("traces"),
            tm.at("production"),
            tm.at("opens"),
            tm.at("rotate"),
        )
        s.w = Win(
            load(HI + "dash-findings1.png"),
            ww=3100,
            title="Theseus · dashboard · Findings",
            keys=[
                (0, 0.64, 0.80, 0.88),
                (s.t_tr, 0.64, 0.82, 0.84),
                (s.t_pr, 0.68, 0.82, 0.8),
                (s.t_rot - 0.2, 0.72, 0.82, 0.8),
            ],
        )
        s.sfx = [(s.t_tr, "whoosh", 0), (s.t_pr, "chime", 523)]

    def frame(s, t):
        f = s.w.frame(t).convert("RGBA")
        lay = rgba_canvas()
        pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · Findings · a compromised Action", BLUE, 1.0, fs=24)

        def box(u0, v0, u1, v1, lab, col, p, side="top"):
            x0, y0 = s.w.to_screen(t, u0, v0)
            x1, y1 = s.w.to_screen(t, u1, v1)
            callout(lay, (x0, y0, x1, y1), lab, col, p, side, 28)

        box(0.46, 0.765, 0.635, 0.865, "could reach customer-db", RED, ss(t, s.t_tr + 0.3, s.t_tr + 0.8))
        box(0.322, 0.762, 0.366, 0.792, "urgency", YEL, ss(t, s.t_urg, s.t_urg + 0.4), "bottom")
        box(0.71, 0.76, 0.82, 0.797, "containment passes", GRN, ss(t, s.t_pr - 0.3, s.t_pr + 0.2), "bottom")
        box(0.935, 0.762, 0.98, 0.845, "PR #111", GRN, ss(t, s.t_pr, s.t_pr + 0.4), "top")
        box(0.86, 0.762, 0.918, 0.815, "rotate these", YEL, ss(t, s.t_rot, s.t_rot + 0.4), "bottom")
        over(f, lay)
        return f.convert("RGB")


# ===================================================================== 12 estate (intro)
class S12(Scene):
    def __init__(s, tm):
        s.w = Win(
            load(HI + "dash-overview-b.png"),
            ww=3000,
            title="Theseus · dashboard · Overview",
            keys=[(0, 0.5, 0.5, 1.12), (3, 0.5, 0.42, 1.0)],
        )
        s.sfx = [(0.1, "whoosh", 0)]

    def frame(s, t):
        f = s.w.frame(t).convert("RGBA")
        lay = rgba_canvas()
        pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · dashboard of main", BLUE, 1.0, fs=24)
        p = ss(t, 0.3, 0.8)
        x0, y0 = s.w.to_screen(t, 0.19, 0.31)
        x1, y1 = s.w.to_screen(t, 0.99, 0.52)
        callout(
            lay,
            (x0, y0, x1, y1),
            "23 dangerous paths · 5 of 11 PRs blocked · cost is an estimate",
            BLUE,
            p,
            "top",
            28,
        )
        over(f, lay)
        return f.convert("RGB")


# ===================================================================== W weak points
class SW(Scene):
    def __init__(s, tm):
        s.tm = tm
        s.t_sec, s.t_four, s.t_brk, s.t_open = tm.at("secret"), tm.at("four"), tm.at("breaks"), tm.at("open")
        s.w = Win(
            load(HI + "weak-open.png"),
            ww=3000,
            title="Theseus · dashboard · Weak points",
            keys=[
                (0, 0.58, 0.42, 0.95),
                (s.t_sec - 0.2, 0.6, 0.42, 0.82),
                (s.t_brk - 0.2, 0.58, 0.52, 0.82),
                (s.t_open - 0.2, 0.6, 0.78, 0.9),
            ],
        )
        s.sfx = [(s.t_sec, "ping", 262), (s.t_brk, "ping", 220), (s.t_open, "chime", 523)]

    def frame(s, t):
        f = s.w.frame(t).convert("RGBA")
        lay = rgba_canvas()
        pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · Weak points", BLUE, 1.0, fs=24)

        def box(u0, v0, u1, v1, lab, col, p, side="top"):
            x0, y0 = s.w.to_screen(t, u0, v0)
            x1, y1 = s.w.to_screen(t, u1, v1)
            callout(lay, (x0, y0, x1, y1), lab, col, p, side, 28)

        box(
            0.2,
            0.345,
            0.975,
            0.445,
            "one secret: 3 actors depend on it, 4 dependencies",
            YEL,
            ss(t, s.t_sec, s.t_sec + 0.4) * (1 - ss(t, s.t_brk, s.t_brk + 0.3)),
        )
        box(
            0.2,
            0.475,
            0.89,
            0.55,
            "if it breaks, all of them lose access at once",
            RED,
            ss(t, s.t_brk, s.t_brk + 0.4) * (1 - ss(t, s.t_open + 0.2, s.t_open + 0.5)),
        )
        box(0.2, 0.595, 0.98, 0.965, "every route through it", BLUE, ss(t, s.t_open, s.t_open + 0.5))
        over(f, lay)
        return f.convert("RGB")


# ===================================================================== I incidents / blast radius
class SI(Scene):
    def __init__(s, tm):
        s.tm = tm
        s.t_14, s.t_11, s.t_24, s.t_bl = (
            tm.at("fourteen"),
            tm.at("eleven"),
            tm.at("twentyfour"),
            tm.at("blast"),
        )
        s.w1 = Win(
            load(HI + "inc-open.png"),
            ww=3000,
            title="Theseus · dashboard · Incidents",
            keys=[(0, 0.58, 0.42, 1.0), (s.t_14 - 0.3, 0.6, 0.4, 0.85), (s.t_11 + 0.4, 0.62, 0.4, 0.85)],
        )
        s.w2 = Win(
            load(HI + "inc-open-b.png"),
            ww=3000,
            title="Theseus · dashboard · Incidents · AWS STS down",
            keys=[(0, 0.58, 0.5, 1.0), (s.t_24 - 0.6, 0.58, 0.5, 0.95), (s.t_bl - 0.2, 0.58, 0.78, 0.95)],
        )
        s.sw = s.t_11 + 0.5
        s.sfx = [(s.t_14, "ping", 262), (s.t_11, "ping", 220), (s.t_24, "ping", 196), (s.t_bl, "chime", 523)]

    def frame(s, t):
        t14, t11, t24, tbl = s.t_14, s.t_11, s.t_24, s.t_bl

        def ov1(lay, w, tt, tabs):
            pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · Incidents", BLUE, 1.0, fs=24)

            def box(u0, v0, u1, v1, lab, col, p, side="top"):
                x0, y0 = w.to_screen(tt, u0, v0)
                x1, y1 = w.to_screen(tt, u1, v1)
                callout(lay, (x0, y0, x1, y1), lab, col, p, side, 28)

            box(
                0.19,
                0.352,
                0.975,
                0.418,
                "AWS STS: pick a service",
                BLUE,
                ss(tabs, 0.5, 0.9) * (1 - ss(tabs, t14 + 0.4, t14 + 0.7)),
            )
            box(0.405, 0.352, 0.6, 0.418, "14 run here · 14 go down", RED, ss(tabs, t14, t14 + 0.4))
            box(0.66, 0.352, 0.74, 0.418, "11 lose access", YEL, ss(tabs, t11, t11 + 0.4), "bottom")
            box(0.83, 0.352, 0.94, 0.418, "24/25 dependencies", RED, ss(tabs, t24 - 0.3, t24 + 0.1))

        def ov2(lay, w, tt, tabs):
            pill(ImageDraw.Draw(lay, "RGBA"), 64, 52, "LIVE · blast radius", BLUE, 1.0, fs=24)

            def box(u0, v0, u1, v1, lab, col, p, side="top"):
                x0, y0 = w.to_screen(tt, u0, v0)
                x1, y1 = w.to_screen(tt, u1, v1)
                callout(lay, (x0, y0, x1, y1), lab, col, p, side, 28)

            box(
                0.19,
                0.337,
                0.45,
                0.533,
                "goes down: 14",
                RED,
                ss(tabs, s.sw, s.sw + 0.3) * (1 - ss(tabs, t24 - 0.3, t24)),
            )
            box(
                0.725,
                0.337,
                0.985,
                0.533,
                "lose access: 11",
                YEL,
                ss(tabs, s.sw, s.sw + 0.3) * (1 - ss(tabs, t24 - 0.3, t24)),
            )
            box(
                0.19,
                0.555,
                0.45,
                0.75,
                "dependencies broken: 24/25",
                RED,
                ss(tabs, t24 - 0.2, t24 + 0.3) * (1 - ss(tabs, tbl - 0.1, tbl + 0.2)),
                "bottom",
            )
            box(
                0.19, 0.765, 0.985, 0.92, "the blast radius, before the outage", GRN, ss(tabs, tbl, tbl + 0.5)
            )

        return _seg_scene([(0, s.w1, ov1), (s.sw, s.w2, ov2)], t, 0)


# ===================================================================== G whole graph
class SG(Scene):
    def __init__(s, tm):
        s.t_red, s.t_yel = tm.at("red"), tm.at("yellow")
        s.t_ei = tm.at("eightysix")
        if os.path.exists(HI + "graph-crop.png"):
            c = load(HI + "graph-crop.png")
        else:  # the graph panel of capture6's full-page shot, without the side bar
            g = load(HI + "graph-everything.png")
            box = (0.171 * g.width, 0.165 * g.height, 0.986 * g.width, 0.962 * g.height)
            c = g.crop(tuple(int(v) for v in box))
        s.w = Win(
            c,
            ww=1750,
            title="Theseus · dashboard · Graph · everything",
            keys=[(0, 0.5, 0.5, 1.8), (8, 0.5, 0.5, 1.72)],
        )
        s.sfx = [(0.1, "whoosh", 0), (s.t_red, "ping", 262), (s.t_yel, "ping", 392)]

    def frame(s, t):
        f = s.w.frame(t).convert("RGBA")
        lay = rgba_canvas()
        d = ImageDraw.Draw(lay, "RGBA")
        pill(d, 64, 52, "LIVE · the whole graph", BLUE, 1.0, fs=24)
        a = ss(t, 0.2, 0.8)
        d.text((70, 250 - (1 - a) * 14), "86 nodes", font=AV(76, "heavy"), fill=fade(FG, a))
        d.text((70, 340), "188 edges", font=AV(76, "heavy"), fill=fade(FG, a))
        d.text((70, 450), "read from FalkorDB now", font=AV(27), fill=fade(DIM, a))
        d.text((70, 520), "who acts · groups · roles", font=AV(28), fill=fade(DIM, a))
        d.text((70, 560), "· secrets · data", font=AV(28), fill=fade(DIM, a))
        r = ss(t, s.t_red - 0.1, s.t_red + 0.4)
        y = ss(t, s.t_yel - 0.1, s.t_yel + 0.4)
        card(
            d,
            1470,
            250,
            400,
            150,
            "Red",
            "a path to sensitive data nothing requires",
            col=RED,
            a=r,
            fs=44,
            subfs=26,
            fill=(44, 18, 26),
        )
        card(
            d,
            1470,
            450,
            400,
            150,
            "Yellow",
            "a single point of failure",
            col=YEL,
            a=y,
            fs=44,
            subfs=26,
            fill=(44, 36, 12),
        )
        over(f, lay)
        return f.convert("RGB")


# ===================================================================== 13 trust + tools
class S13(Scene):
    def __init__(s, tm):
        s.t_c, s.t_u, s.t_ten, s.t_any = tm.at("cites"), tm.at("unknown"), tm.at("ten"), tm.at("any")
        s.sfx = [(s.t_c, "ping", 330), (s.t_u, "ping", 262), (s.t_ten, "whoosh", 0)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        d.text((110, 90), "Honest by construction", font=AV(70, "bold"), fill=FG)
        a = ss(t, s.t_c - 0.1, s.t_c + 0.5)
        card(
            d,
            110,
            240,
            820,
            260,
            "Every claim cites evidence",
            "A checker rejects any evidence ID that does not exist in the graph.",
            col=GRN,
            a=a,
            fs=42,
            subfs=30,
            glow=True,
        )
        b = ss(t, s.t_u - 0.1, s.t_u + 0.5)
        card(
            d,
            990,
            240,
            820,
            260,
            "UNKNOWN is a real answer",
            "Outside the supported IAM subset, it says so instead of guessing.",
            col=YEL,
            a=b,
            fs=42,
            subfs=30,
            glow=True,
        )
        tools = [
            "diff_paths",
            "blast_radius",
            "explain_path",
            "shortest_route",
            "min_cut",
            "simulate_fix",
            "choke_points",
            "unused_grants",
            "secrets_reachable",
            "check_requirements",
        ]
        c = ss(t, s.t_ten - 0.1, s.t_ten + 0.4)
        if c > 0:
            d.text((110, 580), "Ten graph tools, one MCP server:", font=AV(40, "demi"), fill=fade(FG, c))
            for i, n in enumerate(tools):
                tp = ss(t, s.t_ten + 0.2 + i * 0.12, s.t_ten + 0.5 + i * 0.12)
                if tp <= 0:
                    continue
                x = 110 + (i % 5) * 350
                y = 660 + (i // 5) * 100
                d.rounded_rectangle(
                    [x, y, x + 320, y + 76],
                    18,
                    fill=fade((16, 22, 38), 0.95 * tp),
                    outline=fade(BLUE, tp),
                    width=2,
                )
                center(d, n, y + 22, MO(26), fade(FG, tp), x + 160)
        return im.convert("RGB")


# ===================================================================== 14 close
class S14(Scene):
    def __init__(s, tm):
        s.t_rm, s.t_st, s.t_try = tm.at("next"), tm.at("start"), tm.at("try")
        s.logo = Image.open(HI + "logo.png").convert("RGBA").resize((200, 200), Image.LANCZOS)
        s.hero = load(HI + "land-hero.png")
        s.sfx = [(s.t_st, "whoosh", 0), (s.t_try, "chime", 523)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        # phase A: roadmap
        A = ss(t, 0.1, 0.5) * (1 - ss(t, s.t_st - 0.4, s.t_st))
        if A > 0.01:
            pill(d, 64, 52, "ROADMAP", YEL, A, fs=24)
            card(
                d,
                160,
                270,
                560,
                150,
                "Terraform plan",
                "what this change will do",
                col=BLUE,
                a=A,
                fs=40,
                glow=True,
            )
            card(
                d,
                160,
                480,
                560,
                150,
                "Cartography",
                "what already runs: AWS, GitHub, Okta",
                col=YEL,
                a=A,
                fs=40,
                glow=True,
            )
            arrow(d, 720, 345, 900, 440, DIM, 4, A, A)
            arrow(d, 720, 555, 900, 480, DIM, 4, A, A)
            card(
                d,
                900,
                350,
                380,
                200,
                "FalkorDB graph",
                "same labels",
                col=BLUE,
                a=A,
                fs=40,
                fill=(14, 30, 58),
                glow=True,
            )
            arrow(d, 1280, 450, 1400, 450, DIM, 4, A, A)
            card(
                d,
                1400,
                350,
                360,
                200,
                "Same engine",
                "paths · cut · fixes",
                col=RED,
                a=A,
                fs=40,
                fill=(44, 18, 26),
                glow=True,
            )
            center(
                d,
                "Node labels follow Cartography's ontology, so a live cloud map can feed the same engine.",
                720,
                AV(32),
                fade(DIM, A),
            )
        # phase B: steps
        B = ss(t, s.t_st - 0.1, s.t_st + 0.4) * (1 - ss(t, s.t_try - 0.4, s.t_try))
        if B > 0.01:
            pill(d, 64, 52, "GET STARTED", BLUE, B, fs=24)
            steps = ["Install the GitHub App", "Add theseus.yaml and the workflows", "Open a pull request"]
            for i, st in enumerate(steps):
                k = ss(t, s.t_st + 0.1 + i * 0.5, s.t_st + 0.5 + i * 0.5) * B
                y = 260 + i * 170
                d.ellipse([360, y, 450, y + 90], fill=fade(BLUE, k))
                center(d, str(i + 1), y + 14, AV(54, "heavy"), (8, 10, 16, int(255 * k)), 405)
                d.text((500, y + 14), st, font=AV(56, "demi"), fill=fade(FG, k))
        # phase C: end card
        C = ss(t, s.t_try - 0.2, s.t_try + 0.6)
        if C > 0.01:
            hs = s.hero.resize((880, 495), Image.LANCZOS).convert("RGBA")
            m = Image.new("L", hs.size, 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, 879, 494], 22, fill=int(255 * C))
            im.paste(hs, (520, 40 + int((1 - C) * 20)), m)
            d.rounded_rectangle([520, 40, 1400, 535], 22, outline=fade(LINE, C), width=3)
            center(d, "THESEUS", 556, AV(80, "heavy"), fade(FG, C))
            center(d, "Try it live:  guest-box.tail27b7c5.ts.net", 666, AV(42, "demi"), fade(BLUE, C))
            center(d, "Code:  github.com/AjinkyaTaranekar/theseus", 722, AV(32), fade(FG, C))
            d.line([(W // 2 - 260, 786), (W // 2 + 260, 786)], fill=fade(LINE, C), width=2)
            team = "Team Project Hail Mary  ·  Ajinkya Taranekar and Sakshi Chitnis"
            center(d, team, 806, AV(34, "demi"), fade(FG, C))
            center(
                d,
                "FalkorDB Graph Hacks  ·  Track 01: Agents That Act on Connected Data",
                856,
                AV(28, "demi"),
                fade(YEL, C),
            )
            center(
                d,
                "Synthetic infrastructure · AWS IAM subset · Python code · Network exposure not modelled · Cost is a list-price estimate",  # noqa: E501
                900,
                AV(22),
                fade(DIM, C),
            )
        return im.convert("RGB")


# ===================================================================== P positioning
class SP(Scene):
    def __init__(s, tm):
        s.t_c, s.t_t, s.t_w, s.t_s = (
            tm.at("cartography"),
            tm.at("theseus"),
            tm.at("whether"),
            tm.at("smallest"),
        )
        s.sfx = [(s.t_t, "whoosh", 0), (s.t_s, "chime", 523)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        h = ss(t, 0.1, 0.6)
        d.text((110, 90 - (1 - h) * 14), "Where Theseus fits", font=AV(80, "bold"), fill=fade(FG, h))
        a = ss(t, s.t_c - 0.1, s.t_c + 0.5)
        card(d, 110, 250, 760, 480, "Cartography (CNCF)", None, col=LINE, a=a, fs=44)
        for i, l in enumerate(["Reads the deployed cloud", "Finds the attack paths", "Runs after deploy"]):  # noqa: E741
            la = ss(t, s.t_c + 0.3 + i * 0.25, s.t_c + 0.7 + i * 0.25) * a
            d.text((150, 360 + i * 90), l, font=AV(38), fill=fade(DIM, la))
        b = ss(t, s.t_t - 0.1, s.t_t + 0.5)
        card(
            d,
            1000,
            250,
            810,
            480,
            "Theseus judges the change",
            None,
            col=BLUE,
            a=b,
            fs=44,
            glow=True,
            fill=(14, 28, 54),
        )
        L = [
            ("Reads the change, before merge", s.t_t + 0.2, FG),
            ("Compares what the PR says with what it grants", s.t_w, FG),
            ("Proves the smallest fix on graph copies", s.t_s, GRN),
            ("A person approves", s.t_s + 0.7, FG),
        ]
        for i, (l, tt, col) in enumerate(L):  # noqa: E741
            la = ss(t, tt - 0.05, tt + 0.4) * b
            d.ellipse(
                [1040, 372 + i * 82 + 8, 1058, 372 + i * 82 + 26], fill=fade(col if col != FG else BLUE, la)
            )
            d.text((1076, 360 + i * 82), l, font=AV(33, "demi"), fill=fade(col, la))
        return im


# ===================================================================== F FalkorDB under the hood
def code_tokens(line):
    import re

    out = []
    for m in re.finditer(
        r"(MATCH|RETURN|CALL|YIELD|GRAPH\.COPY|CREATE|UNWIND)|('[^']*')|(\$\w+)|([^\s]+|\s+)", line
    ):
        kw, st, pr, other = m.groups()
        out.append((m.group(0), BLUE if kw else YEL if st else GRN if pr else FG))
    return out


def draw_code(d, x, y, lines, fs, nchars, a, lh=36):
    f = MO(fs)
    left = int(nchars)
    for i, ln in enumerate(lines):
        xx = x
        for tok, col in code_tokens(ln):
            if left <= 0:
                return
            sh = tok[:left]
            left -= len(tok)
            d.text((xx, y + i * lh), sh, font=f, fill=fade(col, a))
            xx += d.textlength(tok, font=f)
        left -= 1


class SF(Scene):
    def __init__(s, tm):
        s.t = [tm.at("cypher"), tm.at("max"), tm.at("copy"), tm.at("without")]
        s.sfx = [(s.t[0], "ping", 330), (s.t[1], "ping", 392), (s.t[2], "ping", 440), (s.t[3], "chime", 523)]

    def frame(s, t):
        im = bg()
        d = ImageDraw.Draw(im, "RGBA")
        h = ss(t, 0.1, 0.6)
        d.text((110, 70 - (1 - h) * 14), "FalkorDB does the work", font=AV(70, "bold"), fill=fade(FG, h))
        bands = [
            (
                "Cypher",
                "every route from an actor",
                "3 new paths · 4 hops",
                [
                    "MATCH p = (a:Node {id: $actor})",
                    "  -[:MEMBER_OF|CAN_ASSUME|TRUSTS|RUNS_AS|CAN|UNLOCKS*1..7]->(r:Resource)",
                    "RETURN [rel IN relationships(p) | rel.eid] AS eids",
                ],
            ),
            (
                "algo.maxFlow",
                "the minimum cut",
                "max flow ≥ 1,000,000: not cuttable",
                [
                    "CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts,",
                    "    capacityProperty: 'capacity', relationshipTypes: ['FLOW']})",
                    "YIELD maxFlow, edges, edgeFlows",
                ],
            ),
            (
                "GRAPH.COPY",
                "a graph per candidate fix",
                "4 candidates · 4 graph copies",
                ["GRAPH.COPY demo-infra__pr85-head demo-infra__pr85-fix-b"],
            ),
        ]
        for i, (title, sub, res, code) in enumerate(bands):
            tt = s.t[i]
            a = ss(t, tt - 0.15, tt + 0.5)
            if a <= 0:
                continue
            y = 190 + i * 210
            card(d, 110, y, 1700, 190, None, None, col=BLUE, a=a, fill=(11, 16, 30), glow=t < tt + 1.2)
            d.text((150, y + 26), title, font=AV(44, "bold"), fill=fade(BLUE, a))
            d.text((150, y + 84), sub, font=AV(28), fill=fade(DIM, a))
            d.text((150, y + 128), res, font=AV(28, "demi"), fill=fade(GRN, a * ss(t, tt + 0.9, tt + 1.4)))
            n = len("".join(code)) * 1.4 * ss(t, tt, tt + 1.6)
            draw_code(d, 636, y + 28, code, 25, n, a, 44)
        c = ss(t, s.t[3], s.t[3] + 0.6)
        center(d, "No FalkorDB: no paths, no diff, no fix test.", 840, AV(48, "bold"), fade(RED, c))
        return im


SCENES = [S01, S02, S03, SP, S04, S05, S06, S07, S08, S09, S10, S11, S12, SW, SI, SG, SF, S13, S14]
