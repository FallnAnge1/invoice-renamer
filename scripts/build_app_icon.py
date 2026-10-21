"""从可维护的几何图形生成 Windows 多尺寸图标；仅构建时需要 Pillow。"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def build():
    folder = ROOT / "assets"
    folder.mkdir(exist_ok=True)
    scale = 4
    image = Image.new("RGBA", (256 * scale, 256 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    def box(values):
        return tuple(int(v * scale) for v in values)
    def points(values):
        return [(int(x * scale), int(y * scale)) for x, y in values]
    blue, cyan, white = "#245BE8", "#13B8C8", "#FFFFFF"
    draw.rounded_rectangle(box((12, 12, 244, 244)), radius=52 * scale, fill=blue)
    draw.polygon(points([(78, 46), (150, 46), (190, 86), (190, 198), (178, 210), (78, 210), (66, 198), (66, 58)]), fill=white)
    draw.polygon(points([(150, 46), (190, 86), (150, 86)]), fill="#A5F0F0")
    for end, y in ((164, 108), (164, 134), (138, 160)):
        draw.rounded_rectangle(box((88, y - 5, end, y + 5)), radius=5 * scale, fill=blue)
    draw.ellipse(box((149, 154, 217, 222)), fill=cyan, outline=blue, width=8 * scale)
    draw.ellipse(box((165, 170, 191, 196)), outline=white, width=7 * scale)
    draw.line(points([(188, 194), (201, 207)]), fill=white, width=7 * scale)
    image = image.resize((256, 256), Image.Resampling.LANCZOS)
    image.save(folder / "app.png")
    image.save(folder / "app.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])


if __name__ == "__main__":
    build()
