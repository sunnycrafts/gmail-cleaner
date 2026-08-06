"""Generate app.ico — a simple envelope-with-sparkle mark on a Fluent-blue tile."""
from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# rounded blue tile
blue = (0, 103, 192, 255)
r = 48
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=r, fill=blue)

# envelope
ex0, ey0, ex1, ey1 = 56, 84, 200, 178
white = (255, 255, 255, 255)
d.rounded_rectangle([ex0, ey0, ex1, ey1], radius=12, fill=white)
# flap
d.line([(ex0 + 6, ey0 + 10), (128, 134), (ex1 - 6, ey0 + 10)],
       fill=blue, width=10, joint="curve")

# sparkle (clean/tidy motif) top-right
sx, sy = 196, 70
for dx, dy, ln in [(0, -22, 22), (0, 22, 22), (-22, 0, 22), (22, 0, 22)]:
    d.line([(sx, sy), (sx + dx, sy + dy)], fill=(255, 214, 102, 255), width=8)

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save("app.ico", sizes=sizes)
print("app.ico written")
