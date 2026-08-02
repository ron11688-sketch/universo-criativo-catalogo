# Universo Criativo — Gerador de Catálogo

Aplicativo em Streamlit para transformar o PDF de uma artista em duas páginas padronizadas de e-book:

- página 1: nome, localidade, fotografia, frase opcional e biografia;
- página 2: continuação da biografia, 2 ou 3 obras e fichas técnicas;
- link opcional da artista com QR code e link clicável no PDF;
- exportação em PDF e PNG.

## Publicar no Streamlit Community Cloud

1. Envie todos os arquivos deste projeto para o repositório GitHub.
2. Acesse `https://share.streamlit.io` e entre com a conta GitHub.
3. Clique em **Create app**.
4. Escolha o repositório `universo-criativo-catalogo`.
5. Em **Main file path**, informe `app.py`.
6. Clique em **Deploy**.

## Executar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Observação

O app não usa API externa nem envia os PDFs a serviços de terceiros. O processamento ocorre durante a sessão do Streamlit.
