from __future__ import annotations

import io
import math
import os
import re
import textwrap
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

import fitz  # PyMuPDF
import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_W = 1240
PAGE_H = 1754
BG = (248, 245, 237)
GREEN = (40, 94, 66)
LAVENDER = (128, 101, 151)
GOLD = (181, 139, 58)
TEAL = (92, 142, 143)
CORAL = (207, 112, 74)
TEXT = (55, 52, 48)
MUTED = (113, 106, 98)


@dataclass
class WorkData:
    title: str = ""
    technique: str = ""
    size: str = ""
    year: str = ""
    author: str = ""
    image: Image.Image | None = None


@dataclass
class ParsedPDF:
    raw_text: str
    artist_name: str
    location: str
    biography: str
    images: list[Image.Image]
    image_labels: list[str]
    works: list[WorkData]


def _font_path(preferred: list[str]) -> str | None:
    roots = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation2",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/opentype",
    ]
    for root in roots:
        for name in preferred:
            path = os.path.join(root, name)
            if os.path.exists(path):
                return path
    # broad fallback search
    for root, _, files in os.walk("/usr/share/fonts"):
        for name in preferred:
            if name in files:
                return os.path.join(root, name)
    return None


FONT_SERIF = _font_path(["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"])
FONT_SERIF_ITALIC = _font_path(["DejaVuSerif-Italic.ttf", "LiberationSerif-Italic.ttf"])
FONT_SERIF_BOLD = _font_path(["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf"])
FONT_SANS = _font_path(["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
FONT_SANS_BOLD = _font_path(["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"])


def font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path:
        return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "artista"


def parse_pdf(pdf_bytes: bytes) -> ParsedPDF:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts: list[str] = []
    images: list[Image.Image] = []
    labels: list[str] = []
    seen_xrefs: set[int] = set()

    for page_no, page in enumerate(doc, start=1):
        page_texts.append(page.get_text("text"))
        for image_no, info in enumerate(page.get_images(full=True), start=1):
            xref = info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                extracted = doc.extract_image(xref)
                pil = Image.open(io.BytesIO(extracted["image"])).convert("RGB")
                # Ignore tiny decorative images if any.
                if pil.width < 220 or pil.height < 220:
                    continue
                images.append(pil)
                labels.append(f"Imagem {len(images)} — página {page_no} — {pil.width}×{pil.height}px")
            except Exception:
                continue

    raw_text = "\n".join(page_texts)
    raw_text = raw_text.replace("\u200b", " ")
    raw_text = raw_text.replace("\ufeff", " ")
    raw_text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in raw_text.splitlines())
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    first_line = lines[0] if lines else "Artista"
    heading_match = re.match(r"^(.*?)\s*-\s*([A-Z]{2})\s*-\s*(.+)$", first_line)
    if heading_match:
        artist_name = heading_match.group(1).strip()
        location = f"{heading_match.group(2).strip()} - {heading_match.group(3).strip()}"
    else:
        name_parts = [p.strip() for p in re.split(r"\s+-\s+", first_line)]
        artist_name = name_parts[0] if name_parts else first_line
        location = " - ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    marker = re.search(r"\n\s*Autor(?:a)?:", raw_text, flags=re.I)
    bio_block = raw_text[: marker.start()] if marker else raw_text
    # Remove first heading line from biography.
    bio_lines = bio_block.splitlines()
    if bio_lines and bio_lines[0].strip() == first_line:
        bio_lines = bio_lines[1:]
    biography = "\n".join(ln.strip() for ln in bio_lines).strip()
    biography = re.sub(r"[ \t]+", " ", biography)
    biography = re.sub(r"\n{3,}", "\n\n", biography)

    works: list[WorkData] = []
    pattern = re.compile(
        r"Autor(?:a)?:\s*(?P<author>.*?)\n"
        r"Título:\s*(?P<title>.*?)\n"
        r"Técnica:\s*(?P<technique>.*?)\n"
        r"Tamanho:\s*(?P<size>.*?)\n"
        r"Ano:\s*(?P<year>\d{4}|[^\n]+)",
        flags=re.I | re.S,
    )
    for match in pattern.finditer(raw_text):
        works.append(
            WorkData(
                author=match.group("author").strip(),
                title=match.group("title").strip(),
                technique=match.group("technique").strip(" -"),
                size=match.group("size").strip(),
                year=match.group("year").strip(),
            )
        )

    return ParsedPDF(
        raw_text=raw_text,
        artist_name=artist_name,
        location=location,
        biography=biography,
        images=images,
        image_labels=labels,
        works=works,
    )


def paper_background(seed: int = 12) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = np.full((PAGE_H, PAGE_W, 3), BG, dtype=np.int16)
    noise = rng.normal(0, 2.3, (PAGE_H, PAGE_W, 1)).astype(np.int16)
    base = np.clip(base + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(base, "RGB").convert("RGBA")
    layer = Image.new("RGBA", (PAGE_W, PAGE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Painted corners inspired by the approved layout.
    d.polygon([(0, 0), (330, 0), (120, 95), (0, 180)], fill=(164, 137, 187, 95))
    d.polygon([(PAGE_W, 0), (1020, 0), (PAGE_W, 160)], fill=(128, 159, 117, 70))
    d.polygon([(0, PAGE_H), (0, 1480), (200, PAGE_H)], fill=(101, 157, 161, 80))
    d.polygon([(PAGE_W, PAGE_H), (970, PAGE_H), (PAGE_W, 1390)], fill=(223, 126, 79, 90))
    layer = layer.filter(ImageFilter.GaussianBlur(10))
    return Image.alpha_composite(img, layer)


def draw_leaf(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float, color: tuple[int, int, int, int], flip: bool = False) -> None:
    sign = -1 if flip else 1
    pts = []
    for i in range(7):
        px = x + int(sign * i * 16 * scale)
        py = y - int(i * 22 * scale)
        pts.append((px, py))
    draw.line(pts, fill=color, width=max(2, int(3 * scale)))
    for i, (px, py) in enumerate(pts[1:], start=1):
        r = max(6, int((15 - i) * scale))
        draw.ellipse((px - r, py - r // 2, px + r, py + r // 2), outline=color, width=max(1, int(2 * scale)))


def decorative_background(page_number: int) -> Image.Image:
    img = paper_background(seed=10 + page_number)
    d = ImageDraw.Draw(img)
    draw_leaf(d, 72, 260, 1.2, (181, 139, 58, 165), flip=False)
    draw_leaf(d, PAGE_W - 70, PAGE_H - 100, 1.0, (181, 139, 58, 160), flip=True)
    if page_number == 2:
        draw_leaf(d, 80, PAGE_H - 360, 0.9, (128, 101, 151, 150), flip=False)
    return img


def fit_image(image: Image.Image, box: tuple[int, int, int, int], contain: bool = False) -> Image.Image:
    x, y, w, h = box
    image = image.convert("RGB")
    if contain:
        fitted = ImageOps.contain(image, (w, h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (w, h), (246, 242, 233))
        canvas.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
        return canvas
    return ImageOps.fit(image, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def text_width(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> float:
    return draw.textlength(text, font=fnt)


def wrap_paragraph(draw: ImageDraw.ImageDraw, paragraph: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = paragraph.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        if text_width(draw, trial, fnt) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    output: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text.strip()) if text.strip() else []
    for pi, paragraph in enumerate(paragraphs):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        output.extend(wrap_paragraph(draw, paragraph, fnt, max_width))
        if pi < len(paragraphs) - 1:
            output.append("")
    return output


def split_lines(lines: list[str], max_lines: int) -> tuple[list[str], list[str]]:
    if len(lines) <= max_lines:
        return lines, []
    head = lines[:max_lines]
    tail = lines[max_lines:]
    # Avoid starting continuation with an empty line.
    while tail and tail[0] == "":
        tail.pop(0)
    return head, tail


def draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    xy: tuple[int, int],
    fnt: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    line_height: int,
    first_initial: bool = False,
) -> int:
    x, y = xy
    lines = list(lines)
    for idx, line in enumerate(lines):
        if line:
            if first_initial and idx == 0 and line:
                initial = line[0]
                drop = font(FONT_SERIF, int(getattr(fnt, "size", 28) * 2.1))
                draw.text((x, y - 10), initial, font=drop, fill=LAVENDER)
                draw.text((x + 55, y + 5), line[1:].lstrip(), font=fnt, fill=fill)
            else:
                draw.text((x, y), line, font=fnt, fill=fill)
        y += line_height
    return y


def draw_frame(img: Image.Image, box: tuple[int, int, int, int], color: tuple[int, int, int] = GOLD, width: int = 3) -> None:
    d = ImageDraw.Draw(img)
    x, y, w, h = box
    d.rectangle((x - 7, y - 7, x + w + 7, y + h + 7), outline=color, width=width)


def render_page_one(
    artist_name: str,
    location: str,
    biography: str,
    portrait: Image.Image,
    quote: str = "",
) -> tuple[Image.Image, list[str]]:
    img = decorative_background(1)
    d = ImageDraw.Draw(img)

    title_font = font(FONT_SERIF, 78)
    location_font = font(FONT_SANS_BOLD, 28)
    body_font = font(FONT_SERIF, 27)
    quote_font = font(FONT_SERIF_ITALIC, 40)

    # Header
    title_bbox = d.textbbox((0, 0), artist_name, font=title_font)
    tw = title_bbox[2] - title_bbox[0]
    d.text(((PAGE_W - tw) / 2, 75), artist_name, font=title_font, fill=GREEN)
    loc = location.upper() if location else "ARTISTA"
    lw = d.textlength(loc, font=location_font)
    d.line((230, 190, 455, 190), fill=GOLD, width=2)
    d.line((785, 190, 1010, 190), fill=GOLD, width=2)
    d.text(((PAGE_W - lw) / 2, 172), loc, font=location_font, fill=LAVENDER)

    # Portrait
    portrait_box = (330, 245, 600, 710)
    portrait_img = fit_image(portrait, portrait_box, contain=False)
    img.paste(portrait_img, portrait_box[:2])
    draw_frame(img, portrait_box)

    # Optional quote or decorative phrase area.
    if quote.strip():
        q_lines = wrap_text(d, quote.strip(), quote_font, 245)
        yq = 430
        for line in q_lines[:6]:
            w = d.textlength(line, font=quote_font)
            d.text((55 + (245 - w) / 2, yq), line, font=quote_font, fill=LAVENDER)
            yq += 56
        d.arc((110, yq + 5, 250, yq + 65), 10, 165, fill=GOLD, width=2)
    else:
        draw_leaf(d, 170, 740, 0.8, (128, 101, 151, 160), flip=False)

    # Biography area
    bio_y = 1015
    bio_x = 105
    bio_w = 1030
    line_h = 40
    all_lines = wrap_text(d, biography, body_font, bio_w)
    page1_lines, continuation = split_lines(all_lines, 15)
    d.line((95, bio_y - 20, 95, 1645), fill=LAVENDER, width=3)
    draw_lines(d, page1_lines, (125, bio_y), body_font, TEXT, line_h, first_initial=True)

    # Footer ornament
    d.line((410, 1690, 570, 1690), fill=GOLD, width=2)
    d.ellipse((612, 1684, 624, 1696), fill=GOLD)
    d.line((665, 1690, 825, 1690), fill=GOLD, width=2)

    return img.convert("RGB"), continuation


def draw_metadata_block(
    img: Image.Image,
    work: WorkData,
    x: int,
    y: int,
    width: int,
    compact: bool = False,
) -> int:
    d = ImageDraw.Draw(img)
    label_font = font(FONT_SERIF_BOLD, 28 if not compact else 24)
    value_font = font(FONT_SERIF, 27 if not compact else 23)
    line_height = 51 if not compact else 42
    fields = [
        ("Autora:", work.author),
        ("Título:", work.title),
        ("Técnica:", work.technique),
        ("Tamanho:", work.size),
        ("Ano:", work.year),
    ]
    d.line((x, y - 30, x + width, y - 30), fill=GOLD, width=2)
    for label, value in fields:
        if not value:
            continue
        d.text((x, y), label, font=label_font, fill=LAVENDER)
        label_w = d.textlength(label + " ", font=label_font)
        max_val_w = width - int(label_w)
        lines = wrap_paragraph(d, value, value_font, max_val_w)
        if len(lines) == 1:
            d.text((x + label_w, y), value, font=value_font, fill=TEXT)
            y += line_height
        else:
            # label on first line, wrapped values below.
            d.text((x + label_w, y), lines[0], font=value_font, fill=TEXT)
            y += line_height
            for extra in lines[1:]:
                d.text((x + 20, y), extra, font=value_font, fill=TEXT)
                y += line_height
    return y


def make_qr(link: str, size: int = 150) -> Image.Image:
    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    return qr.make_image(fill_color=GREEN, back_color=BG).convert("RGB").resize((size, size), Image.Resampling.NEAREST)


def draw_link_footer(img: Image.Image, link: str, link_label: str, y: int) -> tuple[int, int, int, int] | None:
    if not link.strip():
        return None
    d = ImageDraw.Draw(img)
    heading_font = font(FONT_SERIF_BOLD, 28)
    value_font = font(FONT_SANS, 24)
    qr = make_qr(link, 130)
    x = 190
    d.rounded_rectangle((x, y, PAGE_W - 190, y + 155), radius=24, outline=GOLD, width=2, fill=(250, 248, 242, 230))
    img.paste(qr, (x + 20, y + 13))
    d.text((x + 175, y + 28), "Conheça mais sobre a artista", font=heading_font, fill=GREEN)
    label = link_label.strip() or link
    if len(label) > 58:
        label = label[:55] + "..."
    d.text((x + 175, y + 82), label, font=value_font, fill=TEXT)
    return (x + 165, y + 15, PAGE_W - 210, y + 140)


def render_page_two(
    continuation_lines: list[str],
    works: list[WorkData],
    link: str = "",
    link_label: str = "",
) -> tuple[Image.Image, tuple[int, int, int, int] | None, bool]:
    img = decorative_background(2)
    d = ImageDraw.Draw(img)
    body_font = font(FONT_SERIF, 27)
    overflow = False

    if len(works) not in (2, 3):
        raise ValueError("O catálogo deve conter 2 ou 3 obras.")

    # Biography continuation.
    if continuation_lines:
        max_cont = 6 if len(works) == 2 else 4
        shown, rest = split_lines(continuation_lines, max_cont)
        overflow = bool(rest)
        draw_lines(d, shown, (205, 110), body_font, TEXT, 40, first_initial=False)
        d.line((390, 60, 555, 60), fill=GOLD, width=2)
        d.ellipse((612, 54, 624, 66), fill=GOLD)
        d.line((680, 60, 845, 60), fill=GOLD, width=2)

    link_rect: tuple[int, int, int, int] | None = None

    if len(works) == 2:
        # Work 1
        box1 = (95, 385, 575, 490)
        img1 = fit_image(works[0].image or Image.new("RGB", (800, 600), "white"), box1, contain=True)
        img.paste(img1, box1[:2])
        draw_frame(img, box1)
        draw_metadata_block(img, works[0], 720, 470, 410, compact=False)

        # Work 2
        box2 = (590, 1000, 555, 470)
        img2 = fit_image(works[1].image or Image.new("RGB", (800, 600), "white"), box2, contain=True)
        img.paste(img2, box2[:2])
        draw_frame(img, box2)
        draw_metadata_block(img, works[1], 125, 1060, 390, compact=False)
        if link:
            link_rect = draw_link_footer(img, link, link_label, 1520)
        else:
            d.text((PAGE_W / 2 - 8, 1660), "2", font=font(FONT_SERIF_BOLD, 28), fill=GOLD)
    else:
        # Three horizontal artwork records with alternating image positions.
        y_positions = [300, 735, 1170]
        for idx, (work, y) in enumerate(zip(works, y_positions)):
            if idx % 2 == 0:
                ibox = (85, y, 500, 330)
                meta_x = 650
            else:
                ibox = (655, y, 500, 330)
                meta_x = 90
            art = fit_image(work.image or Image.new("RGB", (800, 600), "white"), ibox, contain=True)
            img.paste(art, ibox[:2])
            draw_frame(img, ibox)
            draw_metadata_block(img, work, meta_x, y + 45, 485, compact=True)
        if link:
            link_rect = draw_link_footer(img, link, link_label, 1555)
        else:
            d.text((PAGE_W / 2 - 8, 1680), "2", font=font(FONT_SERIF_BOLD, 28), fill=GOLD)

    return img.convert("RGB"), link_rect, overflow


def build_catalog(
    artist_name: str,
    location: str,
    biography: str,
    portrait: Image.Image,
    works: list[WorkData],
    quote: str = "",
    link: str = "",
    link_label: str = "",
) -> tuple[bytes, bytes, bytes, bool]:
    page1, continuation = render_page_one(artist_name, location, biography, portrait, quote)
    page2, link_rect, overflow = render_page_two(continuation, works, link, link_label)

    p1_io = io.BytesIO()
    page1.save(p1_io, format="PNG", optimize=True)
    p1_bytes = p1_io.getvalue()
    p2_io = io.BytesIO()
    page2.save(p2_io, format="PNG", optimize=True)
    p2_bytes = p2_io.getvalue()

    pdf_io = io.BytesIO()
    c = canvas.Canvas(pdf_io, pagesize=A4)
    a4w, a4h = A4
    for page_index, page_bytes in enumerate((p1_bytes, p2_bytes), start=1):
        c.drawImage(ImageReader(io.BytesIO(page_bytes)), 0, 0, width=a4w, height=a4h)
        if page_index == 2 and link and link_rect:
            x1, y1, x2, y2 = link_rect
            # Convert top-left pixels to PDF bottom-left coordinates.
            px_to_pt_x = a4w / PAGE_W
            px_to_pt_y = a4h / PAGE_H
            c.linkURL(
                link,
                (
                    x1 * px_to_pt_x,
                    a4h - y2 * px_to_pt_y,
                    x2 * px_to_pt_x,
                    a4h - y1 * px_to_pt_y,
                ),
                relative=0,
            )
        c.showPage()
    c.save()
    return pdf_io.getvalue(), p1_bytes, p2_bytes, overflow
