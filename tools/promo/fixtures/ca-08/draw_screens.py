# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""draw_screens.py: draw the 20 invented shop-app screens that ca-08 lays on a canvas.

    uv run tools/promo/fixtures/ca-08/draw_screens.py <out dir>

Ten screens of a made-up web shop (sign in, browse, cart, checkout), each as a
1600x1000 desktop shot and a 390x844 phone shot drawn at 2x. File names match
canvas.json. Everything is invented: the shop, the products, the prices, the
address and the card. Same bytes every run.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = {
    "reg": ["/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "bold": ["/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
}
INK, DIM, LINE, BG, CARD = "#1d2433", "#667085", "#e4e7ec", "#f7f7f5", "#ffffff"
BRAND, GREEN, RED, AMBER = "#0f766e", "#15803d", "#c2410c", "#fef3c7"
PRODUCTS = [  # name, price, swatch, shape
    ("Trail Runner 2", "€119.00", "#fde2c8", "shoe", "#ea580c"),
    ("Canvas Tote", "€34.00", "#dbeafe", "tote", "#1d4ed8"),
    ("Merino Beanie", "€29.00", "#ede9fe", "beanie", "#7c3aed"),
    ("Steel Bottle 750", "€24.00", "#dcfce7", "bottle", "#15803d"),
    ("Rain Shell", "€149.00", "#fee2e2", "jacket", "#b91c1c"),
    ("Wool Socks", "€14.00", "#fef9c3", "socks", "#a16207"),
]
_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _cache:
        path = next((p for p in FONTS[kind] if Path(p).exists()), None)
        if not path:
            sys.exit("draw_screens.py: no Noto Sans, DejaVu Sans or Arial found")
        _cache[key] = ImageFont.truetype(path, size)
    return _cache[key]


class Canvas:
    """A screen of w x h points drawn at `s` pixels a point."""

    def __init__(self, w, h, s):
        self.w, self.h, self.s = w, h, s
        self.im = Image.new("RGB", (w * s, h * s), BG)
        self.d = ImageDraw.Draw(self.im)

    def p(self, *v):
        return [round(x * self.s) for x in v]

    def rect(self, x, y, w, h, fill=CARD, outline=LINE, r=8, width=1):
        self.d.rounded_rectangle(self.p(x, y, x + w, y + h), round(r * self.s), fill=fill,
                                 outline=outline, width=max(1, round(width * self.s)) if outline else 0)

    def text(self, x, y, t, size=15, kind="reg", fill=INK, anchor="la"):
        self.d.text(self.p(x, y), t, font=font(kind, round(size * self.s)), fill=fill, anchor=anchor)

    def width_of(self, t, size, kind="reg"):
        return font(kind, round(size * self.s)).getlength(t) / self.s

    def button(self, x, y, w, h, label, fill=BRAND, fg="#fff", size=15):
        self.rect(x, y, w, h, fill=fill, outline=fill if fill != CARD else LINE, r=8)
        self.text(x + w / 2, y + h / 2, label, size, "bold", fg, "mm")

    def field(self, x, y, w, label, value, h=44, size=15, hint=False):
        self.text(x, y, label, size - 2, "bold", DIM)
        self.rect(x, y + 22, w, h, r=7)
        self.text(x + 14, y + 22 + h / 2, value, size, "reg", "#98a2b3" if hint else INK, "lm")
        return y + 22 + h + 18

    def product(self, x, y, w, h, prod):
        _, _, swatch, shape, ink = prod
        self.rect(x, y, w, h, fill=swatch, outline=swatch, r=10)
        cx, cy, u = x + w / 2, y + h / 2, min(w, h) / 10
        d, p = self.d, self.p
        if shape == "shoe":
            d.rounded_rectangle(p(cx - 3.5 * u, cy - 0.5 * u, cx + 3.5 * u, cy + 1.6 * u), round(u * self.s), fill=ink)
            d.rounded_rectangle(p(cx - 3.5 * u, cy - 2 * u, cx + 0.5 * u, cy + 0.5 * u), round(u * self.s), fill=ink)
            d.rectangle(p(cx - 3.5 * u, cy + 1.6 * u, cx + 3.5 * u, cy + 2.1 * u), fill="#fff")
        elif shape == "tote":
            d.arc(p(cx - 1.5 * u, cy - 3.6 * u, cx + 1.5 * u, cy - 0.4 * u), 180, 360, fill=ink, width=round(0.4 * u * self.s))
            d.rounded_rectangle(p(cx - 2.6 * u, cy - 2 * u, cx + 2.6 * u, cy + 2.8 * u), round(0.4 * u * self.s), fill=ink)
        elif shape == "beanie":
            d.pieslice(p(cx - 2.8 * u, cy - 3 * u, cx + 2.8 * u, cy + 2.6 * u), 180, 360, fill=ink)
            d.rounded_rectangle(p(cx - 3 * u, cy - 0.3 * u, cx + 3 * u, cy + 1.3 * u), round(0.3 * u * self.s), fill=ink)
            d.ellipse(p(cx - 0.6 * u, cy - 3.7 * u, cx + 0.6 * u, cy - 2.5 * u), fill=ink)
        elif shape == "bottle":
            d.rounded_rectangle(p(cx - 1.2 * u, cy - 2.6 * u, cx + 1.2 * u, cy + 3.2 * u), round(0.6 * u * self.s), fill=ink)
            d.rectangle(p(cx - 0.6 * u, cy - 3.4 * u, cx + 0.6 * u, cy - 2.4 * u), fill=ink)
        elif shape == "jacket":
            d.polygon([tuple(p(cx - 1 * u, cy - 3 * u)), tuple(p(cx + 1 * u, cy - 3 * u)),
                       tuple(p(cx + 3.2 * u, cy - 1.6 * u)), tuple(p(cx + 2.4 * u, cy + 3 * u)),
                       tuple(p(cx - 2.4 * u, cy + 3 * u)), tuple(p(cx - 3.2 * u, cy - 1.6 * u))], fill=ink)
            d.line(p(cx, cy - 2.6 * u, cx, cy + 3 * u), fill="#fff", width=max(1, round(0.15 * u * self.s)))
        else:
            for k in (-1.4, 1.4):
                d.rounded_rectangle(p(cx + k * u - 0.9 * u, cy - 3 * u, cx + k * u + 0.9 * u, cy + 1.5 * u), round(0.4 * u * self.s), fill=ink)
                d.rounded_rectangle(p(cx + k * u - 0.9 * u, cy + 0.6 * u, cx + k * u + 2 * u, cy + 2.6 * u), round(0.8 * u * self.s), fill=ink)


def header(c, phone, cart=0):
    c.d.rectangle(c.p(0, 0, c.w, 64 if not phone else 56), fill=CARD)
    c.d.line(c.p(0, 64 if not phone else 56, c.w, 64 if not phone else 56), fill=LINE, width=c.s)
    y = 32 if not phone else 28
    c.rect(20 if phone else 40, y - 15, 30, 30, fill=BRAND, outline=BRAND, r=8)
    c.text((35 if phone else 55), y, "N", 17, "bold", "#fff", "mm")
    c.text((60 if phone else 82), y, "Northwind Goods", 18 if not phone else 16, "bold", INK, "lm")
    if not phone:
        for i, t in enumerate(["Shoes", "Bags", "Outerwear", "Accessories", "Sale"]):
            c.text(420 + i * 120, y, t, 15, "reg", RED if t == "Sale" else DIM, "lm")
        c.rect(1080, y - 18, 300, 36, r=18)
        c.text(1100, y, "Search the shop", 14, "reg", "#98a2b3", "lm")
        c.text(1420, y, "Account", 15, "reg", DIM, "lm")
    cx = c.w - (40 if phone else 70)
    c.rect(cx - 16, y - 13, 32, 26, fill=CARD, outline=INK, r=6, width=1.5)
    c.d.arc(c.p(cx - 7, y - 21, cx + 7, y - 7), 180, 360, fill=INK, width=max(1, round(1.5 * c.s)))
    if cart:
        c.d.ellipse(c.p(cx + 8, y - 22, cx + 26, y - 4), fill=RED)
        c.text(cx + 17, y - 13, str(cart), 11, "bold", "#fff", "mm")
    return (64 if not phone else 56) + 28


def col(c, phone):
    """(left, width) of the main column."""
    return (20, c.w - 40) if phone else (160, c.w - 320)


def sign_in(c, phone, reset=False):
    top = header(c, phone)
    w = c.w - 40 if phone else 420
    x = (c.w - w) / 2
    y = top + (24 if phone else 80)
    if not phone:
        c.rect(x - 40, y - 40, w + 80, 470 if not reset else 380, r=14)
    c.text(x, y, "Reset your password" if reset else "Sign in", 26, "bold")
    y += 44
    c.text(x, y, "We will email you a link." if reset else "Welcome back to Northwind Goods.", 15, "reg", DIM)
    y += 40
    y = c.field(x, y, w, "Email", "dana@example.com")
    if not reset:
        y = c.field(x, y, w, "Password", "••••••••••")
        c.text(x + w, y - 6, "Forgot password?", 13, "bold", BRAND, "ra")
        y += 22
    c.button(x, y, w, 48, "Send the link" if reset else "Sign in")
    y += 70
    c.text(x + w / 2, y, "Back to sign in" if reset else "New here? Create an account", 14, "reg", DIM, "ma")


def home(c, phone):
    top = header(c, phone, cart=2)
    x, w = col(c, phone)
    hh = 220 if phone else 340
    c.rect(x, top, w, hh, fill="#134e4a", outline="#134e4a", r=16)
    c.text(x + 28, top + 40, "Winter trail kit", 30 if not phone else 24, "bold", "#fff")
    c.text(x + 28, top + 90, "Warm layers for wet weekends.", 17 if not phone else 15, "reg", "#ccfbf1")
    c.button(x + 28, top + hh - 80, 170, 46, "Shop the edit", fill="#fff", fg="#134e4a")
    if not phone:
        c.product(x + w - 420, top + 30, 380, hh - 60, PRODUCTS[4])
    y = top + hh + 34
    c.text(x, y, "Popular this week", 21, "bold")
    y += 44
    n = 2 if phone else 4
    gw = (w - (n - 1) * 20) / n
    for i in range(n):
        gx = x + i * (gw + 20)
        c.product(gx, y, gw, gw * 0.75, PRODUCTS[i])
        c.text(gx, y + gw * 0.75 + 14, PRODUCTS[i][0], 15, "bold")
        c.text(gx, y + gw * 0.75 + 38, PRODUCTS[i][1], 15, "reg", DIM)


def category(c, phone):
    top = header(c, phone, cart=2)
    x, w = col(c, phone)
    c.text(x, top, "Home  /  Shoes", 13, "reg", DIM)
    c.text(x, top + 26, "Shoes", 28, "bold")
    c.text(x + w, top + 36, "48 products   Sort: Popular", 14, "reg", DIM, "ra")
    y = top + 84
    chips = ["All", "Trail", "Road", "Walking", "Kids"]
    cx = x
    for i, t in enumerate(chips[:4] if phone else chips):
        tw = c.width_of(t, 14, "bold") + 30
        c.rect(cx, y, tw, 32, fill=INK if i == 0 else CARD, outline=INK if i == 0 else LINE, r=16)
        c.text(cx + tw / 2, y + 16, t, 14, "bold", "#fff" if i == 0 else INK, "mm")
        cx += tw + 10
    y += 56
    n = 2 if phone else 4
    gw = (w - (n - 1) * 20) / n
    shoes = [("Trail Runner 2", "€119.00"), ("Ridge Mid GTX", "€165.00"), ("City Walker", "€89.00"),
             ("Trail Runner 2 Kids", "€69.00"), ("Fell Racer", "€135.00"), ("Harbour Slip-on", "€59.00"),
             ("Ridge Low", "€139.00"), ("Pace Road 4", "€109.00")]
    for i, (name, price) in enumerate(shoes[: (4 if phone else 8)]):
        gx = x + (i % n) * (gw + 20)
        gy = y + (i // n) * (gw * 0.7 + 86)
        tint = ["#fde2c8", "#e0f2fe", "#f1f5f9", "#fce7f3"][i % 4]
        c.product(gx, gy, gw, gw * 0.7, (name, price, tint, "shoe", ["#ea580c", "#0369a1", "#334155", "#be185d"][i % 4]))
        c.text(gx, gy + gw * 0.7 + 12, name, 15, "bold")
        c.text(gx, gy + gw * 0.7 + 36, price, 15, "reg", DIM)


def product(c, phone):
    top = header(c, phone, cart=2)
    x, w = col(c, phone)
    if phone:
        c.product(x, top, w, 300, PRODUCTS[0])
        y = top + 324
        ix = x
    else:
        c.product(x, top, 640, 560, PRODUCTS[0])
        y = top + 10
        ix = x + 700
    c.text(ix, y, "Trail Runner 2", 30 if not phone else 24, "bold")
    c.text(ix, y + 48, "€119.00", 22, "bold", BRAND)
    c.text(ix, y + 86, "Rated 4.6 out of 5 · 212 reviews", 14, "reg", DIM)
    y += 128
    c.text(ix, y, "Size (EU)", 14, "bold", DIM)
    y += 28
    for i, sz in enumerate(["39", "40", "41", "42", "43", "44"]):
        bx = ix + i * (52 if phone else 62)
        c.rect(bx, y, 44 if phone else 52, 44, fill=INK if sz == "42" else CARD, outline=INK if sz == "42" else LINE, r=8)
        c.text(bx + (22 if phone else 26), y + 22, sz, 15, "bold", "#fff" if sz == "42" else INK, "mm")
    y += 70
    bw = w if phone else 400
    c.button(ix, y, bw, 52, "Add to cart", size=16)
    y += 76
    for line in ["Grippy lugs for mud and wet rock.", "Free returns within 30 days.", "Ships in 1 to 2 working days."]:
        c.text(ix, y, "·  " + line, 15, "reg", DIM)
        y += 28


def cart(c, phone, promo=True, saved=False):
    top = header(c, phone, cart=0 if saved else 2)
    x, w = col(c, phone)
    c.text(x, top, "Saved for later" if saved else "Your cart", 28, "bold")
    y = top + 56
    lw = w if phone else w - 400
    items = [PRODUCTS[0], PRODUCTS[2]] if not saved else [PRODUCTS[4], PRODUCTS[5], PRODUCTS[3]]
    for prod in items:
        c.rect(x, y, lw, 112, r=12)
        c.product(x + 14, y + 14, 84, 84, prod)
        c.text(x + 116, y + 22, prod[0], 16, "bold")
        c.text(x + 116, y + 50, "Size 42 · Qty 1" if prod[3] == "shoe" else "One size · Qty 1", 14, "reg", DIM)
        c.text(x + lw - 18, y + 22, prod[1], 16, "bold", INK, "ra")
        c.text(x + lw - 18, y + 76, "Move to cart" if saved else "Remove", 13, "bold", BRAND if saved else DIM, "ra")
        y += 128
    if saved:
        return
    sx, sy = (x, y + 6) if phone else (x + w - 370, top + 56)
    sw = w if phone else 370
    c.rect(sx, sy, sw, 300 if promo else 230, r=12)
    yy = sy + 22
    for k, v in [("Subtotal", "€148.00"), ("Shipping", "Free")]:
        c.text(sx + 20, yy, k, 15, "reg", DIM)
        c.text(sx + sw - 20, yy, v, 15, "reg", INK, "ra")
        yy += 32
    if promo:
        c.rect(sx + 20, yy, sw - 130, 40, r=7)
        c.text(sx + 34, yy + 20, "Promo code", 14, "reg", "#98a2b3", "lm")
        c.button(sx + sw - 100, yy, 80, 40, "Apply", fill=CARD, fg=INK, size=14)
        yy += 58
    c.d.line(c.p(sx + 20, yy, sx + sw - 20, yy), fill=LINE, width=c.s)
    yy += 16
    c.text(sx + 20, yy, "Total", 17, "bold")
    c.text(sx + sw - 20, yy, "€148.00", 17, "bold", INK, "ra")
    c.button(sx + 20, yy + 44, sw - 40, 50, "Go to checkout", size=16)


def steps(c, x, y, w, active):
    names = ["Address", "Payment", "Review"]
    sw = w / 3
    for i, n in enumerate(names):
        on = i <= active
        c.d.rectangle(c.p(x + i * sw + 2, y, x + (i + 1) * sw - 2, y + 4), fill=BRAND if on else LINE)
        c.text(x + i * sw + 2, y + 14, f"{i + 1}  {n}", 13, "bold", BRAND if on else DIM)
    return y + 52


def address(c, phone):
    top = header(c, phone, cart=2)
    x, w = col(c, phone)
    fw = w if phone else 620
    y = steps(c, x, top, fw, 0)
    c.text(x, y, "Where should we send it?", 24, "bold")
    y += 50
    y = c.field(x, y, fw, "Full name", "Dana Example")
    y = c.field(x, y, fw, "Street and number", "12 Harbour Lane")
    if phone:
        y = c.field(x, y, fw, "Postcode", "1011 AB")
        y = c.field(x, y, fw, "City", "Port Example")
    else:
        c.field(x, y, 200, "Postcode", "1011 AB")
        y = c.field(x + 220, y, fw - 220, "City", "Port Example")
    c.button(x, y + 6, fw if phone else 260, 50, "Continue to payment", size=16)
    if not phone:
        summary(c, x + w - 370, top + 52)


def summary(c, sx, sy, sw=370):
    c.rect(sx, sy, sw, 230, r=12)
    c.text(sx + 20, sy + 20, "Order summary", 16, "bold")
    yy = sy + 60
    for prod in (PRODUCTS[0], PRODUCTS[2]):
        c.product(sx + 20, yy, 48, 48, prod)
        c.text(sx + 82, yy + 12, prod[0], 14, "reg")
        c.text(sx + sw - 20, yy + 12, prod[1], 14, "reg", INK, "ra")
        yy += 64
    c.text(sx + 20, yy + 10, "Total", 16, "bold")
    c.text(sx + sw - 20, yy + 10, "€148.00", 16, "bold", INK, "ra")


def payment(c, phone):
    top = header(c, phone, cart=2)
    x, w = col(c, phone)
    fw = w if phone else 620
    y = steps(c, x, top, fw, 1)
    c.text(x, y, "How would you like to pay?", 24, "bold")
    y += 50
    c.rect(x, y, fw, 64 if not phone else 84, fill=AMBER, outline="#fcd34d", r=10)
    c.text(x + 16, y + 14, "Your bank did not answer last time.", 15, "bold")
    c.text(x + 16, y + 38, "Nothing was charged. Try the card again" + (" or pick" if not phone else ""), 14, "reg", DIM)
    if phone:
        c.text(x + 16, y + 58, "or pick another way to pay.", 14, "reg", DIM)
    else:
        c.text(x + 16 + c.width_of("Nothing was charged. Try the card again or pick", 14) + 4, y + 38, "another way to pay.", 14, "reg", DIM)
    y += (64 if not phone else 84) + 24
    for i, t in enumerate(["Card", "PayPal", "Invoice"]):
        bw = (fw - 20) / 3
        c.rect(x + i * (bw + 10), y, bw, 44, fill="#ecfdf5" if i == 0 else CARD, outline=BRAND if i == 0 else LINE, r=8, width=2 if i == 0 else 1)
        c.text(x + i * (bw + 10) + bw / 2, y + 22, t, 15, "bold", BRAND if i == 0 else INK, "mm")
    y += 68
    y = c.field(x, y, fw, "Card number", "4242 4242 4242 4242")
    if phone:
        y = c.field(x, y, fw, "Expiry", "08 / 29")
    else:
        c.field(x, y, 200, "Expiry", "08 / 29")
        y = c.field(x + 220, y, 200, "CVC", "•••")
    c.button(x, y + 6, fw if phone else 260, 50, "Pay €148.00", size=16)
    if not phone:
        summary(c, x + w - 370, top + 52)


def placed(c, phone):
    top = header(c, phone, cart=0)
    w = c.w - 40 if phone else 560
    x = (c.w - w) / 2
    y = top + (30 if phone else 80)
    cx = x + w / 2
    c.d.ellipse(c.p(cx - 36, y, cx + 36, y + 72), fill="#dcfce7")
    c.d.line(c.p(cx - 16, y + 37, cx - 4, y + 49, cx + 18, y + 25), fill=GREEN, width=round(5 * c.s), joint="curve")
    y += 100
    c.text(cx, y, "Thank you, Dana!", 28, "bold", INK, "ma")
    c.text(cx, y + 46, "Order #10482 is confirmed.", 16, "reg", DIM, "ma")
    c.text(cx, y + 72, "It ships tomorrow from our warehouse.", 16, "reg", DIM, "ma")
    y += 120
    summary(c, x if phone else cx - 185, y, sw=w if phone else 370)
    c.button(x if phone else cx - 185, y + 254, w if phone else 370, 50, "Track my order", size=16)


SCREENS = {
    "01-sign-in": lambda c, ph: sign_in(c, ph),
    "02-reset": lambda c, ph: sign_in(c, ph, reset=True),
    "03-home": home,
    "04-shoes": category,
    "05-product": product,
    "06-cart": cart,
    "07-saved": lambda c, ph: cart(c, ph, saved=True),
    "08-address": address,
    "09-payment": payment,
    "10-placed": placed,
}


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, draw in SCREENS.items():
        for phone in (False, True):
            c = Canvas(390, 844, 2) if phone else Canvas(1600, 1000, 1)
            draw(c, phone)
            c.im.save(out / (name + (".phone" if phone else "") + ".png"), optimize=True)
    return out


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "."))
