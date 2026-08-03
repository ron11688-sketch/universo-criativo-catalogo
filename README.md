# Universo Criativo — Gerador Editorial (versão 12)

Esta versão elimina traços decorativos que poderiam atravessar conteúdo:

- no modelo **Geométrico**, foi removido o traço grosso da faixa inferior;
- no modelo **Poético**, a curva decorativa foi retirada da área de conteúdo;
- grades, círculos, molduras e paletas permanecem preservados;
- biografias, fichas técnicas, obras e QR code ficam em zonas livres de ornamentos sobrepostos;
- mantém a interface limpa, revisão editável, reset completo e exportação em PDF/PNG.

Esta versão mantém a revisão principal mais limpa:

- biografia e descrições das obras aparecem diretamente em campos editáveis;
- o texto bruto e os comandos de reclassificação ficam recolhidos em **Texto original e ajustes avançados (opcional)**;
- os comandos avançados só devem ser usados quando a separação automática precisar ser substituída;
- mantém validações, reset completo, duas ou três obras e exportação em PDF/PNG.


Aplicativo Streamlit para transformar o PDF de cada artista em duas páginas editoriais padronizadas para o catálogo **Universo Criativo e Elas — Um Mundo de Imagens**.

## Versão 10 — revisão transparente dos textos

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


## Novidades da versão 10

- Preserva blocos de texto mesmo quando o nome da artista e a biografia estão no mesmo bloco interno do PDF.
- Reconhece biografias sem o título “Sobre a artista”, usando sinais como idade, formação, trajetória, prêmios e exposições.
- Separa automaticamente biografia e descrições das obras, mantendo tudo visível e editável.
- Exibe os trechos detectados e o destino sugerido para conferência.
- Permite restaurar a separação automática depois de alterações manuais.


## Correção da versão 10

- invalidação automática do cache após atualização;
- compatibilidade com objetos analisados por versões antigas;
- correção do erro `AttributeError: text_segments`.