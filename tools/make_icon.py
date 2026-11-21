"""Generates assets/icon.ico (all Windows sizes) and assets/icon.png.

Red rounded square with a white "download" arrow. Run: python tools/make_icon.py
(needs Pillow; only for regenerating the icon, not for running or building the app).
"""
from pathlib import Path

from PIL import Image, ImageDraw

RED = (211, 47, 47, 255)
WHITE = (255, 255, 255, 255)
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BIG = 1024


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size  # coordinates below are fractions of the icon size
    m = 0.04 * u
    d.rounded_rectangle([m, m, u - m, u - m], radius=0.22 * u, fill=RED)
    d.rectangle([0.40 * u, 0.15 * u, 0.60 * u, 0.50 * u], fill=WHITE)                     # shaft
    d.polygon([(0.19 * u, 0.45 * u), (0.81 * u, 0.45 * u), (0.50 * u, 0.76 * u)], fill=WHITE)  # head
    d.rounded_rectangle([0.20 * u, 0.81 * u, 0.80 * u, 0.90 * u], radius=0.03 * u, fill=WHITE)  # tray
    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "assets"
    out.mkdir(exist_ok=True)
    big = draw(BIG)
    big.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
    # Downscale from the big drawing for each size so edges stay smooth
    frames = [big.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(out / "icon.ico", format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print("wrote", out / "icon.ico", "and", out / "icon.png")


if __name__ == "__main__":
    main()
