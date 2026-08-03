from __future__ import annotations

import colorsys
import hashlib
import io
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

import fitz  # PyMuPDF
import numpy as np
import qrcode
from PIL import Image, ImageEnhance, ImageOps
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, Paragraph, Spacer

PAGE_W_PT, PAGE_H_PT = A4
PREVIEW_DPI = 150


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
    body_font_size: float = 11.5
    body_leading: float = 15.0
    paragraph_space_after: float = 12.0
    metadata_font_size: float = 10.5
    body_font_family: str = "sans"


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    text: str
    muted: str
    accent: str
    accent2: str
    accent3: str
    panel: str


_FAMILY_LABELS = {
    "organico": "Orgânico",
    "contemporaneo": "Contemporâneo",
    "minimalista": "Minimalista",
    "poetico": "Poético",
    "geometrico": "Geométrico",
}


def family_label(value: str) -> str:
    return _FAMILY_LABELS.get(value, value.title())


_FONT_CANDIDATES = {
    "serif": ["LiberationSerif-Regular.ttf", "DejaVuSerif.ttf", "NotoSerif-Regular.ttf"],
    "serif_bold": ["LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf", "NotoSerif-Bold.ttf"],
    "serif_italic": ["LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf", "NotoSerif-Italic.ttf"],
    "sans": ["LiberationSans-Regular.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf"],
    "sans_bold": ["LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf"],
}


def _discover_fonts() -> dict[str, str | None]:
    roots = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    available: dict[str, str] = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for current_root, _, files in os.walk(root):
            for filename in files:
                available.setdefault(filename.lower(), os.path.join(current_root, filename))
    found: dict[str, str | None] = {}
    for role, candidates in _FONT_CANDIDATES.items():
        found[role] = next((available.get(name.lower()) for name in candidates if available.get(name.lower())), None)
    return found


_FONTS = _discover_fonts()
_FONTS_REGISTERED = False


def ensure_fonts() -> None:
    missing = [role for role, path in _FONTS.items() if not path]
    if missing:
        raise RuntimeError(
            "As fontes editoriais não estão instaladas. Confirme se packages.txt contém "
            "fonts-dejavu-core e fonts-liberation2. Funções ausentes: " + ", ".join(missing)
        )


def register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    ensure_fonts()
    pdfmetrics.registerFont(TTFont("UCSerif", _FONTS["serif"]))
    pdfmetrics.registerFont(TTFont("UCSerifBold", _FONTS["serif_bold"]))
    pdfmetrics.registerFont(TTFont("UCSerifItalic", _FONTS["serif_italic"]))
    pdfmetrics.registerFont(TTFont("UCSans", _FONTS["sans"]))
    pdfmetrics.registerFont(TTFont("UCSansBold", _FONTS["sans_bold"]))
    pdfmetrics.registerFontFamily("UCSans", normal="UCSans", bold="UCSansBold", italic="UCSans", boldItalic="UCSansBold")
    pdfmetrics.registerFontFamily("UCSerif", normal="UCSerif", bold="UCSerifBold", italic="UCSerifItalic", boldItalic="UCSerifBold")
    _FONTS_REGISTERED = True


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "artista"


def normalize_size(value: str) -> str:
    value = re.sub(r"\s*[xX×]\s*", " × ", value.strip())
    value = re.sub(r"\s*(cm|mm|m)\b", r" \1", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def clean_title(value: str) -> str:
    return re.sub(r"\s+-\s*$", "", value.strip())


def _clean_pdf_text(value: str) -> str:
    value = value.replace("\u200b", " ").replace("\ufeff", " ").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def _font_family_from_name(name: str) -> str:
    lowered = (name or "").lower()
    serif_tokens = ("times", "serif", "garamond", "georgia", "baskerville", "cambria", "palatino")
    return "serif" if any(token in lowered for token in serif_tokens) else "sans"


def _median(values: list[float], fallback: float) -> float:
    if not values:
        return fallback
    values = sorted(values)
    mid = len(values) // 2
    return float(values[mid]) if len(values) % 2 else float((values[mid - 1] + values[mid]) / 2)


def parse_pdf(pdf_bytes: bytes) -> ParsedPDF:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts: list[str] = []
    images: list[Image.Image] = []
    labels: list[str] = []
    seen_xrefs: set[int] = set()
    all_blocks: list[tuple[int, tuple[float, float, float, float], str]] = []
    span_records: list[tuple[int, float, str, tuple[float, float, float, float], str]] = []

    for page_no, page in enumerate(doc, start=1):
        page_text = _clean_pdf_text(page.get_text("text"))
        page_texts.append(page_text)

        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text = block[:5]
            cleaned = _clean_pdf_text(text)
            if cleaned:
                all_blocks.append((page_no, (x0, y0, x1, y1), cleaned))

        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = _clean_pdf_text(span.get("text", ""))
                    if text:
                        span_records.append(
                            (page_no, float(span.get("size", 0.0)), span.get("font", ""), tuple(span.get("bbox", (0, 0, 0, 0))), text)
                        )

        for info in page.get_images(full=True):
            xref = info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                extracted = doc.extract_image(xref)
                pil = Image.open(io.BytesIO(extracted["image"])).convert("RGB")
                if pil.width < 220 or pil.height < 220:
                    continue
                images.append(pil)
                labels.append(f"Imagem {len(images)} — página {page_no} — {pil.width}×{pil.height}px")
            except Exception:
                continue

    raw_text = "\n".join(page_texts)
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    first_line = lines[0] if lines else "Artista"
    heading_match = re.match(r"^(.*?)\s*-\s*([A-Z]{2})\s*-\s*(.+)$", first_line)
    if heading_match:
        artist_name = heading_match.group(1).strip()
        location = f"{heading_match.group(2).strip()} - {heading_match.group(3).strip()}"
    else:
        name_parts = [part.strip() for part in re.split(r"\s+-\s+", first_line)]
        artist_name = name_parts[0] if name_parts else first_line
        location = " - ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    # Preserve the paragraph logic of the source PDF by using its text blocks.
    biography_blocks: list[str] = []
    metadata_started = False
    for page_no, _bbox, block_text in sorted(all_blocks, key=lambda item: (item[0], item[1][1], item[1][0])):
        if re.match(r"^Autor(?:a)?:", block_text, flags=re.I):
            metadata_started = True
        if metadata_started:
            continue
        if page_no == 1 and block_text.replace(" ", "").startswith(first_line.replace(" ", "")):
            continue
        if not block_text:
            continue
        block_text = block_text.replace("\n", " ")
        block_text = re.sub(r"\s+", " ", block_text).strip()
        if not block_text:
            continue
        if biography_blocks and block_text[:1].islower() and not re.search(r"[.!?…][\"'”’)]?$", biography_blocks[-1]):
            biography_blocks[-1] = biography_blocks[-1].rstrip() + " " + block_text
        else:
            biography_blocks.append(block_text)

    biography = "\n\n".join(biography_blocks).strip()
    if not biography:
        marker = re.search(r"\n\s*Autor(?:a)?:", raw_text, flags=re.I)
        bio_block = raw_text[: marker.start()] if marker else raw_text
        bio_lines = bio_block.splitlines()
        if bio_lines and bio_lines[0].strip() == first_line:
            bio_lines = bio_lines[1:]
        biography = "\n".join(line.strip() for line in bio_lines).strip()

    works: list[WorkData] = []
    pattern = re.compile(
        r"Autor(?:a)?:\s*(?P<author>.*?)\n"
        r"Título:\s*(?P<title>.*?)\n"
        r"Técnica:\s*(?P<technique>.*?)\n"
        r"(?:Tamanho|Dimensões):\s*(?P<size>.*?)\n"
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

    # Typography is inferred from the source PDF rather than imposed arbitrarily.
    bio_sizes: list[float] = []
    bio_fonts: list[str] = []
    metadata_sizes: list[float] = []
    line_tops_by_page: dict[int, list[float]] = {}
    metadata_mode = False
    for page_no, size, font, bbox, text in span_records:
        if re.match(r"^Autor(?:a)?:", text, flags=re.I):
            metadata_mode = True
        if metadata_mode:
            if size > 0:
                metadata_sizes.append(size)
            continue
        normalized = text.replace(" ", "")
        if page_no == 1 and normalized in first_line.replace(" ", ""):
            continue
        if size > 0 and len(text) > 2:
            bio_sizes.append(size)
            bio_fonts.append(font)
            line_tops_by_page.setdefault(page_no, []).append(float(bbox[1]))

    body_size = max(10.5, min(13.0, _median(bio_sizes, 11.5)))
    metadata_size = max(9.5, min(12.0, _median(metadata_sizes, max(10.0, body_size - 1.0))))
    line_diffs: list[float] = []
    for tops in line_tops_by_page.values():
        unique_tops = sorted(set(round(value, 2) for value in tops))
        for first, second in zip(unique_tops, unique_tops[1:]):
            diff = second - first
            if body_size * 1.05 <= diff <= body_size * 2.2:
                line_diffs.append(diff)
    body_leading = max(body_size * 1.28, min(body_size * 1.55, _median(line_diffs, body_size * 1.34)))
    paragraph_space = body_leading
    dominant_font = max(set(bio_fonts), key=bio_fonts.count) if bio_fonts else "Arial"

    return ParsedPDF(
        raw_text=raw_text,
        artist_name=artist_name,
        location=location,
        biography=biography,
        images=images,
        image_labels=labels,
        works=works,
        body_font_size=round(body_size, 2),
        body_leading=round(body_leading, 2),
        paragraph_space_after=round(paragraph_space, 2),
        metadata_font_size=round(metadata_size, 2),
        body_font_family=_font_family_from_name(dominant_font),
    )

def _pil_to_rgb_tuple(value: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v))) for v in value)


def extract_palette(images: Sequence[Image.Image], count: int = 5) -> list[tuple[int, int, int]]:
    pixels: list[tuple[int, int, int]] = []
    for image in images:
        if image is None:
            continue
        im = image.convert("RGB")
        im.thumbnail((250, 250))
        arr = np.asarray(im).reshape(-1, 3)
        if len(arr) > 5000:
            step = max(1, len(arr) // 5000)
            arr = arr[::step]
        for r, g, b in arr:
            brightness = (int(r) + int(g) + int(b)) / 3
            if 28 < brightness < 235:
                pixels.append((int(r), int(g), int(b)))
    if not pixels:
        return [(91, 120, 104), (174, 98, 93), (188, 158, 93), (116, 98, 135), (232, 226, 214)]
    sample = Image.new("RGB", (len(pixels), 1))
    sample.putdata(pixels)
    quant = sample.quantize(colors=max(count * 3, 12), method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    colors_with_counts = sorted(quant.getcolors() or [], reverse=True)
    chosen: list[tuple[int, int, int]] = []
    for _, idx in colors_with_counts:
        rgb = tuple(palette[idx * 3 : idx * 3 + 3])
        if len(rgb) != 3:
            continue
        if all(sum((a - b) ** 2 for a, b in zip(rgb, existing)) > 900 for existing in chosen):
            chosen.append(_pil_to_rgb_tuple(rgb))
        if len(chosen) >= count:
            break
    while len(chosen) < count:
        defaults = [(91, 120, 104), (174, 98, 93), (188, 158, 93), (116, 98, 135), (232, 226, 214)]
        chosen.append(defaults[len(chosen)])
    return chosen[:count]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _mix(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(a * (1 - amount) + b * amount) for a, b in zip(rgb1, rgb2))


def _luminance(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _saturation(rgb: tuple[int, int, int]) -> float:
    return colorsys.rgb_to_hsv(*(v / 255 for v in rgb))[1]


def recommend_family(palette: Sequence[tuple[int, int, int]], artist_name: str = "") -> str:
    sats = [_saturation(c) for c in palette[:4]]
    lums = [_luminance(c) for c in palette[:4]]
    avg_sat = sum(sats) / max(1, len(sats))
    contrast = max(lums) - min(lums)
    greenish = sum(1 for r, g, b in palette[:4] if g > r * 0.95 and g > b * 0.9)
    pastel = sum(1 for c in palette[:4] if _luminance(c) > 150 and _saturation(c) < 0.45)
    if greenish >= 2:
        return "organico"
    if pastel >= 2:
        return "poetico"
    if avg_sat > 0.48 and contrast > 75:
        return "contemporaneo"
    if avg_sat < 0.25:
        return "minimalista"
    variants = ["geometrico", "organico", "contemporaneo", "poetico", "minimalista"]
    digest = int(hashlib.sha256(artist_name.encode("utf-8")).hexdigest()[:8], 16) if artist_name else 0
    return variants[digest % len(variants)]


def make_theme(family: str, palette: Sequence[tuple[int, int, int]]) -> Theme:
    p = list(palette) + [(91, 120, 104), (174, 98, 93), (188, 158, 93), (116, 98, 135), (232, 226, 214)]
    base = p[0]
    second = p[1]
    third = p[2]
    dark = min(p[:4], key=_luminance)
    light = max(p[:5], key=_luminance)
    if _luminance(dark) > 100:
        dark = _mix(dark, (20, 20, 20), 0.45)
    background = _mix(light, (250, 247, 241), 0.78)
    panel = _mix(background, (255, 255, 255), 0.55)
    muted = _mix(dark, background, 0.45)
    if family == "minimalista":
        background = (250, 249, 246)
        panel = (255, 255, 255)
        second = _mix(base, (255, 255, 255), 0.25)
    elif family == "contemporaneo":
        second = max(p[:4], key=_saturation)
    elif family == "poetico":
        base = _mix(base, (255, 255, 255), 0.18)
        second = _mix(second, (255, 255, 255), 0.28)
    elif family == "geometrico":
        background = _mix(light, (245, 243, 238), 0.82)
    return Theme(
        name=family,
        background=_hex(background),
        text=_hex(dark),
        muted=_hex(muted),
        accent=_hex(base),
        accent2=_hex(second),
        accent3=_hex(third),
        panel=_hex(panel),
    )


def _as_color(value: str, alpha: float = 1.0) -> colors.Color:
    c = colors.HexColor(value)
    return colors.Color(c.red, c.green, c.blue, alpha=alpha)


def _rounded_panel(c: canvas.Canvas, x: float, y: float, w: float, h: float, theme: Theme, radius: float = 8 * mm) -> None:
    c.saveState()
    c.setFillColor(_as_color(theme.panel, 0.90))
    c.setStrokeColor(_as_color(theme.accent, 0.24))
    c.setLineWidth(0.7)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)
    c.restoreState()


def draw_background(c: canvas.Canvas, theme: Theme, family: str, variant: int, page_no: int) -> None:
    c.saveState()
    c.setFillColor(_as_color(theme.background))
    c.rect(0, 0, PAGE_W_PT, PAGE_H_PT, fill=1, stroke=0)

    accent = _as_color(theme.accent)
    accent2 = _as_color(theme.accent2)
    accent3 = _as_color(theme.accent3)
    text = _as_color(theme.text)

    if family == "organico":
        c.setFillColor(_as_color(theme.accent, 0.11))
        c.circle(-18 * mm, PAGE_H_PT - 36 * mm, 58 * mm, fill=1, stroke=0)
        c.setFillColor(_as_color(theme.accent2, 0.09))
        c.circle(PAGE_W_PT + 16 * mm, 22 * mm, 46 * mm, fill=1, stroke=0)
        # Decorative vines remain inside the outer margins and outside the QR/footer zone.
        c.setStrokeColor(_as_color(theme.accent3, 0.46))
        c.setLineWidth(0.9)
        if page_no == 1:
            x0, sign, y0 = 10 * mm, 1, 112 * mm
        else:
            x0, sign, y0 = 207 * mm, -1, 92 * mm
        c.bezier(x0, y0, x0 + sign * 7 * mm, y0 + 20 * mm, x0 + sign * 2 * mm, y0 + 39 * mm, x0 + sign * 8 * mm, y0 + 58 * mm)
        for i in range(4):
            y = y0 + (10 + i * 12) * mm
            x = x0 + sign * (3.5 + (i % 2) * 2.5) * mm
            c.ellipse(x - 3.5 * mm, y - 1.5 * mm, x + 3.5 * mm, y + 1.5 * mm, fill=0, stroke=1)
    elif family == "contemporaneo":
        c.setFillColor(_as_color(theme.accent, 0.94))
        if (variant + page_no) % 2:
            c.rect(0, PAGE_H_PT - 22 * mm, PAGE_W_PT, 22 * mm, fill=1, stroke=0)
            c.setFillColor(_as_color(theme.accent2, 0.18))
            c.rect(PAGE_W_PT - 42 * mm, 0, 42 * mm, PAGE_H_PT, fill=1, stroke=0)
        else:
            c.rect(0, 0, 18 * mm, PAGE_H_PT, fill=1, stroke=0)
            c.setFillColor(_as_color(theme.accent2, 0.18))
            c.rect(0, PAGE_H_PT - 46 * mm, PAGE_W_PT, 46 * mm, fill=1, stroke=0)
        c.setStrokeColor(_as_color(theme.text, 0.16))
        c.setLineWidth(0.45)
        for i in range(1, 8):
            c.line(i * PAGE_W_PT / 8, 0, i * PAGE_W_PT / 8, PAGE_H_PT)
    elif family == "minimalista":
        c.setStrokeColor(_as_color(theme.text, 0.20))
        c.setLineWidth(0.5)
        c.line(16 * mm, PAGE_H_PT - 16 * mm, PAGE_W_PT - 16 * mm, PAGE_H_PT - 16 * mm)
        c.line(16 * mm, 16 * mm, PAGE_W_PT - 16 * mm, 16 * mm)
        c.setFillColor(_as_color(theme.accent, 0.85))
        c.rect((18 if variant % 2 else 177) * mm, PAGE_H_PT - 18 * mm, 15 * mm, 2.2 * mm, fill=1, stroke=0)
    elif family == "poetico":
        for cx, cy, radius, col, alpha in [
            (25 * mm, PAGE_H_PT - 35 * mm, 42 * mm, theme.accent, 0.13),
            (PAGE_W_PT - 20 * mm, PAGE_H_PT - 100 * mm, 38 * mm, theme.accent2, 0.11),
            (PAGE_W_PT - 35 * mm, 28 * mm, 48 * mm, theme.accent3, 0.10),
        ]:
            c.setFillColor(_as_color(col, alpha))
            c.circle(cx, cy, radius, fill=1, stroke=0)
        c.setStrokeColor(_as_color(theme.accent2, 0.45))
        c.setLineWidth(0.8)
        c.bezier(0, 62 * mm, 55 * mm, 88 * mm, 115 * mm, 40 * mm, PAGE_W_PT, 70 * mm)
    elif family == "geometrico":
        c.setFillColor(_as_color(theme.accent, 0.16))
        c.rect(0, PAGE_H_PT - 52 * mm, 68 * mm, 52 * mm, fill=1, stroke=0)
        c.setFillColor(_as_color(theme.accent2, 0.13))
        c.rect(PAGE_W_PT - 46 * mm, 0, 46 * mm, 74 * mm, fill=1, stroke=0)
        c.setStrokeColor(_as_color(theme.text, 0.15))
        c.setLineWidth(0.5)
        step = 18 * mm
        for x in np.arange(12 * mm, PAGE_W_PT, step):
            c.line(float(x), 0, float(x), PAGE_H_PT)
        for y in np.arange(12 * mm, PAGE_H_PT, step):
            c.line(0, float(y), PAGE_W_PT, float(y))
        c.setStrokeColor(_as_color(theme.accent3, 0.65))
        c.setLineWidth(2.0)
        c.line(20 * mm, 34 * mm, 78 * mm, 34 * mm)
    c.restoreState()


def _image_bytes(image: Image.Image, quality: int = 92) -> bytes:
    bio = io.BytesIO()
    image.convert("RGB").save(bio, format="JPEG", quality=quality, optimize=True)
    return bio.getvalue()


def _draw_image_cover(c: canvas.Canvas, image: Image.Image, x: float, y: float, w: float, h: float, contain: bool = False) -> None:
    im = image.convert("RGB")
    if contain:
        fitted = ImageOps.contain(im, (max(1, int(w * 2.2)), max(1, int(h * 2.2))), Image.Resampling.LANCZOS)
        bg = Image.new("RGB", (max(1, int(w * 2.2)), max(1, int(h * 2.2))), (248, 246, 240))
        bg.paste(fitted, ((bg.width - fitted.width) // 2, (bg.height - fitted.height) // 2))
        im = bg
    else:
        im = ImageOps.fit(im, (max(1, int(w * 2.2)), max(1, int(h * 2.2))), Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    c.drawImage(ImageReader(io.BytesIO(_image_bytes(im))), x, y, width=w, height=h, preserveAspectRatio=False, mask="auto")


def _draw_image_frame(c: canvas.Canvas, x: float, y: float, w: float, h: float, theme: Theme, family: str) -> None:
    c.saveState()
    if family in {"poetico", "organico"}:
        c.setStrokeColor(_as_color(theme.accent3, 0.70))
        c.setLineWidth(1.4)
        c.roundRect(x - 2.5 * mm, y - 2.5 * mm, w + 5 * mm, h + 5 * mm, 4 * mm, fill=0, stroke=1)
    elif family == "contemporaneo":
        c.setFillColor(_as_color(theme.accent2, 0.20))
        c.rect(x + 4 * mm, y - 4 * mm, w, h, fill=1, stroke=0)
        c.setStrokeColor(_as_color(theme.text, 0.85))
        c.setLineWidth(1.0)
        c.rect(x, y, w, h, fill=0, stroke=1)
    elif family == "geometrico":
        c.setStrokeColor(_as_color(theme.text, 0.75))
        c.setLineWidth(1.2)
        c.rect(x - 2 * mm, y - 2 * mm, w + 4 * mm, h + 4 * mm, fill=0, stroke=1)
        c.setStrokeColor(_as_color(theme.accent, 0.90))
        c.setLineWidth(2.6)
        c.line(x - 2 * mm, y + h + 2 * mm, x + 22 * mm, y + h + 2 * mm)
    else:
        c.setStrokeColor(_as_color(theme.text, 0.28))
        c.setLineWidth(0.7)
        c.rect(x - 1.8 * mm, y - 1.8 * mm, w + 3.6 * mm, h + 3.6 * mm, fill=0, stroke=1)
    c.restoreState()


def _paragraphs_from_text(text: str, style: ParagraphStyle) -> list:
    text = re.sub(r"[ \t]+", " ", text.strip())
    chunks = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not chunks:
        return []
    story: list = []
    for idx, chunk in enumerate(chunks):
        safe = chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(safe, style))
        if idx < len(chunks) - 1:
            story.append(Spacer(1, 3.2 * mm))
    return story


def _make_styles(
    theme: Theme,
    body_size: float = 11.5,
    body_leading: float | None = None,
    paragraph_space_after: float | None = None,
    metadata_size: float = 10.5,
    body_font_family: str = "sans",
) -> dict[str, ParagraphStyle]:
    body_leading = body_leading or body_size * 1.34
    paragraph_space_after = paragraph_space_after if paragraph_space_after is not None else body_leading
    body_font = "UCSerif" if body_font_family == "serif" else "UCSans"
    body_bold = "UCSerifBold" if body_font_family == "serif" else "UCSansBold"
    return {
        "bio": ParagraphStyle(
            "Biography",
            fontName=body_font,
            fontSize=body_size,
            leading=body_leading,
            textColor=colors.HexColor("#2d2b28"),
            alignment=TA_JUSTIFY,
            allowWidows=1,
            allowOrphans=1,
            splitLongWords=1,
            spaceAfter=paragraph_space_after,
            firstLineIndent=0,
        ),
        "meta": ParagraphStyle(
            "Metadata",
            fontName=body_font,
            fontSize=metadata_size,
            leading=max(metadata_size * 1.30, metadata_size + 2.7),
            textColor=colors.HexColor("#2d2b28"),
            alignment=TA_LEFT,
            allowWidows=1,
            allowOrphans=1,
        ),
        "meta_compact": ParagraphStyle(
            "MetadataCompact",
            fontName=body_font,
            fontSize=max(8.6, metadata_size - 0.8),
            leading=max(11.0, (metadata_size - 0.8) * 1.28),
            textColor=colors.HexColor("#2d2b28"),
            alignment=TA_LEFT,
        ),
        "quote": ParagraphStyle(
            "Quote",
            fontName="UCSerifItalic",
            fontSize=12.2,
            leading=16.2,
            textColor=_as_color(theme.accent3),
            alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "Footer",
            fontName="UCSans",
            fontSize=8.2,
            leading=11.0,
            textColor=_as_color(theme.text),
            alignment=TA_LEFT,
        ),
        "body_bold_font": body_bold,
    }

def _draw_title(c: canvas.Canvas, artist_name: str, location: str, theme: Theme, family: str, variant: int, page_no: int) -> None:
    c.saveState()
    left = 18 * mm
    right = PAGE_W_PT - 18 * mm
    top = PAGE_H_PT - 24 * mm
    if page_no == 1:
        c.setFillColor(_as_color(theme.text))
        c.setFont("UCSerifBold", 25.5 if len(artist_name) < 24 else 21.5)
        if family in {"contemporaneo", "geometrico"} and variant % 2 == 0:
            c.drawString(left, top - 7 * mm, artist_name)
        else:
            c.drawCentredString(PAGE_W_PT / 2, top - 7 * mm, artist_name)
        c.setFont("UCSansBold", 7.8)
        c.setFillColor(_as_color(theme.accent))
        location_text = (location or "ARTISTA").upper().replace(" - ", " · ")
        if family in {"contemporaneo", "geometrico"} and variant % 2 == 0:
            c.drawString(left, top - 16 * mm, location_text)
            c.setStrokeColor(_as_color(theme.accent, 0.85))
            c.setLineWidth(1.6)
            c.line(left, top - 19 * mm, left + 42 * mm, top - 19 * mm)
        else:
            c.drawCentredString(PAGE_W_PT / 2, top - 16 * mm, location_text)
            c.setStrokeColor(_as_color(theme.accent, 0.75))
            c.setLineWidth(1.0)
            c.line(PAGE_W_PT / 2 - 35 * mm, top - 19 * mm, PAGE_W_PT / 2 + 35 * mm, top - 19 * mm)
    else:
        c.setFillColor(_as_color(theme.muted))
        c.setFont("UCSansBold", 7.5)
        c.drawString(left, top - 2 * mm, "UNIVERSO CRIATIVO E ELAS · UM MUNDO DE IMAGENS")
        c.setStrokeColor(_as_color(theme.accent, 0.5))
        c.setLineWidth(0.7)
        c.line(left, top - 5 * mm, right, top - 5 * mm)
    c.restoreState()


def _draw_page_number(c: canvas.Canvas, theme: Theme, page_no: int) -> None:
    c.saveState()
    c.setFillColor(_as_color(theme.muted))
    c.setFont("UCSans", 7)
    c.drawCentredString(PAGE_W_PT / 2, 9 * mm, str(page_no))
    c.restoreState()


def _metadata_html(work: WorkData) -> str:
    fields = [
        ("Autora", work.author),
        ("Título", work.title),
        ("Técnica", work.technique),
        ("Dimensões", work.size),
        ("Ano", work.year),
    ]
    rows = []
    for label, value in fields:
        if value and value.strip():
            safe = value.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows.append(f"<b>{label}:</b> {safe}")
    return "<br/>".join(rows)


def _draw_metadata(c: canvas.Canvas, work: WorkData, x: float, y: float, w: float, h: float, style: ParagraphStyle, theme: Theme) -> None:
    p = Paragraph(_metadata_html(work), style)
    _, ph = p.wrap(w, h)
    p.drawOn(c, x, y + h - ph)
    c.setStrokeColor(_as_color(theme.accent, 0.55))
    c.setLineWidth(0.8)
    c.line(x, y + h + 2.5 * mm, x + min(w, 38 * mm), y + h + 2.5 * mm)


def _draw_qr_footer(c: canvas.Canvas, link: str, label: str, theme: Theme, family: str, page_no: int) -> None:
    if not link.strip():
        return
    box_x, box_y, box_w, box_h = 22 * mm, 16 * mm, PAGE_W_PT - 44 * mm, 23 * mm
    # Opaque footer protects the QR code and text from all decorative background elements.
    c.saveState()
    c.setFillColor(_as_color(theme.panel, 1.0))
    c.setStrokeColor(_as_color(theme.accent, 0.55))
    c.setLineWidth(0.8)
    c.roundRect(box_x, box_y, box_w, box_h, 4 * mm, fill=1, stroke=1)
    c.restoreState()
    qr = qrcode.QRCode(version=None, box_size=8, border=1)
    qr.add_data(link)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=theme.text, back_color=theme.panel).convert("RGB")
    qbio = io.BytesIO(_image_bytes(qr_img, quality=95))
    qsize = 18 * mm
    c.drawImage(ImageReader(qbio), box_x + 2.5 * mm, box_y + 2.5 * mm, qsize, qsize, preserveAspectRatio=True, mask="auto")
    c.setFillColor(_as_color(theme.text))
    c.setFont("UCSerifBold", 9.2)
    c.drawString(box_x + 25 * mm, box_y + 13.5 * mm, "Conheça mais sobre a artista")
    c.setFont("UCSans", 7.8)
    display = label.strip() or link.strip()
    if len(display) > 74:
        display = display[:71] + "..."
    c.drawString(box_x + 25 * mm, box_y + 7.2 * mm, display)
    c.linkURL(link, (box_x, box_y, box_x + box_w, box_y + box_h), relative=0)

def _draw_story_in_box(
    c: canvas.Canvas,
    story: list,
    x: float,
    y: float,
    w: float,
    h: float,
) -> tuple[list, float]:
    """Draw as much of a Platypus story as fits and return the remainder."""
    remaining = list(story)
    cursor = y + h
    bottom = y
    while remaining:
        flowable = remaining[0]
        available_h = cursor - bottom
        if available_h <= 1:
            break
        fw, fh = flowable.wrap(w, available_h)
        space_before = flowable.getSpaceBefore() if cursor < y + h else 0
        space_after = flowable.getSpaceAfter()
        needed = fh + space_before + space_after
        if needed <= available_h + 0.1:
            cursor -= space_before + fh
            flowable.drawOn(c, x, cursor)
            cursor -= space_after
            remaining.pop(0)
            continue
        parts = flowable.split(w, max(0, available_h - space_before))
        if parts:
            first = parts[0]
            fw1, fh1 = first.wrap(w, available_h)
            if fh1 <= available_h + 0.1:
                cursor -= space_before + fh1
                first.drawOn(c, x, cursor)
                cursor -= first.getSpaceAfter()
                remaining = list(parts[1:]) + remaining[1:]
        break
    return remaining, cursor


def _layout_page_one(
    c: canvas.Canvas,
    portrait: Image.Image,
    quote: str,
    story: list,
    theme: Theme,
    family: str,
    variant: int,
    styles: dict[str, ParagraphStyle],
    work_count: int = 2,
) -> list:
    """Page 1 follows a stable editorial structure: portrait first, biography below."""
    # When three works share page 2, page 1 absorbs more biography while preserving font size.
    if work_count == 3:
        image_w, image_h, image_y = 84 * mm, 90 * mm, 155 * mm
        heading_y, story_top = 144 * mm, 136.5 * mm
    else:
        image_w, image_h, image_y = 94 * mm, 106 * mm, 139 * mm
        heading_y, story_top = 128 * mm, 120.5 * mm
    image_x = (PAGE_W_PT - image_w) / 2
    _draw_image_frame(c, image_x, image_y, image_w, image_h, theme, family)
    _draw_image_cover(c, portrait, image_x, image_y, image_w, image_h, contain=False)

    bio_x, bio_w, bio_y = 25 * mm, 160 * mm, 24 * mm
    c.saveState()
    c.setFillColor(_as_color(theme.accent))
    c.setFont("UCSansBold", 8.0)
    c.drawString(bio_x, heading_y, "SOBRE A ARTISTA")
    c.setStrokeColor(_as_color(theme.accent, 0.58))
    c.setLineWidth(0.8)
    c.line(bio_x, heading_y - 2.5 * mm, bio_x + 38 * mm, heading_y - 2.5 * mm)
    c.restoreState()

    if quote.strip():
        safe_quote = quote.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        qp = Paragraph("“" + safe_quote + "”", styles["quote"])
        _, qh = qp.wrap(146 * mm, 11 * mm)
        qp.drawOn(c, 32 * mm, heading_y + 0.5 * mm - qh)
        story_top -= 5 * mm

    bio_h = story_top - bio_y
    remaining, _ = _draw_story_in_box(c, story, bio_x, bio_y, bio_w, bio_h)
    return remaining

def _layout_two_works(
    c: canvas.Canvas,
    works: Sequence[WorkData],
    theme: Theme,
    family: str,
    variant: int,
    top_y: float,
    footer_reserved: float,
    styles: dict[str, ParagraphStyle],
) -> None:
    y_top = min(top_y, PAGE_H_PT - 48 * mm)
    lower_limit = footer_reserved + 7 * mm
    available_h = y_top - lower_limit
    row_gap = 7 * mm
    row_h = (available_h - row_gap) / 2
    image_w, meta_w, horizontal_gap = 92 * mm, 76 * mm, 6 * mm
    image_h = min(70 * mm, row_h - 3 * mm)

    for idx, work in enumerate(works):
        row_top = y_top - idx * (row_h + row_gap)
        row_y = row_top - row_h
        image_y = row_y + (row_h - image_h) / 2
        if (idx + variant) % 2 == 0:
            image_x = 18 * mm
            meta_x = image_x + image_w + horizontal_gap
        else:
            meta_x = 18 * mm
            image_x = meta_x + meta_w + horizontal_gap
        _draw_image_frame(c, image_x, image_y, image_w, image_h, theme, family)
        _draw_image_cover(c, work.image or Image.new("RGB", (800, 600), "white"), image_x, image_y, image_w, image_h, contain=True)
        # The technical description sits close to the corresponding artwork.
        _draw_metadata(c, work, meta_x, image_y + 1 * mm, meta_w, image_h - 2 * mm, styles["meta"], theme)

def _layout_three_works(
    c: canvas.Canvas,
    works: Sequence[WorkData],
    theme: Theme,
    family: str,
    variant: int,
    top_y: float,
    footer_reserved: float,
    styles: dict[str, ParagraphStyle],
) -> None:
    y_top = min(top_y, PAGE_H_PT - 46 * mm)
    lower_limit = footer_reserved + 7 * mm
    available_h = y_top - lower_limit
    row_gap = 5 * mm
    row_h = (available_h - 2 * row_gap) / 3
    image_w, meta_w, horizontal_gap = 73 * mm, 94 * mm, 6 * mm
    image_h = min(48 * mm, row_h - 2 * mm)

    ordered = list(works)
    if variant % 2:
        ordered = [works[1], works[0], works[2]]
    for idx, work in enumerate(ordered):
        row_top = y_top - idx * (row_h + row_gap)
        row_y = row_top - row_h
        image_y = row_y + (row_h - image_h) / 2
        if (idx + variant) % 2 == 0:
            image_x = 18 * mm
            meta_x = image_x + image_w + horizontal_gap
        else:
            meta_x = 18 * mm
            image_x = meta_x + meta_w + horizontal_gap
        _draw_image_frame(c, image_x, image_y, image_w, image_h, theme, family)
        _draw_image_cover(c, work.image or Image.new("RGB", (800, 600), "white"), image_x, image_y, image_w, image_h, contain=True)
        _draw_metadata(c, work, meta_x, image_y, meta_w, image_h, styles["meta_compact"], theme)

def _story_required_height(story: list, width: float, maximum: float) -> float:
    total = 0.0
    for flowable in story:
        _, fh = flowable.wrap(width, maximum)
        total += flowable.getSpaceBefore() + fh + flowable.getSpaceAfter()
        if total >= maximum:
            return maximum
    return total


def _draw_biography_continuation(c: canvas.Canvas, story: list, theme: Theme, family: str, max_height: float) -> tuple[list, float]:
    if not story:
        return story, PAGE_H_PT - 37 * mm
    x, w = 24 * mm, PAGE_W_PT - 48 * mm
    top = PAGE_H_PT - 38 * mm
    content_h = _story_required_height(story, w, max_height - 11 * mm)
    h = min(max_height, max(19 * mm, content_h + 11 * mm))
    y = top - h
    c.saveState()
    c.setFillColor(_as_color(theme.accent))
    c.setFont("UCSansBold", 7.8)
    c.drawString(x, top - 5 * mm, "TRAJETÓRIA")
    c.setStrokeColor(_as_color(theme.accent, 0.52))
    c.setLineWidth(0.7)
    c.line(x, top - 7.5 * mm, x + 32 * mm, top - 7.5 * mm)
    c.restoreState()
    remaining, _ = _draw_story_in_box(c, story, x, y, w, h - 11 * mm)
    return remaining, y

def _draw_pdf(
    artist_name: str,
    location: str,
    biography: str,
    portrait: Image.Image,
    works: Sequence[WorkData],
    quote: str,
    link: str,
    link_label: str,
    family: str,
    variation: int,
    palette: Sequence[tuple[int, int, int]],
    body_font_size: float,
    body_leading: float,
    paragraph_space_after: float,
    metadata_font_size: float,
    body_font_family: str,
) -> tuple[bytes, bool]:
    register_fonts()
    theme = make_theme(family, palette)
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    c.setTitle(f"{artist_name} — Universo Criativo e Elas")
    c.setAuthor("Universo Criativo")
    c.setSubject("Catálogo artístico")
    styles = _make_styles(
        theme,
        body_size=body_font_size,
        body_leading=body_leading,
        paragraph_space_after=paragraph_space_after,
        metadata_size=metadata_font_size,
        body_font_family=body_font_family,
    )

    # PAGE 1
    draw_background(c, theme, family, variation, 1)
    _draw_title(c, artist_name, location, theme, family, variation, 1)
    story = _paragraphs_from_text(biography, styles["bio"])
    story = _layout_page_one(c, portrait, quote, story, theme, family, variation, styles, len(works))
    _draw_page_number(c, theme, 1)
    c.showPage()

    # PAGE 2
    draw_background(c, theme, family, variation + 1, 2)
    _draw_title(c, artist_name, location, theme, family, variation, 2)
    footer_reserved = 45 * mm if link.strip() else 17 * mm

    max_cont_h = 48 * mm if len(works) == 2 else 39 * mm
    top_y = PAGE_H_PT - 37 * mm
    if story:
        story, cont_bottom = _draw_biography_continuation(c, story, theme, family, max_cont_h)
        top_y = cont_bottom - 5 * mm

    if len(works) == 2:
        _layout_two_works(c, works, theme, family, variation, top_y, footer_reserved, styles)
    elif len(works) == 3:
        _layout_three_works(c, works, theme, family, variation, top_y, footer_reserved, styles)
    else:
        raise ValueError("O catálogo deve conter 2 ou 3 obras.")

    _draw_qr_footer(c, link, link_label, theme, family, 2)
    _draw_page_number(c, theme, 2)
    overflow = bool(story)
    c.showPage()
    c.save()
    return output.getvalue(), overflow

def pdf_to_png_pages(pdf_bytes: bytes, dpi: int = PREVIEW_DPI) -> tuple[bytes, bytes]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[bytes] = []
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    for page in doc:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pages.append(pix.tobytes("png"))
    if len(pages) != 2:
        raise RuntimeError("O PDF gerado não possui exatamente duas páginas.")
    return pages[0], pages[1]


def build_catalog(
    artist_name: str,
    location: str,
    biography: str,
    portrait: Image.Image,
    works: list[WorkData],
    quote: str = "",
    link: str = "",
    link_label: str = "",
    family: str = "auto",
    variation: int = 0,
    body_font_size: float = 11.5,
    body_leading: float = 15.0,
    paragraph_space_after: float = 12.0,
    metadata_font_size: float = 10.5,
    body_font_family: str = "sans",
) -> tuple[bytes, bytes, bytes, bool, str, list[tuple[int, int, int]]]:
    ensure_fonts()
    source_images = [portrait] + [w.image for w in works if w.image is not None]
    palette = extract_palette(source_images)
    chosen_family = recommend_family(palette, artist_name) if family == "auto" else family
    pdf_bytes, overflow = _draw_pdf(
        artist_name=artist_name,
        location=location,
        biography=biography,
        portrait=portrait,
        works=works,
        quote=quote,
        link=link,
        link_label=link_label,
        family=chosen_family,
        variation=max(0, int(variation)) % 9,
        palette=palette,
        body_font_size=max(10.5, min(13.0, float(body_font_size))),
        body_leading=max(float(body_font_size) * 1.24, min(float(body_font_size) * 1.58, float(body_leading))),
        paragraph_space_after=max(5.0, min(22.0, float(paragraph_space_after))),
        metadata_font_size=max(9.5, min(12.0, float(metadata_font_size))),
        body_font_family=body_font_family if body_font_family in {"sans", "serif"} else "sans",
    )
    p1, p2 = pdf_to_png_pages(pdf_bytes)
    return pdf_bytes, p1, p2, overflow, chosen_family, palette

