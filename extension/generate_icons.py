"""
generate_icons.py
─────────────────────────────────────────────────────────────────
Run this script once to generate the required PNG icon files:

    python generate_icons.py

Requires Pillow:
    pip install Pillow

Creates:
    icons/icon16.png
    icons/icon48.png
    icons/icon128.png
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont

os.makedirs("icons", exist_ok=True)

SIZES = [16, 48, 128]

# Dark Guard AI colour palette
BG_DARK   = (30,  41,  59)    # #1e293b
SHIELD    = (255, 255, 255)   # white
ACCENT    = (220, 38,  38)    # #dc2626 red
TEXT_CLR  = (255, 255, 255)


def draw_shield(draw, cx, cy, size, fill, outline=None):
    """Draw a simple shield shape centred at (cx, cy) with given height."""
    h = size
    w = h * 0.75

    # Shield is a rounded rectangle on top + pointed bottom
    points = [
        (cx - w/2,       cy - h/2),        # top-left
        (cx + w/2,       cy - h/2),        # top-right
        (cx + w/2,       cy + h * 0.1),    # mid-right
        (cx,             cy + h/2),        # bottom point
        (cx - w/2,       cy + h * 0.1),    # mid-left
    ]
    draw.polygon(points, fill=fill, outline=outline)


def create_icon(size):
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad    = size * 0.08
    radius = (size - pad * 2) * 0.45

    # Circular background
    draw.ellipse(
        [pad, pad, size - pad, size - pad],
        fill=BG_DARK,
    )

    cx = size / 2
    cy = size / 2

    # Shield
    shield_h = size * 0.55
    draw_shield(draw, cx, cy - size * 0.02, shield_h, SHIELD)

    # Red accent bar across middle of shield
    if size >= 48:
        bar_w = shield_h * 0.5
        bar_h = shield_h * 0.18
        draw.rectangle(
            [cx - bar_w/2, cy - bar_h/2 - size*0.02,
             cx + bar_w/2, cy + bar_h/2 - size*0.02],
            fill=ACCENT,
        )

    # "AI" text for larger icons
    if size >= 48:
        font_size = max(6, size // 8)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        text = "AI"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
        draw.text(
            (cx - tw/2, cy + shield_h * 0.28 - th/2 - size*0.02),
            text,
            fill=BG_DARK,
            font=font,
        )

    return img


for sz in SIZES:
    icon = create_icon(sz)
    path = f"icons/icon{sz}.png"
    icon.save(path, "PNG")
    print(f"Created {path} ({sz}x{sz})")

print("\nAll icons created successfully.")
print("You can now load the extension in Chrome:")
print("  1. Open chrome://extensions/")
print("  2. Enable Developer Mode")
print("  3. Click 'Load unpacked' and select this folder")
