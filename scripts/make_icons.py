#!/usr/bin/env python3
"""Génère PNG pure stdlib (zlib+struct) - flèche bas dans carré arrondi"""
import struct
import zlib
from pathlib import Path

def crc(data): return zlib.crc32(data) & 0xffffffff

def chunk(type_, data):
    return struct.pack(">I", len(data)) + type_ + data + struct.pack(">I", crc(type_ + data))

def png_bytes(w, h, rgba_rows):
    # rgba_rows: list of bytes per row (w*4)
    raw = b""
    for row in rgba_rows:
        raw += b"\x00" + row  # filter 0
    comp = zlib.compress(raw, 9)
    # IHDR
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")

def gen_icon(size, out_path):
    # colors: background dark #151922, accent #4f8cff
    bg = (21, 25, 34, 255)
    accent = (79, 140, 255, 255)
    white = (255,255,255,255)
    # Create grid
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            # rounded rect bg: inset 2px, radius ~ size*0.2
            radius = int(size * 0.2)
            # Determine if inside rounded rect (size-4 margin)
            left, top = 2, 2
            right, bottom = size-3, size-3
            # simple rounded rect check
            in_rect = False
            if left <= x <= right and top <= y <= bottom:
                # corners
                # distances to corners
                in_rect = True
                # top-left corner
                if x < left+radius and y < top+radius:
                    dx = x - (left+radius)
                    dy = y - (top+radius)
                    if dx*dx + dy*dy > radius*radius:
                        in_rect = False
                elif x > right-radius and y < top+radius:
                    dx = x - (right-radius)
                    dy = y - (top+radius)
                    if dx*dx+dy*dy > radius*radius:
                        in_rect=False
                elif x < left+radius and y > bottom-radius:
                    dx = x - (left+radius)
                    dy = y - (bottom-radius)
                    if dx*dx+dy*dy > radius*radius:
                        in_rect=False
                elif x > right-radius and y > bottom-radius:
                    dx = x - (right-radius)
                    dy = y - (bottom-radius)
                    if dx*dx+dy*dy>radius*radius:
                        in_rect=False
            if not in_rect:
                # transparent
                row += bytes([0,0,0,0])
                continue
            # Inside bg
            # Draw arrow: vertical bar + triangle down
            # Arrow area: center x = size//2, y 0.3*size to 0.75*size
            cx = size//2
            # bar width ~ size*0.18
            bar_w = max(2, int(size*0.18))
            bar_top = int(size*0.28)
            bar_bottom = int(size*0.62)
            tri_top = bar_bottom
            tri_bottom = int(size*0.78)
            tri_half = int(size*0.22)
            is_arrow = False
            if bar_top <= y <= bar_bottom and abs(x-cx) <= bar_w//2:
                is_arrow = True
            elif tri_top <= y <= tri_bottom:
                # triangle width shrinks linearly
                prog = (y - tri_top) / max(1, tri_bottom - tri_top)  # 0->1
                half = tri_half * (1 - prog)
                if abs(x-cx) <= half:
                    is_arrow = True
            if is_arrow:
                row += bytes(white)
            else:
                # bg with accent border? Use bg
                # blend accent at border
                if x==left or x==right or y==top or y==bottom:
                    row += bytes(accent)
                else:
                    row += bytes(bg)
        rows.append(bytes(row))
    data = png_bytes(size, size, rows)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(data)
    print(f"Generated {out_path} {size}x{size}")

if __name__ == "__main__":
    base = Path(__file__).parent.parent / "extension" / "icons"
    for s in [16,32,48,128]:
        gen_icon(s, base / f"icon{s}.png")
