from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "input" / "sample-scenes" / "scene_01"


def font(size: int):
    candidates = (
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def transparent(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    background = Image.new("RGB", (1920, 1080), "#e8dfc9")
    draw = ImageDraw.Draw(background)
    for x in range(0, 1920, 42):
        draw.line((x, 0, x + 300, 1080), fill="#ddd2b8", width=1)
    for y in range(45, 1080, 64):
        draw.line((0, y, 1920, y - 30), fill="#f0e9d8", width=2)
    background.save(DESTINATION / "background.jpg", quality=94)

    map_layer = transparent((1040, 700))
    draw = ImageDraw.Draw(map_layer)
    draw.rounded_rectangle((16, 16, 1024, 684), 8, fill="#d2b879", outline="#4c4332", width=5)
    for x in (230, 430, 660, 830):
        draw.line((x, 45, x - 70, 650), fill="#776847", width=3)
    for y in (180, 330, 490):
        draw.line((45, y, 990, y + 35), fill="#8a7954", width=3)
    draw.text((55, 45), "EUROPE 1992", fill="#2d2923", font=font(52))
    map_layer.save(DESTINATION / "map.png")

    bank = transparent((650, 430))
    draw = ImageDraw.Draw(bank)
    draw.polygon(((325, 25), (35, 150), (615, 150)), fill="#3c3b38", outline="#f1ead9", width=10)
    draw.rectangle((60, 150, 590, 355), fill="#55534d", outline="#f1ead9", width=10)
    for x in range(100, 570, 85):
        draw.rectangle((x, 165, x + 34, 330), fill="#ddd5c4")
    draw.rectangle((25, 355, 625, 410), fill="#33322f", outline="#f1ead9", width=10)
    bank.save(DESTINATION / "bank.png")

    pound = transparent((430, 520))
    draw = ImageDraw.Draw(pound)
    draw.text((55, -25), "£", fill="#262626", stroke_width=12, stroke_fill="#f4efdf", font=font(480))
    pound.save(DESTINATION / "pound.png")

    label = transparent((570, 150))
    draw = ImageDraw.Draw(label)
    draw.polygon(((10, 30), (550, 8), (560, 125), (20, 145)), fill="#f4e9c9", outline="#3b3427", width=4)
    draw.text((55, 42), "LONDON • SEPT 1992", fill="#25221d", font=font(45))
    label.save(DESTINATION / "label.png")

    alert = transparent((430, 145))
    draw = ImageDraw.Draw(alert)
    draw.rectangle((10, 12, 420, 133), fill="#d9ad34", outline="#332b1d", width=5)
    draw.text((38, 37), "POUND UNDER ATTACK", fill="#211d18", font=font(38))
    alert.save(DESTINATION / "alert.png")

    string = transparent((820, 390))
    draw = ImageDraw.Draw(string)
    points = ((30, 310), (265, 75), (485, 250), (785, 30))
    draw.line(points, fill="#a51f23", width=14, joint="curve")
    for x, y in points:
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill="#b59a58", outline="#493a1e", width=4)
    string.save(DESTINATION / "string.png")


if __name__ == "__main__":
    main()
