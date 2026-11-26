# Montador — desenho do app

Decisões tomadas por JP em 20/11/2026. Este arquivo é o guia da construção: qualquer mudança de regra passa por aqui.

## O que é

App desktop (Mac e Windows) que monta as sequências das videoaulas do NPD (PUC Minas / IEC) e entrega um XML para abrir no Premiere 25. Substitui integralmente o Fluxo NPD (`video_editor_assist`).

Segue o modelo do Revisor de Vídeos:
- repositório público no GitHub (`jprodriguesgm/montador`), aprovado pela TI;
- empacotado, sem pedir admin nem Python instalado;
- builds pelo GitHub Actions; versões de teste podem sair separadas por sistema, a versão oficial sai sempre com Mac e Windows juntos;
- as outras unidades baixam as atualizações do GitHub — pelo botão **Atualizar** do próprio app (baixa a release, troca a si mesmo e reabre; Mac em `~/Applications` quando não dá para escrever na pasta atual; Windows troca ao fechar) ou **Baixar** (só o `.zip`, troca à mão).

Visual no estilo do app Subir no Drive: cinza escuro, cantos arredondados, contorno branco leve e sombra azul bem clara.
Ícone: original, na linha "montador de móveis" (parafusadeira montando peças que lembram quadros de filme/timeline).

## Entradas

1. **Pasta do dia.** O app acha os vídeos (Footage), as transcrições, o `SRT unico` e a `tabela` gerados pelo `transcribe`.
   - Transcrição master do Premiere (vídeos colados numa sequência): dividida pela duração de cada vídeo (reconhecida sozinha, ou com a caixa "Transcrição feita no Premiere") ou, mais exato, pelo **XML da sequência** (Final Cut Pro XML), que dá o início real de cada vídeo.
   - Duração do vídeo: cabeçalho do MP4 → fragmentos do MP4 (o OBS grava fragmentado) → `afinfo` (Mac) → `ffprobe`. Faltou mesmo assim: o app diz qual vídeo.
2. **Cartão.** ID do cartão do Trello (pela API, chave configurada por máquina) **ou** o TXT com os mesmos campos na pasta `Originais`. A leitura do cartão fica isolada para trocar a fonte (Planner) sem mexer no resto.
   - Do cartão vêm: formato, tipo de inserção, títulos das aulas (os títulos são sempre os das aulas gravadas no dia, na ordem).
   - Títulos que chegam grudados na mesma linha são separados pelo app até a conta bater com o número de aulas; o editor confirma.
   - "Unidade" não entra no nome nem em pasta.
3. **Retorno da Skoopia (opcional).** Quantos SRTs de corte e inserção o editor quiser.
   - Corte ou inserção: identificado pelo conteúdo (`[ERRO]`/`[BASTIDORES]`), não pelo nome.
   - De qual vídeo: se o tempo atravessa vídeos, veio do SRT único e é dividido pela tabela (cada aula começa em 00:00); se é de um vídeo só, o app confere as falas citadas contra a transcrição de cada vídeo. Sem certeza: "escolher vídeo".
4. **Material de inserção.** `.pptx`, roteiro `.docx`, imagens. O tipo de inserção é descoberto pelo material; a caixa na janela só confirma.

## Modos de marcação

Chave **"Marcações: Skoopia / Sem IA"**. Sem SRTs da Skoopia, usa automaticamente o modo Sem IA (regras do Fluxo NPD: frases de interrupção, tentativas repetidas, pausas, bastidores no início e no fim, alinhamento de slide por texto). Na timeline, os dois modos saem iguais. A Skoopia vale para todos os formatos desde a primeira versão.

## Aulas, takes e divisão

- Uma aula é **um ou mais trechos de vídeo**:
  - normal: um vídeo inteiro;
  - take descartado: o vídeo some inteiro (o primeiro take, quando a aula foi regravada);
  - final refeito em take curto: vídeo A até o ponto do erro + vídeo B;
  - final refeito emendando a próxima aula: aula 1 = A (até o erro) + B (até o fim do final); aula 2 = B (do "Olá" em diante).
- **Os títulos do cartão mandam** (decisão de 25/11/2026): cada título é uma aula, na ordem; o número da aula no mapa é o número do título (aula 9 = 9º título, mesmo se a 8 ficar sem trecho). Título sem trecho seguro = "aula não reconhecida — escolha"; nunca juntar tudo numa aula por falta de pista.
- Pistas para a divisão, somadas (nenhuma decide sozinha): abertura e fechamento na fala ("Olá…", "Vejo vocês lá", "nos vemos"); contagem de títulos (a conta tem de fechar para mais e para menos); abertura sem cumprimento ("Neste vídeo", "Nesta aula", "hoje vamos") e síntese no fim da anterior, com peso pequeno; conteúdo (palavras do título, do texto dos `.pptx` de cada aula e das inserções da Skoopia × fala); duração (arquivo curto quase sempre é continuação ou take). `[ERRO]` da Skoopia no fim de um vídeo.
- As regras antigas (cumprimento, take, final refeito) continuam iguais: os dias que já funcionavam saem iguais (conferido com os testes de 08/10 antes da mudança). Sem cartão, aula sem "Olá" só se separa com duas pistas fortes.
- Arquivo minúsculo no meio do dia (≤ 30 s, poucas palavras, sem abertura nem fechamento) sai como "trecho curto sem aula"; pausa de 5 min ou mais no meio de um trecho fica marcada para conferir.
- A aula é sempre definida pelo app (arquivo, fala, títulos). A aba "Aulas" da Skoopia não é usada (ela não exporta e errou o início de uma aula nos testes).
- Na janela, o **mapa do dia**: cada vídeo é uma faixa pintada pela aula; o editor arrasta o ponto de divisão ou troca a aula de um trecho. Conta que não fecha vira "conferir divisão".
- Futuro (script do estúdio): botão "Novo take da mesma aula" marca o arquivo como continuação.

## Timeline

Nada é apagado. Tudo entra cortado nos limites (razor), com cor e marcador:

| Tipo | Cor | Marcador |
|---|---|---|
| `[ERRO]` | Rose | explicação da Skoopia (ou regra que disparou) |
| `[BASTIDORES]` | Mango | explicação |
| A conferir (tempo não bate com o texto, sobreposição, divisão incerta) | Violet | motivo |
| Silêncio longo detectado pelo app | — (só marcador) | "silêncio" |
| Inserção | — | código da cartela (C33) e texto |

Cores editáveis em Configurações.

Antes de marcar, o app junta marcações sobrepostas, remove duplicadas e confere texto × tempo pelos números de cue citados.

**Nenhum efeito** em nenhum clipe (vídeo ou áudio). Única exceção: o enquadramento interno dos nests E/D.

Regras herdadas do Fluxo NPD: nests `-E` e `-D` do bruto 3840x1080 (sem dividir o arquivo); 1ª fala no quadro 175 (fim da vinheta, 00;00;05;25); câmera com escala e posição padrão; pastas no XML: Footage, Footage/nest, Slides; assets: brasão da PUC e vignette; lower third (mograph) não passa pelo XML e vira marcador.

Sequências nomeadas `01 Título`, `02 Título`… (ordem no dia). O editor escolhe onde exportar; padrão: pasta `Projeto` do dia, lembrando a última escolha.

O XML sai com os caminhos reais dos vídeos naquela máquina (sem relink no Premiere).

## Inserções por formato

O material do professor tem prioridade; a fala decide **quando**.

| Fonte | O que entra |
|---|---|
| Cartelas no `.pptx` | JPEG da cartela (ligação pela sugestão da Skoopia: código C.. quando houver, senão texto) |
| Negrito nos slides | cartela de palavra-chave (gerador do Fluxo NPD, Poppins) |
| Roteiro em duas colunas | marcador "INSERIR (roteiro)" por item da coluna da direita (conservador até haver exemplo real) |
| Imagens soltas | o arquivo, achado pelo nome citado |
| A critério do editor / sugestão sem cartela | marcador com o texto + botão "Gerar cartela" na revisão |

- **TP com slide / palavra-chave:** como acima, na trilha de inserção.
- **TV:** o ponto de inserção vira a troca para a exibição (D) em tela cheia; marcador para conferir (o professor interage pelo toque).
- **Screencast:** só cortes; inserções ignoradas.

## Slides

Conversão `.pptx` → JPEG dentro do app com LibreOffice embutido (1920x1080, qualidade 95). Fontes levadas no app: Montserrat, Carlito (equivalente da Calibri), Poppins. Se algum slide sair diferente, o editor exporta pelo PowerPoint e arrasta os JPEGs.

## Configurações (primeira vez em cada máquina)

Como o Link Media do Premiere: aponta um item, o app procura o resto na mesma estrutura; o que faltar tem o botão **Procurar**.
- pasta das gravações;
- assets compartilhados (brasão, vignette);
- pasta de exportação padrão;
- chave do Trello (opcional);
- cores das marcações.

Dentro do app, iguais para todos: modelos por formato, fontes, LibreOffice, regras de montagem.

## Relatório de uso

A cada montagem, um arquivo ao lado do XML com: modo (Skoopia / Sem IA), formato, número de marcações por tipo, itens "a conferir". Serve para relatar problemas.

## Transcrição (`transcribe`)

mlx-whisper large-v3-turbo, sem contexto anterior, tempo por palavra, descarte de alucinação em silêncio, remoção de repetições curtas. Legenda por trecho de fala (quebra em pontuação, vírgula e pausas de 0,5 s, até 12 s). Aceita pasta; gera o SRT único com separadores `[ARQUIVO: …]` e a tabela.

## Etapas

1. Base: janela, Configurações, pasta do dia, cartão/TXT, mapa do dia (Mac e Windows).
2. Montagem dos 4 formatos com as regras do Fluxo NPD portadas (sem efeitos, "01 Título", trechos) + Skoopia e Sem IA. Conferência: XML do Montador × Fluxo NPD nos mesmos dias (TP 21/09, Screencast Thiago Olimpio, TV Carlos Brandão).
3. Slides e inserções.
4. Ícone, instaladores e releases.

Aprovação: JP aprova a parte da Skoopia no TP com slide; publica com os 4 formatos; testes com e sem IA para os ajustes finos.

## Pontos a levar à Skoopia

- Cada `[ARQUIVO]` é uma gravação; nunca dividir uma aula dentro do mesmo arquivo; o início da aula é o primeiro cue depois do `[ARQUIVO]`, salvo bastidores.
- Nunca incluir a versão corrigida no corte; em repetição, cortar só a primeira; quando o professor refaz um trecho, cortar a tentativa anterior inteira.
- Um arquivo inteiro que se repete no seguinte é take descartado.
- Sempre devolver o código da cartela (C33) nas inserções.
