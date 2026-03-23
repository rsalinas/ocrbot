#!/usr/bin/env python3
"""Generate OCR test images from a real Wikipedia article.

Example:
  python scripts/gen_test_images.py --title "Inteligencia artificial" --lang es --max-images 24
"""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Rendering parameters
# ---------------------------------------------------------------------------
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 28
IMG_W = 720
IMG_BG = (255, 255, 255)
TEXT_COLOR = (30, 30, 30)
PADDING = 36
LINE_SPACING = 1.35

DEFAULT_TARGET_WORDS = 106
DEFAULT_MIN_WORDS = 60
DEFAULT_MAX_IMAGES = 24


def fetch_wikipedia_extract(title: str, lang: str, timeout: int = 20) -> str:
    """Fetch plain-text article extract from Wikipedia API."""
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": 1,
        "redirects": 1,
        "titles": title,
        "format": "json",
    }
    url = f"https://{lang}.wikipedia.org/w/api.php?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": "ocrbot-test-image-generator/1.0 (https://github.com/)",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        raise RuntimeError("Wikipedia response did not include any pages")

    page = next(iter(pages.values()))
    extract = page.get("extract", "")
    if not extract.strip():
        raise RuntimeError("Wikipedia page has no extract text")
    return extract


def clean_text(text: str) -> str:
    """Normalize whitespace and remove common reference markers like [12]."""
    text = re.sub(r"\[[0-9]+\]", "", text)
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_long_paragraph(paragraph: str, target_words: int) -> list[str]:
    """Split very long paragraphs by sentence or words."""
    words = paragraph.split()
    if len(words) <= target_words:
        return [paragraph]

    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    chunks: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        s_words = sentence.split()
        if not s_words:
            continue
        if len(current) + len(s_words) <= target_words:
            current.extend(s_words)
            continue
        if current:
            chunks.append(" ".join(current))
            current = []

        if len(s_words) > target_words:
            for i in range(0, len(s_words), target_words):
                chunks.append(" ".join(s_words[i : i + target_words]))
        else:
            current = s_words

    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_article(text: str, target_words: int, min_words: int, max_images: int) -> list[str]:
    """Chunk article text into image-sized pieces, preserving paragraph boundaries when possible."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []

    for paragraph in paragraphs:
        pieces.extend(split_long_paragraph(paragraph, target_words))

    chunks: list[str] = []
    current_words: list[str] = []

    for piece in pieces:
        p_words = piece.split()
        if not p_words:
            continue

        if len(current_words) + len(p_words) <= target_words:
            current_words.extend(p_words)
            continue

        if current_words:
            chunks.append(" ".join(current_words))
            current_words = []

        if len(p_words) > target_words:
            for i in range(0, len(p_words), target_words):
                chunks.append(" ".join(p_words[i : i + target_words]))
        else:
            current_words = p_words

        if len(chunks) >= max_images:
            break

    if current_words and len(chunks) < max_images:
        chunks.append(" ".join(current_words))

    # Merge tiny trailing chunk into previous one when possible.
    if len(chunks) >= 2 and len(chunks[-1].split()) < min_words:
        merged = f"{chunks[-2]} {chunks[-1]}".strip()
        if len(merged.split()) <= target_words + min_words:
            chunks[-2] = merged
            chunks.pop()

    return chunks[:max_images]


def make_image(index: int, text: str, out_dir: Path) -> Path:
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    usable_w = IMG_W - 2 * PADDING
    line_h = int(FONT_SIZE * LINE_SPACING)

    wrapped_lines = textwrap.wrap(text, width=int(usable_w / (FONT_SIZE * 0.52)))

    total_text_h = len(wrapped_lines) * line_h + 2 * PADDING
    img_h = max(total_text_h, 400)

    img = Image.new("RGB", (IMG_W, img_h), IMG_BG)
    draw = ImageDraw.Draw(img)

    y = PADDING
    for line in wrapped_lines:
        draw.text((PADDING, y), line, font=font, fill=TEXT_COLOR)
        y += line_h

    out_path = out_dir / f"wiki_{index:02d}.jpg"
    img.save(out_path, "JPEG", quality=92)
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate OCR test images from Wikipedia")
    parser.add_argument("--title", required=True, help="Wikipedia article title")
    parser.add_argument("--lang", default="es", help="Wikipedia language code (default: es)")
    parser.add_argument("--target-words", type=int, default=DEFAULT_TARGET_WORDS)
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS)
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parent.parent / "tests" / "images"),
        help="Output directory for generated images",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = fetch_wikipedia_extract(args.title, args.lang)
    cleaned = clean_text(raw)
    chunks = chunk_article(
        text=cleaned,
        target_words=args.target_words,
        min_words=args.min_words,
        max_images=args.max_images,
    )

    if not chunks:
        raise RuntimeError("No text chunks generated from article")

    print(
        f"Generating {len(chunks)} images from Wikipedia article '{args.title}' "
        f"({args.lang}) -> {out_dir}"
    )
    for i, chunk in enumerate(chunks, start=1):
        path = make_image(i, chunk, out_dir)
        print(f"  [{i:02d}] {path.name}  chars={len(chunk)}  words={len(chunk.split())}")
    print(f"Done. {len(chunks)} images saved to {out_dir}")


if __name__ == "__main__":
    main()
