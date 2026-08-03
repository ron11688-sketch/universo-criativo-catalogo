from __future__ import annotations

import hashlib
from urllib.parse import urlparse

import streamlit as st
from PIL import Image

from catalog_generator import (
    ParsedPDF,
    WorkData,
    build_catalog,
    clean_title,
    extract_palette,
    family_label,
    normalize_size,
    parse_pdf,
    recommend_family,
    slugify,
)

st.set_page_config(page_title="Universo Criativo — Gerador Editorial", page_icon="🎨", layout="wide")

st.markdown(
    """
<style>
    .main .block-container {max-width: 1220px; padding-top: 1.6rem; padding-bottom: 4rem;}
    h1, h2, h3 {color:#3d4a43; letter-spacing:-.02em;}
    .uc-hero {background:linear-gradient(135deg,#fbf8f0,#eee8dd);border:1px solid #d7c7a3;border-radius:24px;padding:25px 30px;margin-bottom:22px;box-shadow:0 12px 30px rgba(46,44,39,.06)}
    .uc-hero p {margin:.3rem 0;color:#5e5a54;}
    .uc-badge {display:inline-block;padding:5px 11px;border-radius:999px;background:#7c668d;color:white;font-size:.80rem;margin-bottom:8px;}
    .small-note {color:#736d64;font-size:.92rem;}
    .palette {display:flex;gap:7px;margin:.5rem 0 1rem 0;}
    .swatch {height:32px;flex:1;border-radius:8px;border:1px solid rgba(0,0,0,.12);}
    div[data-testid="stDownloadButton"] button {background:#3d6d57;color:white;border-radius:12px;border:0;}
    div[data-testid="stButton"] button[kind="primary"] {background:#a64d3e;border-color:#a64d3e;border-radius:12px;}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="uc-hero">
  <span class="uc-badge">VERSÃO EDITORIAL</span>
  <h1>🎨 Gerador de catálogo — Universo Criativo</h1>
  <p>Crie duas páginas sofisticadas e coerentes para cada artista, preservando texto, fotografia e obras.</p>
  <p class="small-note">O sistema mantém a lógica editorial do e-book, mas varia paleta, ornamentos e composição para que cada artista tenha identidade própria.</p>
</div>
""",
    unsafe_allow_html=True,
)


def reset_app() -> None:
    st.session_state.clear()
    st.cache_data.clear()
    st.rerun()


@st.cache_data(show_spinner=False)
def cached_parse(data: bytes) -> ParsedPDF:
    return parse_pdf(data)


def valid_url(value: str) -> bool:
    try:
        parsed_url = urlparse(value)
        return parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)
    except Exception:
        return False


uploaded = st.file_uploader("1. Envie o PDF da artista", type=["pdf"])
if not uploaded:
    st.info("Envie um PDF para iniciar.")
    st.caption("Privacidade: o arquivo é processado apenas durante esta sessão e não é enviado a APIs externas.")
    st.stop()

file_hash = hashlib.sha256(uploaded.getvalue()).hexdigest()
if st.session_state.get("active_file_hash") != file_hash:
    st.session_state["active_file_hash"] = file_hash
    st.session_state["variation"] = 0
    st.session_state.pop("catalog_outputs", None)

with st.spinner("Analisando texto e imagens do PDF..."):
    parsed = cached_parse(uploaded.getvalue())

if not parsed.images:
    st.error("Não encontrei imagens incorporadas no PDF. Verifique se a fotografia e as obras estão dentro do arquivo.")
    st.stop()

st.success(f"Foram encontradas {len(parsed.images)} imagens no PDF.")

st.subheader("2. Confira a artista e a biografia")
col_a, col_b = st.columns([1, 1.25])
with col_a:
    artist_name = st.text_input("Nome da artista", value=parsed.artist_name)
    location = st.text_input("Estado / país", value=parsed.location)
    quote = st.text_input("Frase de destaque (opcional)", placeholder="Ex.: A arte é o meu jeito de agradecer.")
with col_b:
    biography = st.text_area("Biografia", value=parsed.biography, height=350)
    st.caption(f"{len(biography):,} caracteres. O texto será justificado e dividido automaticamente entre as páginas 1 e 2.")
    st.caption(
        f"Configuração detectada no PDF: corpo {parsed.body_font_size:g} pt, "
        f"entrelinha {parsed.body_leading:g} pt e espaçamento entre parágrafos {parsed.paragraph_space_after:g} pt."
    )

preserve_source_typography = st.checkbox(
    "Preservar o tamanho da fonte e a configuração dos parágrafos do PDF enviado",
    value=True,
    help="Mantém tamanho do corpo, entrelinha, espaçamento entre parágrafos e família tipográfica detectados no documento original.",
)
if preserve_source_typography:
    body_font_size = parsed.body_font_size
    body_leading = parsed.body_leading
    paragraph_space_after = parsed.paragraph_space_after
    metadata_font_size = parsed.metadata_font_size
    body_font_family = parsed.body_font_family
else:
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        body_font_size = st.number_input("Tamanho do texto (pt)", 10.5, 13.0, 11.5, 0.25)
    with tc2:
        body_leading = st.number_input("Entrelinha (pt)", 13.0, 20.0, 15.0, 0.25)
    with tc3:
        paragraph_space_after = st.number_input("Espaço entre parágrafos (pt)", 5.0, 22.0, 12.0, 0.5)
    metadata_font_size = max(9.5, body_font_size - 1.0)
    body_font_family = "sans"

st.subheader("3. Identifique as imagens")
st.write("Confira as miniaturas e selecione qual é o retrato e quais são as obras.")
thumb_cols = st.columns(min(4, len(parsed.images)))
for idx, image in enumerate(parsed.images):
    with thumb_cols[idx % len(thumb_cols)]:
        st.image(image, caption=parsed.image_labels[idx], use_container_width=True)

image_options = {label: i for i, label in enumerate(parsed.image_labels)}
portrait_label = st.selectbox("Fotografia da artista", parsed.image_labels, index=0)
portrait_index = image_options[portrait_label]
number_of_works = st.radio("Quantidade de obras", [2, 3], horizontal=True, index=0)
if len(parsed.images) < number_of_works + 1:
    st.warning("O PDF possui menos imagens do que o necessário. Envie as imagens ausentes nos campos abaixo.")

st.subheader("4. Confira as fichas técnicas")
standardize = st.checkbox(
    "Padronizar títulos finais e dimensões",
    value=True,
    help="Remove hífen solto no fim do título e padroniza dimensões como 40 × 40 cm.",
)

work_entries: list[WorkData] = []
work_source_ids: list[str] = []
for i in range(number_of_works):
    extracted = parsed.works[i] if i < len(parsed.works) else WorkData(author=artist_name)
    with st.expander(f"Obra {i + 1}", expanded=True):
        left, right = st.columns([1, 1.15])
        with left:
            default_index = min(i + 1, len(parsed.images) - 1)
            if default_index == portrait_index and len(parsed.images) > 1:
                default_index = (default_index + 1) % len(parsed.images)
            image_choice = st.selectbox(
                f"Imagem da obra {i + 1}", parsed.image_labels, index=default_index, key=f"work_image_{i}"
            )
            extra_file = st.file_uploader(
                f"Ou envie outra imagem para a obra {i + 1} (opcional)",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"extra_work_{i}",
            )
            if extra_file:
                work_image = Image.open(extra_file).convert("RGB")
                source_id = f"extra:{i}:{extra_file.name}:{extra_file.size}"
            else:
                selected_index = image_options[image_choice]
                work_image = parsed.images[selected_index]
                source_id = f"pdf:{selected_index}"
            st.image(work_image, caption=f"Prévia da obra {i + 1}", use_container_width=True)
        with right:
            author = st.text_input("Autora", value=extracted.author or artist_name, key=f"author_{i}")
            title = st.text_input("Título", value=extracted.title, key=f"title_{i}")
            technique = st.text_input("Técnica", value=extracted.technique, key=f"tech_{i}")
            size = st.text_input("Tamanho", value=extracted.size, key=f"size_{i}")
            year = st.text_input("Ano", value=extracted.year, key=f"year_{i}")
        if standardize:
            title = clean_title(title)
            size = normalize_size(size)
        work_entries.append(WorkData(author=author, title=title, technique=technique, size=size, year=year, image=work_image))
        work_source_ids.append(source_id)

st.subheader("5. Link da artista")
has_link = st.checkbox("A artista possui Instagram, site, portfólio ou outro link para divulgação?")
link = ""
link_label = ""
if has_link:
    lc1, lc2 = st.columns(2)
    with lc1:
        link = st.text_input("Cole o link completo", placeholder="https://instagram.com/nome ou https://site.com")
    with lc2:
        link_label = st.text_input("Como o link deve aparecer", placeholder="@nomeartista ou nome do site")
    st.caption("O app incluirá um QR code e uma área clicável no PDF.")

st.subheader("6. Direção visual")
source_images = [parsed.images[portrait_index]] + [w.image for w in work_entries if w.image is not None]
palette = extract_palette(source_images)
recommended = recommend_family(palette, artist_name)

family_options = {
    "Automática — recomendada pelo app": "auto",
    "Orgânico": "organico",
    "Contemporâneo": "contemporaneo",
    "Minimalista": "minimalista",
    "Poético": "poetico",
    "Geométrico": "geometrico",
}
selected_family_label = st.selectbox(
    "Família editorial",
    list(family_options.keys()),
    index=0,
    help="No modo automático, o app escolhe a família visual a partir das cores das obras e do retrato.",
)
selected_family = family_options[selected_family_label]
st.caption(f"Recomendação atual: **{family_label(recommended)}**")

swatches = "".join(f'<div class="swatch" style="background:rgb({r},{g},{b})"></div>' for r, g, b in palette)
st.markdown(f'<div class="palette">{swatches}</div>', unsafe_allow_html=True)

vc1, vc2 = st.columns([1, 2])
with vc1:
    if st.button("Gerar outra proposta visual", use_container_width=True):
        st.session_state["variation"] = int(st.session_state.get("variation", 0)) + 1
        st.session_state.pop("catalog_outputs", None)
        st.rerun()
with vc2:
    st.caption(
        f"Proposta visual nº {int(st.session_state.get('variation', 0)) + 1}. "
        "A estrutura editorial permanece consistente, mas a composição, o destaque das obras e os ornamentos variam."
    )

st.subheader("7. Gere, confira e baixe")
if st.button("Gerar prévia editorial", type="primary", use_container_width=True):
    errors: list[str] = []
    if not artist_name.strip():
        errors.append("Preencha o nome da artista.")
    if not biography.strip():
        errors.append("Preencha a biografia da artista.")
    if any(not w.title.strip() for w in work_entries):
        errors.append("Preencha o título de todas as obras.")
    if any(not w.image for w in work_entries):
        errors.append("Selecione uma imagem para cada obra.")
    if len(set(work_source_ids)) != len(work_source_ids):
        errors.append("A mesma imagem foi selecionada para mais de uma obra.")
    if f"pdf:{portrait_index}" in work_source_ids:
        errors.append("A fotografia da artista também foi selecionada como obra. Escolha imagens diferentes.")
    if has_link:
        if not valid_url(link.strip()):
            errors.append("Informe um link completo e válido, iniciado por https://")
        if not link_label.strip() or link_label.strip().lower() in {"@artista", "artista", "nome do site"}:
            errors.append("Informe como o link deve aparecer, usando o perfil ou nome real da artista.")

    if errors:
        for message in errors:
            st.error(message)
    else:
        try:
            with st.spinner("Compondo o catálogo editorial..."):
                pdf_bytes, p1_bytes, p2_bytes, overflow, chosen_family, final_palette = build_catalog(
                    artist_name=artist_name.strip(),
                    location=location.strip(),
                    biography=biography.strip(),
                    portrait=parsed.images[portrait_index],
                    works=work_entries,
                    quote=quote.strip(),
                    link=link.strip() if has_link else "",
                    link_label=link_label.strip() if has_link else "",
                    family=selected_family,
                    variation=int(st.session_state.get("variation", 0)),
                    body_font_size=body_font_size,
                    body_leading=body_leading,
                    paragraph_space_after=paragraph_space_after,
                    metadata_font_size=metadata_font_size,
                    body_font_family=body_font_family,
                )
            st.session_state["catalog_outputs"] = (
                pdf_bytes, p1_bytes, p2_bytes, overflow, artist_name, chosen_family, final_palette
            )
        except RuntimeError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Não foi possível gerar o catálogo: {exc}")

if "catalog_outputs" in st.session_state:
    pdf_bytes, p1_bytes, p2_bytes, overflow, output_artist, chosen_family, final_palette = st.session_state["catalog_outputs"]
    st.success(f"Proposta gerada na família **{family_label(chosen_family)}**.")
    if overflow:
        st.warning(
            "A biografia ultrapassou o espaço editorial das duas páginas. Resuma o texto antes da versão final; a fonte não será reduzida automaticamente."
        )
    st.markdown("### Prévia")
    st.caption("Revise nome, texto, imagens e fichas. O PDF preserva texto pesquisável, justificação e link clicável.")
    pcol1, pcol2 = st.columns(2)
    with pcol1:
        st.image(p1_bytes, caption="Página 1", use_container_width=True)
    with pcol2:
        st.image(p2_bytes, caption="Página 2", use_container_width=True)

    base = slugify(output_artist)
    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button("Baixar PDF completo", pdf_bytes, f"{base}-catalogo.pdf", "application/pdf", use_container_width=True)
    with d2:
        st.download_button("Baixar página 1 (PNG)", p1_bytes, f"{base}-pagina-1.png", "image/png", use_container_width=True)
    with d3:
        st.download_button("Baixar página 2 (PNG)", p2_bytes, f"{base}-pagina-2.png", "image/png", use_container_width=True)

    if st.button("Limpar e iniciar nova artista", use_container_width=True):
        reset_app()
