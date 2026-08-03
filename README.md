# Universo Criativo — Gerador Editorial de Catálogo (v6)

Aplicativo Streamlit para transformar o PDF de cada artista em duas páginas editoriais padronizadas para o catálogo **Universo Criativo e Elas — Um Mundo de Imagens**.

## Melhorias da versão 7

- pergunta obrigatória para classificar o texto extraído como biografia, descrição de obra ou ausência de apresentação;
- quando o texto descreve uma obra, o título passa a ser **Sobre a obra**, evitando apresentá-lo como biografia;
- remove rótulos e cabeçalhos editoriais indevidos da extração do PDF;
- valida o campo **Ano**, aceitando quatro algarismos ou `s/d`;
- bloqueia a geração quando um valor textual é identificado incorretamente como ano;
- reduz a intensidade e o tamanho dos elementos decorativos do estilo Geométrico;
- mantém ornamentos restritos às margens para não competir com as obras;
- corrige o botão **Limpar e iniciar nova artista**, inclusive limpando o arquivo do uploader;
- mantém as melhorias anteriores: texto justificado, parágrafos preservados, 2 ou 3 obras em duas páginas, QR code opcional e cinco famílias visuais.

## Publicação

- arquivo principal: `app.py`
- branch: `main`
- o Streamlit instala as fontes listadas em `packages.txt`

## Atualização no GitHub

Substitua no repositório os arquivos `app.py`, `catalog_generator.py`, `requirements.txt`, `packages.txt` e `README.md`. O Streamlit atualizará o mesmo endereço automaticamente.


## Versão 7 — biografia e descrição das obras

- biografia da artista e descrições das obras são campos independentes;
- textos que parecem descrever uma obra são associados automaticamente à Obra 1;
- cada obra possui campo opcional de descrição/conceito;
- limites editoriais preservam a legibilidade em layouts com 2 ou 3 obras;
- a geração exige uma biografia da artista;
- o botão de reinício continua removendo o PDF e todos os campos da sessão.
