# Universo Criativo — Gerador Editorial de Catálogo (v4)

Aplicativo Streamlit para transformar o PDF de cada artista em duas páginas editoriais padronizadas para o catálogo **Universo Criativo e Elas — Um Mundo de Imagens**.

## Melhorias da versão 5

- página 1 sem cartão vazio ao lado da fotografia: retrato em destaque e biografia abaixo;
- detecção automática do tamanho do corpo, entrelinha, espaçamento entre parágrafos e família tipográfica do PDF enviado;
- preservação dos parágrafos por blocos do documento original;
- texto realmente justificado e pesquisável;
- fichas técnicas posicionadas mais próximas das respectivas obras;
- zonas de segurança para impedir sobreposição entre ornamentos, obras e QR code;
- rodapé do QR code com fundo opaco e link clicável;
- adaptação específica para 2 ou 3 obras, mantendo somente duas páginas;
- cinco famílias visuais: Orgânico, Contemporâneo, Minimalista, Poético e Geométrico;
- prévia e exportação em PDF e PNG.

## Publicação

- arquivo principal: `app.py`
- branch: `main`
- o Streamlit instala as fontes listadas em `packages.txt`


## Ajustes editoriais da versão 5

- remove o título "Trajetória" da página 2;
- continua a biografia diretamente, sem criar uma nova seção;
- preserva os parágrafos detectados no PDF;
- elimina espaçamento duplicado entre parágrafos;
- mantém texto justificado sem dividir palavras entre páginas;
- evita espaço extra quando um parágrafo é dividido entre páginas;
- aproxima a continuação biográfica das obras.
