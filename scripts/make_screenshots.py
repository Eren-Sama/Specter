from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = [
    ("sample_run_pulmovision.md", "pulmovision_terminal.png", 56),
    ("sample_run_failure.md", "failure_recovery_terminal.png", 70),
]


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = Path("C:/Windows/Fonts") / name
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default()


def make_screenshot(source: str, output: str, max_lines: int) -> None:
    source_path = ROOT / "docs" / source
    output_path = ROOT / "docs" / "screenshots" / output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()[:max_lines]
    font = load_font("consola.ttf", 18)
    title_font = load_font("consolab.ttf", 20)

    width = 1280
    padding = 28
    line_height = 24
    title_height = 48
    height = padding * 2 + title_height + line_height * len(lines)

    image = Image.new("RGB", (width, height), (22, 26, 34))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, title_height), fill=(33, 38, 48))
    draw.text((padding, 13), source.replace(".md", ""), font=title_font, fill=(235, 238, 245))

    y = title_height + padding
    for index, line in enumerate(lines):
        draw.text((padding, y + index * line_height), line[:130], font=font, fill=(224, 229, 236))

    image.save(output_path)


def main() -> None:
    for source, output, max_lines in SCREENSHOTS:
        make_screenshot(source, output, max_lines)


if __name__ == "__main__":
    main()

