from __future__ import annotations

import io

import streamlit as st
from PIL import Image

from catalog_generator import ParsedPDF, WorkData, build_catalog, parse_pdf, slugify

st.set_page_config(
    page_title="Universo Criativo — Gerador de Catálogo",
    page_icon="🎨",
    layout="wide",
)

st.markdown(
    """
<style>
    .main .block-container {max-width: 1180px; padding-top: 2rem;}
    h1, h2, h3 {color: #285e42;}
    .uc-card {background:#faf7ef;border:1px solid #d9c69a;border-radius:16px;padding:18px;margin-bottom:14px;}
    .small-note {color:#6f6a62;font-size:.92rem;}
    div[data-testid="stDownloadButton"] button {background:#285e42;color:white;border-radius:12px;}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🎨 Gerador de páginas — Universo Criativo")
st.write(
    "Envie o PDF da artista, confira os dados extraídos e gere automaticamente duas páginas padronizadas para o e-book."
)
st.caption("O app aceita uma fotografia da artista, biografia e 2 ou 3 obras com ficha técnica.")

uploaded = st.file_uploader("1. Envie o PDF da artista", type=["pdf"])


@st.cache_data(show_spinner=False)
def cached_parse(data: bytes) -> ParsedPDF:
    return parse_pdf(data)


if not uploaded:
    st.info("Envie um PDF para iniciar.")
    st.stop()

with st.spinner("Analisando texto e imagens do PDF..."):
    parsed = cached_parse(uploaded.getvalue())

if not parsed.images:
    st.error("Não encontrei imagens incorporadas no PDF. Verifique se a fotografia e as obras estão realmente dentro do arquivo.")
    st.stop()

st.success(f"Foram encontradas {len(parsed.images)} imagens no PDF.")

st.subheader("2. Confira a artista e a biografia")
col_a, col_b = st.columns([1.2, 1])
with col_a:
    artist_name = st.text_input("Nome da artista", value=parsed.artist_name)
    location = st.text_input("Estado / país", value=parsed.location)
    quote = st.text_input(
        "Frase de destaque (opcional)",
        placeholder="Ex.: A arte é o meu jeito de agradecer.",
    )
with col_b:
    biography = st.text_area("Biografia", value=parsed.biography, height=230)

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
    st.warning("O PDF possui menos imagens do que o necessário. Você poderá enviar imagens adicionais abaixo.")

st.subheader("4. Confira as fichas técnicas")
work_entries: list[WorkData] = []
used_defaults: set[int] = {portrait_index}

for i in range(number_of_works):
    extracted = parsed.works[i] if i < len(parsed.works) else WorkData(author=artist_name)
    with st.expander(f"Obra {i + 1}", expanded=True):
        left, right = st.columns([1, 1.15])
        with left:
            default_index = min(i + 1, len(parsed.images) - 1)
            if default_index == portrait_index and len(parsed.images) > 1:
                default_index = (default_index + 1) % len(parsed.images)
            image_choice = st.selectbox(
                f"Imagem da obra {i + 1}",
                parsed.image_labels,
                index=default_index,
                key=f"work_image_{i}",
            )
            extra_file = st.file_uploader(
                f"Ou envie outra imagem para a obra {i + 1} (opcional)",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"extra_work_{i}",
            )
            if extra_file:
                work_image = Image.open(extra_file).convert("RGB")
            else:
                work_image = parsed.images[image_options[image_choice]]
        with right:
            author = st.text_input("Autora", value=extracted.author or artist_name, key=f"author_{i}")
            title = st.text_input("Título", value=extracted.title, key=f"title_{i}")
            technique = st.text_input("Técnica", value=extracted.technique, key=f"tech_{i}")
            size = st.text_input("Tamanho", value=extracted.size, key=f"size_{i}")
            year = st.text_input("Ano", value=extracted.year, key=f"year_{i}")
        work_entries.append(
            WorkData(
                author=author,
                title=title,
                technique=technique,
                size=size,
                year=year,
                image=work_image,
            )
        )

st.subheader("5. Link da artista")
has_link = st.checkbox("A artista possui Instagram, site, portfólio ou outro link para divulgação?")
link = ""
link_label = ""
if has_link:
    lc1, lc2 = st.columns(2)
    with lc1:
        link = st.text_input("Cole o link completo", placeholder="https://instagram.com/... ou https://...")
    with lc2:
        link_label = st.text_input("Como o link deve aparecer", placeholder="@artista ou nome do site")
    st.caption("O app incluirá um QR code e deixará o link clicável no PDF.")

st.subheader("6. Gere e baixe")
if st.button("Gerar as duas páginas", type="primary", use_container_width=True):
    if not artist_name.strip() or not biography.strip():
        st.error("Preencha o nome e a biografia da artista.")
    elif has_link and link and not link.lower().startswith(("http://", "https://")):
        st.error("O link precisa começar com http:// ou https://")
    elif any(not w.title.strip() for w in work_entries):
        st.error("Preencha o título de todas as obras.")
    else:
        with st.spinner("Montando o catálogo..."):
            pdf_bytes, p1_bytes, p2_bytes, overflow = build_catalog(
                artist_name=artist_name.strip(),
                location=location.strip(),
                biography=biography.strip(),
                portrait=parsed.images[portrait_index],
                works=work_entries,
                quote=quote.strip(),
                link=link.strip(),
                link_label=link_label.strip(),
            )
        st.session_state["catalog_outputs"] = (pdf_bytes, p1_bytes, p2_bytes, overflow, artist_name)

if "catalog_outputs" in st.session_state:
    pdf_bytes, p1_bytes, p2_bytes, overflow, output_artist = st.session_state["catalog_outputs"]
    if overflow:
        st.warning(
            "A biografia excedeu o espaço disponível nas duas páginas. Revise e reduza o texto antes da versão final para evitar corte."
        )
    st.markdown("### Prévia")
    pcol1, pcol2 = st.columns(2)
    with pcol1:
        st.image(p1_bytes, caption="Página 1", use_container_width=True)
    with pcol2:
        st.image(p2_bytes, caption="Página 2", use_container_width=True)

    base = slugify(output_artist)
    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            "Baixar PDF completo",
            data=pdf_bytes,
            file_name=f"{base}-catalogo.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "Baixar página 1 (PNG)",
            data=p1_bytes,
            file_name=f"{base}-pagina-1.png",
            mime="image/png",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            "Baixar página 2 (PNG)",
            data=p2_bytes,
            file_name=f"{base}-pagina-2.png",
            mime="image/png",
            use_container_width=True,
        )
