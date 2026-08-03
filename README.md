# Universo Criativo — Gerador Editorial de Catálogo (v8)

Aplicativo Streamlit para transformar o PDF de cada artista em duas páginas editoriais padronizadas para o catálogo **Universo Criativo e Elas — Um Mundo de Imagens**.

## Versão 8 — revisão transparente dos textos

- o texto original extraído do PDF permanece sempre visível e editável;
- a classificação automática é apenas uma sugestão e nunca apaga ou oculta conteúdo;
- botões permitem copiar a versão revisada para a biografia ou para as descrições das Obras 1, 2 e 3;
- a biografia e cada descrição de obra continuam visíveis e totalmente editáveis antes da geração;
- o botão **Limpar destinos** apaga apenas os campos de uso, preservando o texto original;
- a troca manual do PDF também limpa corretamente os dados da artista anterior;
- permanecem as validações de ano, links, imagens duplicadas, 2 ou 3 obras e o reinício completo da sessão;
- mantém texto justificado, parágrafos preservados, QR code opcional e cinco famílias visuais.

## Publicação

- arquivo principal: `app.py`
- branch: `main`
- o Streamlit instala as fontes listadas em `packages.txt`

## Atualização no GitHub

Substitua no repositório os arquivos `app.py`, `catalog_generator.py`, `requirements.txt`, `packages.txt` e `README.md`. O Streamlit atualizará o mesmo endereço automaticamente.
