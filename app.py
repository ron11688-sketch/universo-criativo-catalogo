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
    valid_year,
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
  <span class="uc-badge">VERSÃO EDITORIAL 8</span>
  <h1>🎨 Gerador de catálogo — Universo Criativo</h1>
  <p>Crie duas páginas sofisticadas e coerentes para cada artista, preservando texto, fotografia e obras.</p>
  <p class="small-note">O sistema mantém a lógica editorial do e-book, mas varia paleta, ornamentos e composição para que cada artista tenha identidade própria.</p>
</div>
""",
    unsafe_allow_html=True,
)


if "reset_nonce" not in st.session_state:
    st.session_state["reset_nonce"] = 0


def reset_app() -> None:
    """Start a truly clean artist session, including a cleared PDF uploader."""
    next_nonce = int(st.session_state.get("reset_nonce", 0)) + 1
    st.session_state.clear()
    st.session_state["reset_nonce"] = next_nonce
    st.cache_data.clear()
    st.rerun()


def infer_text_kind(text: str) -> str:
    """Suggest whether extracted copy is an artist bio or an artwork description."""
    lowered = (text or "").lower()
    description_terms = (
        "esta obra", "a obra", "bordado", "sobre folha", "sobre tela", "escultura",
        "técnica", "tecnica", "fios", "arte têxtil", "arte textil", "dimensões", "dimensoes",
    )
    biography_terms = (
        "trajetória", "trajetoria", "artista", "nasceu", "formação", "formacao", "carreira",
        "autodidata", "exposição", "exposicao", "pesquisa", "vive", "mora", "sua jornada",
    )
    description_score = sum(term in lowered for term in description_terms)
    biography_score = sum(term in lowered for term in biography_terms)
    if len(text or "") < 900 and description_score >= 2 and description_score > biography_score:
        return "Descrição de uma obra"
    return "Biografia/apresentação da artista"


@st.cache_data(show_spinner=False)
def cached_parse(data: bytes) -> ParsedPDF:
    return parse_pdf(data)


def valid_url(value: str) -> bool:
    try:
        parsed_url = urlparse(value)
        return parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)
    except Exception:
        return False


uploader_key = f"source_pdf_{int(st.session_state.get('reset_nonce', 0))}"
uploaded = st.file_uploader("1. Envie o PDF da artista", type=["pdf"], key=uploader_key)
if not uploaded:
    st.info("Envie um PDF para iniciar.")
    st.caption("Privacidade: o arquivo é processado apenas durante esta sessão e não é enviado a APIs externas.")
    st.stop()

file_hash = hashlib.sha256(uploaded.getvalue()).hexdigest()
if st.session_state.get("active_file_hash") != file_hash:
    # A troca manual do PDF também deve iniciar um formulário limpo. Mantemos
    # apenas o uploader atual e o contador usado pelo botão de reinício.
    preserved = {"reset_nonce", uploader_key}
    for state_key in list(st.session_state.keys()):
        if state_key not in preserved:
            del st.session_state[state_key]
    st.session_state["active_file_hash"] = file_hash
    st.session_state["variation"] = 0

with st.spinner("Analisando texto e imagens do PDF..."):
    parsed = cached_parse(uploaded.getvalue())

if not parsed.images:
    st.error("Não encontrei imagens incorporadas no PDF. Verifique se a fotografia e as obras estão dentro do arquivo.")
    st.stop()

st.success(f"Foram encontradas {len(parsed.images)} imagens no PDF.")

st.subheader("2. Confira os textos extraídos e a biografia")

# O texto original nunca é ocultado. A classificação automática apenas sugere
# um destino inicial; a pessoa responsável pode revisar o conteúdo e copiá-lo
# para a biografia ou para qualquer obra sem perder o original.
extracted_kind = infer_text_kind(parsed.biography)
if st.session_state.get("text_defaults_hash") != file_hash:
    st.session_state["text_defaults_hash"] = file_hash
    st.session_state["source_text_editor"] = parsed.biography
    st.session_state["artist_biography"] = (
        parsed.biography if extracted_kind == "Biografia/apresentação da artista" else ""
    )
    for description_index in range(3):
        st.session_state[f"work_description_{description_index}"] = ""
    if extracted_kind == "Descrição de uma obra":
        st.session_state["work_description_0"] = parsed.biography
        st.session_state["text_assignment_status"] = (
            "O texto foi sugerido para a descrição da Obra 1. "
            "O original continua visível e pode ser redistribuído."
        )
    else:
        st.session_state["text_assignment_status"] = (
            "O texto foi sugerido para a biografia da artista. "
            "Revise-o antes de gerar o catálogo."
        )
    st.session_state["artist_name_field"] = parsed.artist_name
    st.session_state["location_field"] = parsed.location
    st.session_state["quote_field"] = ""

st.markdown("#### Texto original extraído do PDF")
source_text = st.text_area(
    "Revise o texto original antes de distribuí-lo",
    height=220,
    key="source_text_editor",
    placeholder="O texto extraído do PDF aparecerá aqui.",
    help=(
        "Este campo preserva o conteúdo extraído. Editá-lo não altera automaticamente "
        "a biografia nem as descrições; use os botões abaixo para copiar a versão revisada."
    ),
)

if source_text.strip():
    st.caption(f"Sugestão automática: **{extracted_kind}**. A decisão final é sua.")
    assignment_cols = st.columns([1.25, 1, 1, 1, 1.1])
    with assignment_cols[0]:
        if st.button("Copiar para a biografia", use_container_width=True):
            st.session_state["artist_biography"] = st.session_state.get("source_text_editor", "")
            st.session_state["text_assignment_status"] = "Texto copiado para a biografia da artista."
            st.session_state.pop("catalog_outputs", None)
            st.rerun()
    for work_number in range(1, 4):
        with assignment_cols[work_number]:
            if st.button(f"Copiar para a Obra {work_number}", use_container_width=True):
                st.session_state[f"work_description_{work_number - 1}"] = st.session_state.get(
                    "source_text_editor", ""
                )
                st.session_state["text_assignment_status"] = (
                    f"Texto copiado para a descrição da Obra {work_number}."
                )
                st.session_state.pop("catalog_outputs", None)
                st.rerun()
    with assignment_cols[4]:
        if st.button("Limpar destinos", use_container_width=True):
            st.session_state["artist_biography"] = ""
            for description_index in range(3):
                st.session_state[f"work_description_{description_index}"] = ""
            st.session_state["text_assignment_status"] = (
                "Biografia e descrições foram limpas; o texto original foi preservado."
            )
            st.session_state.pop("catalog_outputs", None)
            st.rerun()
else:
    st.warning("Não foi identificado texto de apresentação no PDF. Preencha a biografia manualmente.")

if st.session_state.get("text_assignment_status"):
    st.info(st.session_state["text_assignment_status"])

col_a, col_b = st.columns([1, 1.25])
with col_a:
    artist_name = st.text_input("Nome da artista", key="artist_name_field")
    location = st.text_input("Estado / país", key="location_field")
    quote = st.text_input(
        "Frase de destaque (opcional)",
        placeholder="Ex.: A arte é o meu jeito de agradecer.",
        key="quote_field",
    )
with col_b:
    biography = st.text_area(
        "Biografia / apresentação da artista",
        height=350,
        placeholder="Cole aqui a trajetória, formação, pesquisa artística ou apresentação da artista.",
        key="artist_biography",
    )
    st.caption(
        f"{len(biography):,} caracteres. O texto será justificado e dividido automaticamente entre as páginas 1 e 2."
    )
    st.caption(
        f"Configuração detectada no PDF: corpo {parsed.body_font_size:g} pt, "
        f"entrelinha {parsed.body_leading:g} pt e espaçamento entre parágrafos {parsed.paragraph_space_after:g} pt."
    )

section_title = "SOBRE A ARTISTA"

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
invalid_year_entries: list[int] = []
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
            if year.strip() and not valid_year(year):
                invalid_year_entries.append(i + 1)
                st.error("O ano deve conter quatro algarismos (ex.: 2026) ou ‘s/d’ quando não houver data.")
            description_key = f"work_description_{i}"
            if description_key not in st.session_state:
                st.session_state[description_key] = getattr(extracted, "description", "") or ""
            description = st.text_area(
                "Descrição ou conceito da obra (opcional)",
                height=140,
                key=description_key,
                placeholder="Breve descrição, conceito, materiais ou contexto da obra.",
                help=(
                    "O conteúdo associado pelo app permanece totalmente editável. "
                    "Use o texto original da etapa 2 para copiar outra versão quando necessário."
                ),
            )
            description_limit = 420 if number_of_works == 2 else 240
            st.caption(f"{len(description):,}/{description_limit} caracteres recomendados para este layout.")
            if description.strip():
                st.caption("Texto visível e editável antes da geração do catálogo.")
            if len(description) > description_limit:
                st.warning(
                    f"Para manter duas páginas com boa legibilidade, resuma esta descrição para até {description_limit} caracteres."
                )
        if standardize:
            title = clean_title(title)
            size = normalize_size(size)
        work_entries.append(WorkData(author=author, title=title, technique=technique, size=size, year=year, description=description, image=work_image))
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
        errors.append("Preencha a biografia ou apresentação da artista.")
    description_limit = 420 if number_of_works == 2 else 240
    overlong_descriptions = [i + 1 for i, work in enumerate(work_entries) if len((work.description or "").strip()) > description_limit]
    if overlong_descriptions:
        errors.append(
            "Resuma a descrição das obras " + ", ".join(map(str, overlong_descriptions)) +
            f" para até {description_limit} caracteres."
        )
    if invalid_year_entries:
        numbers = ", ".join(str(number) for number in invalid_year_entries)
        errors.append(f"Revise o campo Ano nas obras: {numbers}.")
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
                    section_title="SOBRE A ARTISTA",
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
            "O texto de apresentação ultrapassou o espaço editorial das duas páginas. Resuma-o antes da versão final; a fonte não será reduzida automaticamente."
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

    if st.button(
        "Limpar e iniciar nova artista",
        use_container_width=True,
        key=f"reset_artist_{int(st.session_state.get('reset_nonce', 0))}",
    ):
        reset_app()
