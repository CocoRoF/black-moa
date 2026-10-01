"""black-moa 글자 그림을 만든다 (plan/82).

표식(M)과 아이콘은 Memora 때의 원본 그림을 그대로 쓰고, 글자가 들어간 그림만 여기서 다시 짠다.
글자는 원본 글자와 가장 닮은 둥근 서체 Fredoka(700, OFL)로 쓰고, "o" 자리에는 원본 글자 그림의
그라데이션 o 를 떼어 끼운다 — 브랜드에서 유일하게 색이 있는 글자라 서체로 흉내 내지 않는다.

    python tools/brand_wordmark.py            # frontend/public/brand, images 를 덮어쓴다

만드는 것: wordmark-trim(-dark), logo-lockup(-dark), logo-full(@2x)(-trim)(-dark), og-default,
images/black-moa-{text-,}for-{light,dark}.png. 바꾼 뒤에는 frontend/lib/brand.ts 의 BRAND_REV 를 올린다.
"""
from __future__ import annotations

import colorsys
import pathlib
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRAND = ROOT / "frontend/public/brand"
IMAGES = ROOT / "images"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/fredoka/Fredoka%5Bwdth,wght%5D.ttf"
FONT = pathlib.Path.home() / ".cache/black-moa/Fredoka.ttf"

TEXT = ("black-m", "o", "a")          # 가운데가 그라데이션 o
INK_LIGHT = (6, 21, 54)               # 원본 글자의 잉크(밝은 바탕)
INK_DARK = (242, 246, 253)            # 어두운 바탕
SIZE = 900                            # 그릴 때의 글자 크기 — 줄일 때 계단이 생기지 않게 크게
O_SCALE = 1.04                        # 원본에서 o 는 다른 소문자보다 조금 크다


def font() -> ImageFont.FreeTypeFont:
    if not FONT.exists():
        FONT.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(FONT_URL, headers={"User-Agent": "Mozilla/5.0"})
        FONT.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    f = ImageFont.truetype(str(FONT), SIZE)
    f.set_variation_by_axes([700, 100])
    return f


O_SOURCE = IMAGES / "brand-o.png"   # 원본 글자 그림에서 떼어 둔 o — 이것이 정본이다


def gradient_o() -> Image.Image:
    return Image.open(O_SOURCE).convert("RGBA")


def extract_o(path: pathlib.Path) -> Image.Image:
    """원본 글자 그림(Memora 때의 text-for-light)에서 그라데이션 o 만 떼어 낸다(가운데 구멍은 원래 투명).
    한 번 떼어 O_SOURCE 로 저장해 두었다 — 만든 그림에서 다시 떼면 줄일 때마다 흐려진다."""
    src = Image.open(path).convert("RGBA")
    px = src.load()
    xs, ys = [], []
    for y in range(src.height):
        for x in range(src.width):
            r, g, b, a = px[x, y]
            if a > 40:
                _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                if s > 0.45 and v > 0.35:
                    xs.append(x); ys.append(y)
    box = (min(xs) - 3, min(ys) - 3, max(xs) + 4, max(ys) + 4)
    o = src.crop(box)
    q = o.load()
    # 이웃 글자(m·r)의 잉크가 사각형 안에 걸치면 지운다.
    for y in range(o.height):
        for x in range(o.width):
            r, g, b, a = q[x, y]
            if a and abs(r - INK_LIGHT[0]) + abs(g - INK_LIGHT[1]) + abs(b - INK_LIGHT[2]) < 70:
                q[x, y] = (0, 0, 0, 0)
    return o.crop(o.getbbox())


def wordmark(ink: tuple[int, int, int], o_img: Image.Image) -> Image.Image:
    f = font()
    left, mid, right = TEXT
    w = int(f.getlength("".join(TEXT)) + SIZE)
    canvas = Image.new("RGBA", (w, int(SIZE * 1.6)), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    x0, base = SIZE // 4, int(SIZE * 1.15)
    d.text((x0, base), left, font=f, fill=ink + (255,), anchor="ls")
    # 그라데이션 o 는 서체의 o 보다 넓다. 서체의 o 키에 맞춰 줄이고, 양옆 여백(side bearing)은 서체의 것을
    # 그대로 두어 o 의 실제 폭만큼 자리를 낸다 — 같은 중심에 얹으면 m·a 에 닿는다.
    gx0, gy0, gx1, gy1 = f.getbbox(mid, anchor="ls")
    gh = (gy1 - gy0) * O_SCALE
    scaled = o_img.resize((round(o_img.width * gh / o_img.height), round(gh)), Image.LANCZOS)
    o_left = x0 + f.getlength(left) + gx0
    cy = base + (gy0 + gy1) / 2
    canvas.alpha_composite(scaled, (round(o_left), round(cy - scaled.height / 2)))
    a_x = o_left + scaled.width + (f.getlength(mid) - gx1)
    d.text((a_x, base), right, font=f, fill=ink + (255,), anchor="ls")
    return canvas.crop(canvas.getbbox())


def fit_h(im: Image.Image, h: int) -> Image.Image:
    return im.resize((round(im.width * h / im.height), h), Image.LANCZOS)


def lockup(mark: Image.Image, word: Image.Image, h: int, pad: float = 0.0) -> Image.Image:
    """표식 + 글자 한 줄. 글자 키는 표식의 42%, 사이는 표식 키의 16% — Memora 때 비율."""
    m = fit_h(mark, h)
    wd = fit_h(word, round(h * 0.42))
    gap = round(h * 0.16)
    p = round(h * pad)
    out = Image.new("RGBA", (p + m.width + gap + wd.width + p, h + 2 * p), (0, 0, 0, 0))
    out.alpha_composite(m, (p, p))
    out.alpha_composite(wd, (p + m.width + gap, p + round((h - wd.height) / 2)))
    return out


def main() -> None:
    o = gradient_o()
    mark = Image.open(BRAND / "logo-mark.png").convert("RGBA")
    mark = mark.crop(mark.getbbox())
    words = {"": wordmark(INK_LIGHT, o), "-dark": wordmark(INK_DARK, o)}
    for suffix, word in words.items():
        fit_h(word, 165).save(BRAND / f"wordmark-trim{suffix}.png", optimize=True)
        lockup(mark, word, 224).save(BRAND / f"logo-lockup{suffix}.png", optimize=True)
        lockup(mark, word, 196).save(BRAND / f"logo-full-trim{suffix}.png", optimize=True)
        lockup(mark, word, 140).save(BRAND / f"logo-full{suffix}.png", optimize=True)
        lockup(mark, word, 280).save(BRAND / f"logo-full@2x{suffix}.png", optimize=True)
        tone = "light" if not suffix else "dark"
        lockup(mark, word, 480, pad=0.25).save(IMAGES / f"black-moa-for-{tone}.png", optimize=True)
        fit_h(word, 308).save(IMAGES / f"black-moa-text-for-{tone}.png", optimize=True)
    og = Image.new("RGBA", (1200, 630), (255, 255, 255, 255))
    lk = lockup(mark, words[""], 190)
    if lk.width > 980:
        lk = lk.resize((980, round(lk.height * 980 / lk.width)), Image.LANCZOS)
    og.alpha_composite(lk, ((1200 - lk.width) // 2, (630 - lk.height) // 2))
    og.convert("RGB").save(BRAND / "og-default.png", optimize=True)


if __name__ == "__main__":
    main()
