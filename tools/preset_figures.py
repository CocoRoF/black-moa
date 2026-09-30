#!/usr/bin/env python3
"""고른 얼굴(프리셋)마다 세울 전신 그림을 원본에서 만든다 — 무대와 PC 앱의 아바타가 쓴다.

원본(`images/*_portrait/*.png`, 바탕이 이미 투명한 PNG)을 **PNG 그대로, 투명한 채로** 줄인다. 형식을 바꾸지
않는다(JPEG·WebP 로 바꾸면 가장자리가 번지거나 투명이 깨진다). 하는 일은 셋뿐이다.

1. 투명한 가장자리만 잘라 낸다(사람 둘레 8px 는 남긴다). 보이는 그림은 한 점도 바뀌지 않는다.
2. 긴 변을 1280 으로 줄인다. 무대에서 가장 크게 서는 것이 1080p 화면에서 세로 1100px 남짓이라 거의 1:1 이다.
   Pillow 의 LANCZOS 는 RGBA 를 알파를 곱한 채로 줄여서 머리카락 가장자리에 검거나 흰 테가 생기지 않는다.
3. PNG 를 최대로 압축한다(무손실). 한 장이 3MB 를 넘으면 긴 변을 더 줄인다.

Run:  python tools/preset_figures.py        # frontend/public/presets/<이름>-full.png 를 다시 만든다
      python tools/preset_figures.py --check  # 만들어 둔 것이 지금 규칙과 맞는지만 본다
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "presets"

#: 원본 → 프리셋 이름(얼굴 `<이름>.png` 와 같은 이름에 `-full`). 백엔드 `PRESET_FIGURES` 와 같은 목록이다.
SOURCES = {
    "male_portrait/male-01-navy-suit.png": "secretary-male",
    "male_portrait/male-02-pinstripe.png": "secretary-male-pinstripe",
    "male_portrait/male-03-navy-double.png": "secretary-male-double",
    "male_portrait/male-04-grey-knit.png": "secretary-male-grey",
    "male_portrait/male-05-burgundy-tie.png": "secretary-male-burgundy",
    "female_portrait/female-01-long-wave.png": "secretary-female",
    "female_portrait/female-02-beige-bob.png": "secretary-female-bob",
    "female_portrait/female-03-charcoal-long.png": "secretary-female-dark",
    "female_portrait/female-04-green-ponytail.png": "secretary-female-ponytail",
    "female_portrait/female-05-ivory-pixie.png": "secretary-female-pixie",
    "female_portrait/female-06-dot-cardigan.png": "secretary-female-dot-cardigan",
    "female_portrait/female-07-dot-auburn.png": "secretary-female-dot-auburn",
    "female_portrait/female-08-dot-shirt.png": "secretary-female-dot-shirt",
    "female_portrait/female-09-dot-green.png": "secretary-female-dot-green",
    "female_portrait/female-10-dot-navy.png": "secretary-female-dot-navy",
}
LONG_EDGE = 1280
MAX_BYTES = 3 * 1024 * 1024
PAD = 8


def figure(src: Path) -> bytes:
    im = Image.open(src).convert("RGBA")
    bb = im.getchannel("A").getbbox()
    if bb:
        im = im.crop((max(0, bb[0] - PAD), max(0, bb[1] - PAD), min(im.width, bb[2] + PAD), min(im.height, bb[3] + PAD)))
    edge = LONG_EDGE
    while True:
        k = min(1.0, edge / max(im.size))
        out = im if k >= 1 else im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True, compress_level=9)
        if buf.tell() <= MAX_BYTES or edge <= 640:
            return buf.getvalue()
        edge = int(edge * 0.85)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    bad = 0
    total = 0
    for rel, name in SOURCES.items():
        dst = OUT / f"{name}-full.png"
        if args.check:
            im = Image.open(dst)
            ok = im.format == "PNG" and im.mode == "RGBA" and max(im.size) <= LONG_EDGE and dst.stat().st_size <= MAX_BYTES
            bad += not ok
            print(("  ok " if ok else "!! ") + f"{dst.name} {im.size} {dst.stat().st_size}")
            continue
        data = figure(ROOT / "images" / rel)
        dst.write_bytes(data)
        total += len(data)
        print(f"{dst.name} {Image.open(io.BytesIO(data)).size} {len(data)}")
    if not args.check:
        print(f"total {total}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
