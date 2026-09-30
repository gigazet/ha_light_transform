"""Render original RGB-to-white transformation artwork with no external assets."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND = Path(__file__).resolve().parents[1] / "custom_components" / "light_transform" / "brand"
BACKGROUND = "#111C30"
FOREGROUND = "#F5F8FF"
MUTED = "#B1C0D9"


def icon(size: int) -> Image.Image:
    scale = 4
    image = Image.new("RGBA", (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(image)

    def box(coords: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(value * scale for value in coords)

    draw.rounded_rectangle(box((0, 0, 256, 256)), radius=52 * scale, fill=BACKGROUND)
    for y, color in ((78, "#FF727C"), (128, "#51D8A0"), (178, "#69ACFF")):
        draw.line(
            [(34 * scale, y * scale), (70 * scale, y * scale), (106 * scale, 128 * scale)],
            fill=color,
            width=8 * scale,
            joint="curve",
        )
        draw.ellipse(box((26, y - 7, 40, y + 7)), fill=color)

    draw.line(
        (140 * scale, 128 * scale, 167 * scale, 128 * scale), fill=FOREGROUND, width=8 * scale
    )
    draw.polygon(
        [(x * scale, y * scale) for x, y in ((110, 89), (148, 128), (110, 167), (82, 128))],
        fill="#243851",
        outline="#ADC9EE",
        width=3 * scale,
    )
    draw.line(
        [(x * scale, y * scale) for x, y in ((109, 111), (125, 128), (109, 145))],
        fill=FOREGROUND,
        width=5 * scale,
        joint="curve",
    )
    draw.ellipse(box((161, 96, 221, 156)), fill="#FFD387")
    draw.pieslice(box((161, 96, 221, 156)), start=270, end=90, fill="#C9EDFF")
    draw.rounded_rectangle(box((176, 143, 206, 163)), radius=5 * scale, fill=FOREGROUND)
    draw.rounded_rectangle(box((178, 169, 204, 176)), radius=3 * scale, fill=MUTED)
    draw.rounded_rectangle(box((183, 182, 199, 189)), radius=3 * scale, fill=MUTED)
    for start, end in (((191, 75), (191, 82)), ((228, 88), (223, 93)), ((154, 88), (159, 93))):
        draw.line(
            [(start[0] * scale, start[1] * scale), (end[0] * scale, end[1] * scale)],
            fill="#FFD387",
            width=4 * scale,
        )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def logo(scale: int) -> Image.Image:
    image = Image.new("RGBA", (1024 * scale, 320 * scale))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 1024 * scale, 320 * scale), radius=40 * scale, fill=BACKGROUND)
    image.alpha_composite(icon(256 * scale), (32 * scale, 32 * scale))
    draw.text(
        (324 * scale, 99 * scale),
        "Light Transform",
        font=ImageFont.load_default(size=68 * scale),
        fill=FOREGROUND,
    )
    draw.text(
        (327 * scale, 185 * scale),
        "Real channels. The right light.",
        font=ImageFont.load_default(size=29 * scale),
        fill=MUTED,
    )
    return image


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    for name, image in (
        ("icon.png", icon(256)),
        ("icon@2x.png", icon(512)),
        ("logo.png", logo(1)),
        ("logo@2x.png", logo(2)),
    ):
        image.save(BRAND / name, optimize=True)
        print(BRAND / name)


if __name__ == "__main__":
    main()
