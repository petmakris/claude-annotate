# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""draw_screen.py: draw the invented shop-app Orders screen that ca-07 explains.

    uv run tools/promo/fixtures/ca-07/draw_screen.py <out dir>

Writes <out dir>/orders.png: a 1440x900 admin page drawn at 2x (2880x1800), so
spotlight.json's boxes are in 2x pixels. Everything on it is made up: the
shop, the customers, the order numbers and the amounts. Same bytes every run.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2  # drawn at 2x; every coordinate below is in 1x points
FONTS = {
    "reg": ["/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "bold": ["/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
}
INK, DIM, LINE, BG, CARD = "#1b2330", "#5b6676", "#e3e7ee", "#f5f7fa", "#ffffff"
BLUE, RED, GREEN, AMBER = "#2f6fed", "#d6453d", "#1f8a4c", "#b7791f"


def font(kind, size):
    for p in FONTS[kind]:
        if Path(p).exists():
            return ImageFont.truetype(p, size * S)
    sys.exit("draw_screen.py: no Noto Sans, DejaVu Sans or Arial found")


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1440 * S, 900 * S), BG)
    d = ImageDraw.Draw(im)

    def box(x, y, w, h, fill=CARD, outline=LINE, r=10, width=1):
        d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], r * S, fill=fill,
                            outline=outline, width=width * S)

    def text(x, y, s, size=16, kind="reg", fill=INK, anchor="la"):
        d.text((x * S, y * S), s, font=font(kind, size), fill=fill, anchor=anchor)

    # sidebar
    d.rectangle([0, 0, 232 * S, 900 * S], fill="#16202e")
    box(24, 26, 34, 34, fill=BLUE, outline=BLUE, r=8)
    text(41, 43, "S", 20, "bold", "#fff", "mm")
    text(70, 31, "shop-app", 21, "bold", "#fff")
    for i, item in enumerate(["Overview", "Orders", "Products", "Customers", "Payouts", "Settings"]):
        y = 108 + i * 50
        if item == "Orders":
            box(14, y - 10, 204, 42, fill="#26354a", outline="#26354a", r=8)
        text(36, y, item, 18, "bold" if item == "Orders" else "reg",
             "#fff" if item == "Orders" else "#9fb0c6")

    # header
    text(272, 34, "Orders", 34, "bold")
    text(274, 84, "Today, 26 Nov · all channels", 17, fill=DIM)
    box(1060, 34, 340, 46, r=23)
    text(1086, 46, "Search orders", 17, fill="#98a2b1")

    # KPI cards
    kpis = [("Orders today", "1,284", "+6% on last Thursday", GREEN),
            ("Revenue", "€48,920", "+4% on last Thursday", GREEN),
            ("Failed payments", "37", "in the last hour", RED),
            ("Average basket", "€38.10", "flat", DIM)]
    for i, (k, v, sub, c) in enumerate(kpis):
        x = 272 + i * 286
        box(x, 128, 266, 132)
        text(x + 22, 148, k, 17, fill=DIM)
        text(x + 22, 178, v, 38, "bold", RED if k.startswith("Failed") else INK)
        text(x + 22, 228, sub, 15, fill=c)

    # alert with the retry button
    box(272, 284, 1130, 72, fill="#fdf0ef", outline="#f2c4c0")
    d.ellipse([294 * S, 308 * S, 318 * S, 332 * S], fill=RED)
    text(306, 320, "!", 17, "bold", "#fff", "mm")
    text(334, 297, "37 card payments failed: the card issuer timed out", 18, "bold")
    text(334, 324, "Customers were not charged. Their orders wait as Payment failed.", 16, fill=DIM)
    box(1166, 298, 218, 44, fill=RED, outline=RED, r=8)
    text(1275, 320, "Retry failed payments", 16, "bold", "#fff", "mm")

    # orders table
    box(272, 380, 1130, 486)
    cols = [(298, "Order"), (448, "Customer"), (720, "Items"), (840, "Total"), (990, "Payment"), (1170, "Status")]
    for x, c in cols:
        text(x, 402, c, 15, "bold", DIM)
    d.line([272 * S, 436 * S, 1402 * S, 436 * S], fill=LINE, width=S)
    rows = [("#10482", "Ana Ruiz", "3", "€64.00", "Card", "Paid"),
            ("#10481", "Ben Okafor", "1", "€19.90", "Card", "Payment failed"),
            ("#10480", "Chloe Martin", "2", "€42.50", "PayPal", "Shipped"),
            ("#10479", "Dev Mehta", "5", "€131.20", "Card", "Payment failed"),
            ("#10478", "Eva Novak", "1", "€24.00", "Invoice", "Paid"),
            ("#10477", "Finn Larsen", "2", "€58.80", "Card", "Shipped"),
            ("#10476", "Gia Romano", "4", "€97.40", "Card", "Paid")]
    pill = {"Paid": ("#e5f4ea", GREEN), "Shipped": ("#e7effd", BLUE),
            "Payment failed": ("#fbe7e5", RED)}
    for r, row in enumerate(rows):
        y = 456 + r * 58
        for (x, _), v in zip(cols, row):
            if v in pill:
                bg, fg = pill[v]
                w = font("bold", 15).getlength(v) / S + 28
                box(x, y - 6, w, 32, fill=bg, outline=bg, r=16)
                text(x + 14, y + 10, v, 15, "bold", fg, "lm")
            else:
                text(x, y, v, 17, "bold" if x == 298 else "reg", INK)
        if r < len(rows) - 1:
            d.line([292 * S, (y + 42) * S, 1382 * S, (y + 42) * S], fill="#eef1f5", width=S)
    im.save(out / "orders.png", optimize=True)
    return out / "orders.png"


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "."))
