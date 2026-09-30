"""xwd 화면 덤프를 PNG 로. 틀(앱의 창)과 문(웹 뷰)과 아바타가 한 장에 담기려면 화면 전체를 찍어야 한다.

xwd -root -silent | python3 test/xwd2png.py out.png
"""
import struct
import sys

from PIL import Image

data = sys.stdin.buffer.read()
hdr = struct.unpack(">25I", data[:100])
header_size, _ver, _fmt, depth, width, height = hdr[0], hdr[1], hdr[2], hdr[3], hdr[4], hdr[5]
byte_order, bpp, bytes_per_line, ncolors = hdr[7], hdr[11], hdr[12], hdr[19]
off = header_size + ncolors * 12
px = data[off:off + bytes_per_line * height]
if bpp != 32:
    sys.exit(f"지원하지 않는 형식: {bpp}bpp")
mode = "BGRX" if byte_order == 0 else "XRGB"
img = Image.frombuffer("RGB", (width, height), px, "raw", mode, bytes_per_line, 1)
img.save(sys.argv[1])
