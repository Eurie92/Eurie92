# Builds every static SVG in assets/ from the sources in scripts/src.
# usage: python scripts/build-art.py   (needs Pillow + fonttools + brotli)
# The ledger SVG is not built here: scripts/ledger.mjs redraws it daily from GitHub.
import base64, io, json, math, random, re
from pathlib import Path
from PIL import Image, ImageFilter
from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "src"
OUT = ROOT / "assets"

# palette, mirrored from the portfolio (src/lib/palette.ts)
INK = "#0b0a10"
VIOLET, LILAC, DEEP = "#b7a6e1", "#e1d9f6", "#806cb4"
GILT, BONE, UMBER = "#c9a46a", "#f1e4c6", "#7a6443"
MUTED = "#8b8597"

# ---------------------------------------------------------------- fonts
ASCII = "".join(chr(c) for c in range(32, 127)) + " ·—–’‘“”…✦×←→↓"


def font_b64(name):
    f = TTFont(SRC / name)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga"]
    s = subset.Subsetter(opts)
    s.populate(text=ASCII)
    s.subset(f)
    buf = io.BytesIO()
    f.flavor = "woff2"
    f.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


FONTS = {
    "serif": font_b64("instrument-serif-latin-400-normal.woff2"),
    "serif-i": font_b64("instrument-serif-latin-400-italic.woff2"),
    "mono": font_b64("geist-mono-latin-400-normal.woff2"),
}
(OUT / "fonts.json").write_text(json.dumps(FONTS))  # for ledger.mjs


def font_css(*which):
    fam = {"serif": ("S", "normal"), "serif-i": ("S", "italic"), "mono": ("M", "normal")}
    out = []
    for w in which:
        name, style = fam[w]
        out.append(
            f"@font-face{{font-family:{name};font-style:{style};"
            f"src:url(data:font/woff2;base64,{FONTS[w]}) format('woff2')}}"
        )
    return "".join(out)


BASE_CSS = (
    ".s{font-family:S,'Instrument Serif',Georgia,'Times New Roman',serif}"
    ".i{font-family:S,'Instrument Serif',Georgia,serif;font-style:italic}"
    ".m{font-family:M,'Geist Mono',ui-monospace,Consolas,monospace}"
    "text{white-space:pre}@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg(w, h, body, css="", fonts=("serif", "serif-i", "mono"), title=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
        f"<title>{esc(title)}</title>"
        f"<style>{font_css(*fonts)}{BASE_CSS}{css}</style>"
        f'<rect width="{w}" height="{h}" fill="{INK}"/>{body}</svg>'
    )


def write(name, text):
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"{name:22s} {len(text.encode()) / 1024:6.1f} KB")


# ---------------------------------------------------------------- ascii
CODE_RAMP = [  # light → dense, several glyphs per step so it reads as source code
    ".`'", ":,;", "-~_", "=+<>", "/\\|!", "()[]{}", "?*ijl", "0o$x", "#%&", "@MW",
]


def ascii_grid(img, cols, rows, mode, seed=7):
    """mode 'ink': dark pixels on light ground (alpha aware) are the subject.
    mode 'light': light pixels on dark ground are the subject.
    Returns rows of (char, tone 0..2) or None."""
    rnd = random.Random(seed)
    im = img.convert("RGBA")
    alpha = im.getchannel("A").resize((cols, rows), Image.LANCZOS)
    lum = im.convert("L")
    edges = lum.filter(ImageFilter.FIND_EDGES).resize((cols, rows), Image.LANCZOS)
    lum = lum.resize((cols, rows), Image.LANCZOS)
    grid = []
    for y in range(rows):
        row = []
        for x in range(cols):
            a = alpha.getpixel((x, y)) / 255
            l = lum.getpixel((x, y)) / 255
            e = edges.getpixel((x, y)) / 255
            if mode == "ink":
                v = (1 - l) * a  # how much ink
                if a < 0.35 or v < 0.08:
                    row.append(None)
                    continue
                # carved highlights glow, shadows sink: tone by brightness inside the figure
                tone = 2 if l > 0.42 or e > 0.22 else (1 if l > 0.17 else 0)
                dens = min(0.999, 0.35 + v * 0.65)
            else:
                v = l
                if v < 0.16:
                    row.append(None)
                    continue
                tone = 2 if v > 0.72 else (1 if v > 0.42 else 0)
                dens = min(0.999, v)
            step = CODE_RAMP[int(dens * len(CODE_RAMP))]
            row.append((rnd.choice(step), tone))
        grid.append(row)
    return grid


def grid_text(grid, x0, y0, cw, ch, size, tone_cls, extra=""):
    """Each tone becomes its own layer of full-width rows (other tones blanked),
    pinned with textLength so any monospace fallback still lines up."""
    cols = len(grid[0])
    layers = []
    for t in range(3):
        rows = []
        for r, row in enumerate(grid):
            s = "".join(c[0] if c and c[1] == t else " " for c in row)
            if not s.replace(" ", ""):
                continue
            rows.append(
                f'<text x="{x0}" y="{y0 + (r + 1) * ch:.1f}" textLength="{cols * cw:.1f}" '
                f'lengthAdjust="spacing">{esc(s)}</text>'
            )
        layers.append(f'<g class="{tone_cls[t]}" font-size="{size}" xml:space="preserve" {extra}>{"".join(rows)}</g>')
    return "".join(layers)


# ---------------------------------------------------------------- pieces
WALL = [l.rstrip().replace("\t", "  ") for l in (SRC / "wall.txt").read_text(encoding="utf-8").splitlines()]


def code_wall(x, y, w, h, start, numbered, size=11, lh=16, clip_id="w"):
    lines = WALL[start:] + WALL[:start]
    maxc = int(w / (size * 0.6))
    n = int(h / lh) + 2
    rows = []
    for k in range(n * 2):  # two copies for a seamless scroll
        i = k % len(lines)
        t = lines[i][:maxc]
        num = f'<tspan fill="{DEEP}">{(start + i) % 900 + 1:>3}  </tspan>' if numbered else ""
        rows.append(f'<text x="{x}" y="{y + (k + 1) * lh}">{num}{esc(t)}</text>')
    period = n * lh
    return (
        f'<clipPath id="{clip_id}"><rect x="{x - 4}" y="{y}" width="{w + 40}" height="{h}"/></clipPath>'
        f'<g clip-path="url(#{clip_id})" mask="url(#fade)"><g class="m wall" font-size="{size}" fill="{LILAC}" '
        f'xml:space="preserve" style="--p:-{period}px">{"".join(rows)}</g></g>'
    )


def chain(p0, p1, sag, link=14, color="#55506a", hi="#8e86a6"):
    """Iron links along a sagging curve: open ovals alternate with edge-on bars."""
    (x0, y0), (x1, y1) = p0, p1
    cx, cy = (x0 + x1) / 2, max(y0, y1) + sag
    pts = []
    for i in range(400):
        t = i / 399
        pts.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
                    (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1))
    out, acc, prev, k = [], 0.0, pts[0], 0
    for p in pts[1:]:
        acc += math.dist(p, prev)
        if acc >= link * 0.82:
            acc = 0
            ang = math.degrees(math.atan2(p[1] - prev[1], p[0] - prev[0]))
            if k % 2 == 0:
                out.append(f'<ellipse cx="{p[0]:.1f}" cy="{p[1]:.1f}" rx="{link / 2:.1f}" ry="{link / 3.6:.1f}" '
                           f'transform="rotate({ang:.1f} {p[0]:.1f} {p[1]:.1f})" fill="none" stroke="{color}" stroke-width="2.6"/>'
                           f'<ellipse cx="{p[0]:.1f}" cy="{p[1] - 1:.1f}" rx="{link / 2.6:.1f}" ry="{link / 6:.1f}" '
                           f'transform="rotate({ang:.1f} {p[0]:.1f} {p[1]:.1f})" fill="none" stroke="{hi}" stroke-width=".7" opacity=".55"/>')
            else:
                out.append(f'<rect x="{p[0] - link / 2:.1f}" y="{p[1] - 1.6:.1f}" width="{link:.1f}" height="3.2" rx="1.6" '
                           f'transform="rotate({ang:.1f} {p[0]:.1f} {p[1]:.1f})" fill="{color}"/>')
            k += 1
        prev = p
    return "".join(out)


HERO_CSS = (
    f".t0{{fill:{DEEP}}}.t1{{fill:{VIOLET}}}.t2{{fill:{LILAC}}}"
    ".t1{animation:sh 5s ease-in-out infinite}.t2{animation:sh 3.7s ease-in-out -1.3s infinite}"
    "@keyframes sh{0%,100%{opacity:1}50%{opacity:.55}}"
    ".wall{opacity:.13;animation:up 70s linear infinite}"
    "@keyframes up{to{transform:translateY(var(--p))}}"
    ".halo{animation:glow 4.5s ease-in-out infinite}"
    "@keyframes glow{0%,100%{opacity:.55}50%{opacity:1}}"
    ".cur{animation:blink 1.1s steps(1) infinite}@keyframes blink{50%{opacity:0}}"
    ".fall{animation:fall 9s cubic-bezier(.5,0,.8,.6) infinite}"
    "@keyframes fall{0%{transform:translateY(-40px);opacity:0}10%{opacity:.9}100%{transform:translateY(620px);opacity:0}}"
)


def defs_common(w, h):
    return (
        "<defs>"
        f'<radialGradient id="aura" cx="50%" cy="34%" r="55%"><stop offset="0" stop-color="{DEEP}" stop-opacity=".28"/>'
        f'<stop offset=".55" stop-color="{DEEP}" stop-opacity=".06"/><stop offset="1" stop-color="{INK}" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="fg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        '<stop offset=".18" stop-color="#fff"/><stop offset=".78" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
        f'<mask id="fade"><rect width="{w}" height="{h}" fill="url(#fg)"/></mask>'
        f'<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{INK}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{INK}" stop-opacity=".95"/></linearGradient>'
        '<filter id="soft" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="3"/></filter>'
        "</defs>"
    )


def falling_glyphs(w, n, seed=3):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        x = rnd.uniform(w * 0.08, w * 0.92)
        d = rnd.uniform(0, 9)
        c = rnd.choice("{}<>/\\=;01")
        out.append(f'<text class="m fall" x="{x:.0f}" y="0" font-size="10" fill="{VIOLET}" '
                   f'style="animation-delay:-{d:.2f}s;animation-duration:{rnd.uniform(7, 12):.1f}s">{esc(c)}</text>')
    return "".join(out)


ANGEL = Image.open(SRC / "archangel-reference.png")
AW, AH = ANGEL.size
HALO = (372 / AW, 372 / AH, 82 / AW, 20 / AH)  # cx, cy, rx, ry as fractions of the image
SHOULDERS = ((318 / AW, 452 / AH), (428 / AW, 452 / AH))


def angel_block(cx, top, rows, size):
    cw, ch = size * 0.6, size * 0.94
    scale = rows * ch / AH
    cols = round(AW * scale / cw)
    x0 = cx - cols * cw / 2
    grid = ascii_grid(ANGEL, cols, rows, "ink")
    sx = lambda f: x0 + f * cols * cw
    sy = lambda f: top + f * rows * ch
    hx, hy, hrx, hry = HALO
    halo = (
        f'<g class="halo"><ellipse cx="{sx(hx):.1f}" cy="{sy(hy):.1f}" rx="{hrx * cols * cw:.1f}" ry="{hry * rows * ch:.1f}" '
        f'fill="none" stroke="{LILAC}" stroke-width="5" filter="url(#soft)" opacity=".7"/>'
        f'<ellipse cx="{sx(hx):.1f}" cy="{sy(hy):.1f}" rx="{hrx * cols * cw:.1f}" ry="{hry * rows * ch:.1f}" '
        f'fill="none" stroke="{LILAC}" stroke-width="1.6"/></g>'
    )
    body = grid_text(grid, round(x0, 1), top, cw, ch, size, ("t0", "t1", "t2"))
    body = f'<g class="m">{body}</g>'
    shoulders = [(sx(a), sy(b)) for a, b in SHOULDERS]
    return halo, body, shoulders


def hero(w, h, narrow=False):
    parts = [defs_common(w, h), f'<rect width="{w}" height="{h}" fill="url(#aura)"/>']
    if not narrow:
        parts += [code_wall(120, 40, 280, 420, 0, True, clip_id="wl"), code_wall(800, 40, 280, 420, 26, False, clip_id="wr")]
        halo, body, (ls, rs) = angel_block(w / 2, 20, 70, 7.4)
        parts.append(falling_glyphs(w, 14))
        parts.append(chain(ls, (-30, 470), 40) + chain(rs, (w + 30, 470), 40))
        parts += [body, halo, f'<rect y="{h - 200}" width="{w}" height="200" fill="url(#floor)"/>']
        parts.append(
            f'<text class="s" x="{w / 2}" y="{h - 70}" font-size="150" fill="#efe9f8" text-anchor="middle" '
            f'textLength="{w - 120}" lengthAdjust="spacingAndGlyphs">EURIE PAULINO</text>'
        )
        # margin narration, set like the site: vertical italic in the gutters, never over the angel
        parts.append(
            f'<text class="i" transform="translate(96 46) rotate(90)" font-size="17" fill="{LILAC}">Compiled from scratch.</text>'
            f'<text class="i" transform="translate(1110 46) rotate(90)" font-size="17" fill="{LILAC}">Bound to one name. '
            f"It’s signed on everything I build.</text>"
        )
        parts.append(
            f'<text class="m" x="40" y="40" font-size="11" fill="{MUTED}" letter-spacing="2">EP</text>'
            f'<text class="m" x="{w - 40}" y="40" font-size="11" fill="{MUTED}" letter-spacing="3" text-anchor="end">PROL. · THE SERAPH</text>'
            f'<text class="m" x="40" y="250" font-size="10" fill="{MUTED}" letter-spacing="3" transform="rotate(-90 40 250)">FALL</text>'
            f'<line x1="44" y1="270" x2="44" y2="380" stroke="{MUTED}" stroke-opacity=".4"/>'
            f'<text class="m" x="40" y="400" font-size="10" fill="{MUTED}">000</text>'
        )
        parts.append(
            f'<text class="i" x="56" y="{h - 34}" font-size="24" fill="{LILAC}">Software Engineer</text>'
            f'<text class="i" x="56" y="{h - 12}" font-size="16" fill="{MUTED}">So nothing leaves half-built.<tspan class="cur" fill="{VIOLET}"> _</tspan></text>'
            f'<text class="i" x="{w - 56}" y="{h - 34}" font-size="24" fill="{LILAC}" text-anchor="end">AI Engineer</text>'
            f'<text class="i" x="{w - 56}" y="{h - 12}" font-size="16" fill="{MUTED}" text-anchor="end">Websites. Web shops. Bots. AI tools.</text>'
        )
    else:
        parts += [f'<g opacity=".6">{code_wall(20, 40, 560, 470, 10, False, size=10, lh=14, clip_id="wn")}</g>']
        halo, body, (ls, rs) = angel_block(w / 2, 34, 92, 6.0)
        parts.append(falling_glyphs(w, 8))
        parts.append(chain(ls, (-30, 480), 30) + chain(rs, (w + 30, 480), 30))
        parts += [body, halo, f'<rect y="{h - 330}" width="{w}" height="330" fill="url(#floor)"/>']
        parts.append(
            f'<text class="s" x="{w / 2}" y="{h - 160}" font-size="120" fill="#efe9f8" text-anchor="middle" '
            f'textLength="{w - 140}" lengthAdjust="spacingAndGlyphs">EURIE</text>'
            f'<text class="s" x="{w / 2}" y="{h - 62}" font-size="120" fill="#efe9f8" text-anchor="middle" '
            f'textLength="{w - 60}" lengthAdjust="spacingAndGlyphs">PAULINO</text>'
            f'<text class="i" x="{w / 2}" y="{h - 26}" font-size="22" fill="{LILAC}" text-anchor="middle">Software Engineer · AI Engineer</text>'
            f'<text class="m" x="24" y="26" font-size="10" fill="{MUTED}" letter-spacing="2">EP</text>'
            f'<text class="m" x="{w - 24}" y="26" font-size="10" fill="{MUTED}" letter-spacing="3" text-anchor="end">PROL. · THE SERAPH</text>'
        )
    return svg(w, h, "".join(parts), HERO_CSS,
               title="Eurie Paulino. Software Engineer and AI Engineer. A chained seraph drawn in code glyphs.")


# ---------------------------------------------------------------- chapter plates
CHAPTERS = [
    ("i", "I", "Know thyself", "Code by trade, art by temperament.", "The name on the chains is mine."),
    ("iii", "III", "The Plates", "What I made.", "The wax melted. These shipped anyway."),
    ("iv", "IV", "The Commission", "What I can make for you.", "Those were mine. The next one is yours."),
    ("v", "V", "The Reliquary", "The tools I keep.", "Yours gets built with these."),
    ("vi", "VI", "The Ledger", "Every day, on record.", "Tools rust unused. Mine get swung daily."),
    ("vii", "VII", "The Creed", "What I believe.", "Why I show up daily."),
    ("epil", "Epil.", "Let’s build", "Your chapter.", "It hasn’t killed me yet."),
]


def plate(slug, num, name, beat, kicker, narrow=False):
    w, h = (600, 150) if narrow else (1200, 128)
    rule = "·" * (95 if narrow else 190)
    label = "EPILOGUE" if num == "Epil." else f"CHAPTER {esc(num)}"
    if narrow:
        body = (
            f'<text class="m" x="24" y="30" font-size="10" fill="{UMBER}" letter-spacing="3">{label}</text>'
            f'<text class="s" x="24" y="78" font-size="44" fill="{BONE}"><tspan fill="{GILT}">{esc(num)}</tspan>  {esc(name)}</text>'
            f'<text class="i" x="24" y="106" font-size="18" fill="{MUTED}">{esc(beat)}</text>'
            f'<text class="i" x="24" y="132" font-size="16" fill="{GILT}">“{esc(kicker)}”</text>'
        )
    else:
        body = (
            f'<text class="m" x="40" y="34" font-size="10" fill="{UMBER}" letter-spacing="3">{label}</text>'
            f'<text class="s" x="40" y="92" font-size="58" fill="{BONE}" xml:space="preserve"><tspan fill="{GILT}">{esc(num)}</tspan>  {esc(name)}</text>'
            f'<text class="i" x="{w - 40}" y="68" font-size="22" fill="{GILT}" text-anchor="end">“{esc(kicker)}”</text>'
            f'<text class="i" x="{w - 40}" y="94" font-size="17" fill="{MUTED}" text-anchor="end">{esc(beat)}</text>'
        )
    body += (f'<text class="m" x="{w / 2}" y="{h - 8}" font-size="8" fill="{UMBER}" text-anchor="middle" '
             f'textLength="{w - 48}" lengthAdjust="spacing" opacity=".8">{rule}</text>')
    return svg(w, h, body, title=f"Chapter {num}: {name}. {kicker}")


# ---------------------------------------------------------------- II. The Fall
FALL_CSS = (
    f".t0{{fill:{UMBER}}}.t1{{fill:{GILT}}}.t2{{fill:{BONE}}}"
    ".t2{animation:sh 4s ease-in-out infinite}@keyframes sh{0%,100%{opacity:1}50%{opacity:.6}}"
    ".sun{animation:glow 6s ease-in-out infinite}@keyframes glow{0%,100%{opacity:.25}50%{opacity:.6}}"
)


def wrap(text, n):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > n:
            lines.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    return lines + [cur]


def fall(narrow=False):
    ic = Image.open(SRC / "icarus-ascii.jpg")
    quote = ("Never regret thy fall, O Icarus of the fearless flight, for the greatest "
             "tragedy of them all is never to feel the burning light.")
    if narrow:
        w, h, rows, size, mx, my = 600, 900, 64, 7.4, 300, 300
    else:
        w, h, rows, size, mx, my = 1200, 470, 66, 6.6, 860, 235
    cw, ch = size * 0.6, size * 0.94
    cols = round(rows * ch / cw)
    grid = ascii_grid(ic, cols, rows, "light", seed=11)
    x0, y0 = mx - cols * cw / 2, my - rows * ch / 2
    sun = f'<circle class="sun" cx="{mx + cols * cw * 0.18:.0f}" cy="{y0 + rows * ch * 0.12:.0f}" r="90" fill="{GILT}" filter="url(#blur)"/>'
    art = sun + f'<g class="m">{grid_text(grid, round(x0, 1), y0, cw, ch, size, ("t0", "t1", "t2"))}</g>'
    defs = '<defs><filter id="blur" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="40"/></filter></defs>'
    if narrow:
        tx, ty, qn, qs = 40, 640, 34, 26
    else:
        tx, ty, qn, qs = 56, 150, 38, 30
    lines = wrap(quote, qn)
    q = "".join(f'<tspan x="{tx}" dy="{0 if i == 0 else qs * 1.2:.0f}">{"“" if i == 0 else ""}{esc(l)}{"”" if i == len(lines) - 1 else ""}</tspan>'
                for i, l in enumerate(lines))
    txt = (
        f'<text class="m" x="{tx}" y="{ty - 90}" font-size="10" fill="{UMBER}" letter-spacing="3">CHAPTER II</text>'
        f'<text class="s" x="{tx}" y="{ty - 40}" font-size="52" fill="{BONE}"><tspan fill="{GILT}">II</tspan>  The Fall</text>'
        f'<text class="i" x="{tx}" y="{ty + 20}" font-size="{qs}" fill="{BONE}">{q}</text>'
        f'<text class="m" x="{tx}" y="{ty + 40 + len(lines) * qs * 1.2:.0f}" font-size="11" fill="{MUTED}" letter-spacing="1">after Philippe Desportes, 1583</text>'
        f'<text class="i" x="{tx}" y="{ty + 80 + len(lines) * qs * 1.2:.0f}" font-size="20" fill="{GILT}">Fly close to the sun. Keep going.</text>'
    )
    return svg(w, h, defs + art + txt, FALL_CSS, title="Chapter II: The Fall. Icarus, drawn in code glyphs. " + quote)


# ---------------------------------------------------------------- VII. The Creed
ENTRIES = [
    "craft (kraft) n. 1. Skill in making things well, by hand or by code. 2. The part of the work nobody asks for and everybody notices.",
    "detail (dē′tāl) n. 1. A small part that decides whether the whole looks cheap or expensive. 2. Where the work lives.",
    "fall (fôl) v. 1. To descend freely. 2. To fly too close to something and keep going anyway.",
    "Icarus n. Son of Daedalus; flew on wings of feather and wax toward the sun. Remembered for how high he flew.",
    "obsession n. Love with a deadline.",
    "seraph n. The highest order of angels; six-winged, made of fire. Here, made of glyphs.",
    "ship v. To put the thing in front of people. The only step that counts.",
    "taste n. Knowing what to leave out.",
]


def creed(narrow=False):
    w, h = (600, 420) if narrow else (1200, 360)
    text = "   ".join(ENTRIES)
    text = re.sub(r"[^\x20-\x7e·—–’]", "", text)
    n = int((w - 40) / (10 * 0.6))
    tex, i, y = [], 0, 22
    while y < h:
        seg = (text * 4)[i:i + n]
        tex.append(f'<text x="20" y="{y}">{esc(seg)}</text>')
        i += n
        y += 15
    bg = f'<g class="m" font-size="10" fill="{UMBER}" opacity=".32">{"".join(tex)}</g>'
    veil = f'<rect width="{w}" height="{h}" fill="url(#v)"/>'
    defs = (f'<defs><radialGradient id="v" cx="50%" cy="50%" r="60%"><stop offset="0" stop-color="{INK}" stop-opacity=".92"/>'
            f'<stop offset="1" stop-color="{INK}" stop-opacity=".2"/></radialGradient></defs>')
    if narrow:
        fg = (
            f'<text class="s" x="{w / 2}" y="150" font-size="60" fill="{BONE}" text-anchor="middle">find what you <tspan class="i" fill="{GILT}">love</tspan></text>'
            f'<text class="s" x="{w / 2}" y="230" font-size="60" fill="{BONE}" text-anchor="middle">and let it <tspan class="i" fill="{GILT}">kill</tspan> you.</text>'
            f'<text class="m" x="{w / 2}" y="290" font-size="11" fill="{MUTED}" text-anchor="middle" letter-spacing="1">attributed to Charles Bukowski</text>'
        )
    else:
        fg = (
            f'<text class="s" x="{w / 2}" y="160" font-size="84" fill="{BONE}" text-anchor="middle">find what you <tspan class="i" fill="{GILT}">love</tspan></text>'
            f'<text class="s" x="{w / 2}" y="248" font-size="84" fill="{BONE}" text-anchor="middle">and let it <tspan class="i" fill="{GILT}">kill</tspan> you.</text>'
            f'<text class="m" x="{w / 2}" y="300" font-size="11" fill="{MUTED}" text-anchor="middle" letter-spacing="1">attributed to Charles Bukowski</text>'
        )
    return svg(w, h, defs + bg + veil + fg, title="Find what you love and let it kill you. Attributed to Charles Bukowski.")


if __name__ == "__main__":
    write("hero.svg", hero(1200, 620))
    write("hero-narrow.svg", hero(600, 820, narrow=True))
    write("fall.svg", fall())
    write("fall-narrow.svg", fall(narrow=True))
    write("creed.svg", creed())
    write("creed-narrow.svg", creed(narrow=True))
    for c in CHAPTERS:
        write(f"ch-{c[0]}.svg", plate(*c))
        write(f"ch-{c[0]}-narrow.svg", plate(*c, narrow=True))
