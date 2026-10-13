"""
Generates icon.ico (multi-resolution) and icon.png (512px).

Design: WhatsApp dark-green rounded square, white speech bubble,
        bright-green sound-wave bars inside the bubble.
"""

from PIL import Image, ImageDraw
from pathlib import Path


# ── Palette ──────────────────────────────────────────────────────────────────
BG_COLOR     = (7,   94,  84,  255)   # #075E54  WhatsApp dark teal
BUBBLE_COLOR = (255, 255, 255, 255)   # white
WAVE_COLOR   = (37,  211, 102, 255)   # #25D366  WhatsApp bright green


def draw_icon(size: int) -> Image.Image:
    """
    Draw the icon at `size` × `size` px using 4× supersampling so all
    curves and rounded corners come out smooth after downscaling.
    """
    SCALE = 4 if size >= 32 else 2
    s = size * SCALE

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # ── Background rounded square ─────────────────────────────────────────
    pad  = int(s * 0.055)
    r_bg = int(s * 0.20)
    d.rounded_rectangle(
        [pad, pad, s - pad - 1, s - pad - 1],
        radius=r_bg,
        fill=BG_COLOR,
    )

    # ── Speech-bubble body ────────────────────────────────────────────────
    bx1 = int(s * 0.13)
    by1 = int(s * 0.13)
    bx2 = int(s * 0.87)
    by2 = int(s * 0.70)
    r_b = int(s * 0.095)
    d.rounded_rectangle([bx1, by1, bx2, by2], radius=r_b, fill=BUBBLE_COLOR)

    # ── Bubble tail (polygon, bottom-left) ───────────────────────────────
    t_left   = bx1 - int(s * 0.055)
    t_tip_y  = by2 + int(s * 0.155)
    t_top_y  = by2 - int(s * 0.01)
    t_right  = bx1 + int(s * 0.20)
    # The overlap with the bubble body hides any gap
    d.polygon(
        [(bx1 + int(s * 0.03), t_top_y),
         (t_left,              t_tip_y),
         (t_right,             t_top_y)],
        fill=BUBBLE_COLOR,
    )

    # ── Sound-wave bars ───────────────────────────────────────────────────
    HEIGHTS   = [0.33, 0.57, 0.80, 1.00, 0.80, 0.57, 0.33]
    N_BARS    = len(HEIGHTS)
    bub_w     = bx2 - bx1
    bub_h     = by2 - by1
    area_w    = bub_w * 0.60
    area_h    = bub_h * 0.50
    bar_w     = area_w / (N_BARS * 2 - 1)   # bars & gaps of equal width
    start_x   = bx1 + (bub_w - area_w) / 2
    center_y  = (by1 + by2) / 2 - bub_h * 0.03  # very slight upward nudge

    for i, h_ratio in enumerate(HEIGHTS):
        bh  = area_h * h_ratio
        x0  = start_x + i * bar_w * 2
        x1  = x0 + bar_w
        y0  = center_y - bh / 2
        y1  = center_y + bh / 2
        d.rounded_rectangle([x0, y0, x1, y1], radius=bar_w / 2, fill=WAVE_COLOR)

    # ── Downsample with Lanczos for smooth anti-aliasing ─────────────────
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    here = Path(__file__).parent

    # Multi-resolution ICO (Windows wants all of these)
    ico_sizes = [256, 128, 64, 48, 32, 24, 16]
    images = [draw_icon(s) for s in ico_sizes]

    ico_path = here / "icon.ico"
    # Pillow saves the first image as the primary frame and appends the rest
    images[0].save(
        ico_path,
        format="ICO",
        append_images=images[1:],
        sizes=[(s, s) for s in ico_sizes],
    )

    # High-res PNG (512 px) for documentation / other uses
    png_path = here / "icon.png"
    draw_icon(512).save(png_path, "PNG")

    print(f"OK  icon.ico  ->  {ico_path}")
    print(f"OK  icon.png  ->  {png_path}")


if __name__ == "__main__":
    main()
