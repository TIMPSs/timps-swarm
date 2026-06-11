"""Generate TIMPS Swarm comparison GIF programmatically."""
from PIL import Image, ImageDraw, ImageFont
import math, os

W, H = 800, 533
BG = (10, 10, 10)
NEON = (0, 255, 65)
NEON_DIM = (0, 180, 40)
NEON_DARK = (0, 80, 20)
RED = (255, 60, 60)

def get_font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size)
    except:
        return ImageFont.load_default()

def blend(c1, c2, alpha):
    return tuple(int(c1[i] * (1 - alpha) + c2[i] * alpha) for i in range(3))

def draw_pixel_bar(draw, x, y, w, h, color, glow=False):
    for row in range(h):
        factor = 1.0 - (row / h) * 0.3
        c = tuple(int(v * factor) for v in color)
        draw.rectangle([x, y + h - 1 - row, x + w, y + h - row], fill=c)
    if glow:
        for i in range(8):
            gc = blend(color, BG, 0.08 * (1 - i / 8))
            draw.rectangle([x - i, y - i, x + w + i, y + h + i], outline=gc, width=1)

def draw_text(draw, text, x, y, size=12, color=NEON, anchor="mm"):
    font = get_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    if anchor == "mm":
        px = x - tw // 2
        py = y - th // 2
    elif anchor == "lm":
        px = x
        py = y - th // 2
    else:
        px, py = x, y
    draw.text((px, py), text, font=font, fill=color)

def draw_pixel_circle(draw, cx, cy, r, color):
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                draw.point((cx + dx, cy + dy), fill=color)

def draw_hive(draw, cx, cy, t):
    for r in range(50, 0, -2):
        a = 1.0 - r / 50
        c = blend(NEON, BG, a * 0.6)
        draw_pixel_circle(draw, cx, cy, r, c)
    for ring, radius in enumerate([22, 35, 48]):
        bounce = math.sin(t * 1.5 + ring) * 3
        r = radius + bounce
        a = 0.3 - ring * 0.08
        c = blend(NEON, BG, 1 - a)
        for i in range(6):
            a1 = (i / 6) * math.pi * 2 - math.pi / 6
            a2 = ((i + 1) / 6) * math.pi * 2 - math.pi / 6
            x1 = cx + math.cos(a1) * r
            y1 = cy + math.sin(a1) * r
            x2 = cx + math.cos(a2) * r
            y2 = cy + math.sin(a2) * r
            draw.line([x1, y1, x2, y2], fill=c, width=2)
    draw_text(draw, "HIVE", cx, cy, 14, NEON)

AGENTS = [
    ("API", (0, 255, 65)),
    ("DB", (68, 170, 255)),
    ("UI", (255, 170, 0)),
    ("CLI", (255, 102, 204)),
]

def draw_agents(draw, cx, cy, t):
    for i, (label, color) in enumerate(AGENTS):
        angle = (i / len(AGENTS)) * math.pi * 2 + t * 0.3
        r = 110 + math.sin(t * 0.8 + i * 2) * 15
        x = cx + math.cos(angle) * r
        y = cy + math.sin(angle) * r
        for g in range(10, 0, -2):
            gc = blend(color, BG, 0.15 * (1 - g / 10))
            draw_pixel_circle(draw, int(x), int(y), g, gc)
        bs = 8
        draw.rectangle([x - bs, y - bs, x + bs, y + bs], fill=color)
        draw.rectangle([x - bs + 2, y - bs + 2, x + bs - 2, y + bs - 2], fill=(10, 10, 10))
        draw_text(draw, label, x, y - bs - 8, 8, color)
        draw.line([x, y, cx, cy], fill=blend(NEON, BG, 0.85), width=1)

def draw_bar_chart(draw, t):
    ph = min(130, (t / 1.5) * 130) if t < 1.5 else 130
    sh = min(170, ((t - 0.5) / 1.5) * 170) if t > 0.5 else 0
    sh = min(170, sh)

    bx1, by1 = 220, 350
    bw = 60

    draw_pixel_bar(draw, bx1, int(by1 - ph), bw, int(ph), NEON, glow=True)
    draw_pixel_bar(draw, bx1 + 120, int(by1 - sh), bw, int(sh), RED)

    draw_text(draw, "PARALLEL", bx1 + bw // 2, by1 + 20, 11, NEON)
    pct = int(ph / max(ph, 0.01) * 100)
    draw_text(draw, f"{int(64 * ph/130)}s", bx1 + bw // 2, by1 - ph - 20, 11, NEON)

    draw_text(draw, "SEQUENTIAL", bx1 + 120 + bw // 2, by1 + 20, 11, RED)
    draw_text(draw, f"{int(192 * sh/170)}s", bx1 + 120 + bw // 2, by1 - sh - 20, 11, RED)

def draw_particles(draw, t):
    for i in range(15):
        x = (math.sin(t * 1.5 + i * 2.1) * 0.5 + 0.5) * 700 + 50
        y = (t * 40 + i * 40) % 500 - 20
        c = blend(NEON_DIM, BG, 0.5)
        draw.point((int(x), int(y)), fill=c)

def create_frame(frame_num, total_frames):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    t = (frame_num / total_frames) * 4

    for i in range(80):
        sx = (i * 137 + 50) % W
        sy = (i * 97 + 30) % H
        twinkle = math.sin(t * 2 + i * 0.7) * 0.3 + 0.3
        c_val = int(60 * twinkle)
        draw.point((sx, sy), fill=(c_val, c_val, c_val))

    cx, cy = 400, 150
    draw_hive(draw, cx, cy, t)
    draw_agents(draw, cx, cy, t)
    draw_particles(draw, t)

    draw.line([50, 260, 750, 260], fill=blend(NEON, BG, 0.9), width=1)

    draw_text(draw, "TIMPS SWARM", 400, 25, 22, NEON)
    draw_text(draw, "PARALLEL AGENT EXECUTION", 400, 55, 11, NEON_DIM)

    draw_text(draw, "COMPARISON", 400, 290, 12, NEON_DIM)
    draw_bar_chart(draw, t)

    if t > 2.0:
        alpha = min(1, (t - 2.0) * 2)
        c = blend(NEON, BG, 1 - alpha)
        draw_text(draw, "3x FASTER", 535, 310, 14, c)

    draw_text(draw, "4 agents  |  64s parallel  |  192s sequential", 400, 505, 9, NEON_DARK)

    return img

frames = []
total = 40
for i in range(total):
    frames.append(create_frame(i, total))
    if i % 10 == 0:
        print(f"  Frame {i+1}/{total}")

out_path = "/Users/sandeepreddy/Desktop/timps-swarm/demo/swarm-demo.gif"
frames[0].save(
    out_path,
    save_all=True,
    append_images=frames[1:],
    duration=100,
    loop=0,
    optimize=True,
)
print(f"\nGIF saved: {out_path}")
print(f"Size: {os.path.getsize(out_path) / 1024:.0f} KB")
