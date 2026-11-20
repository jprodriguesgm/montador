# Montador

Monta as sequências das videoaulas do Núcleo de Produção Digital (PUC Minas / IEC) no Premiere a partir da transcrição, das marcações da IA (ou das regras sem IA) e do material de inserção.

O desenho completo está em [DESENHO.md](DESENHO.md).

## Estado

- **Etapa 1 (base):** configurações deste computador (arquivos dos projetos, como o Link Media), pasta do dia, cartão (títulos grudados), mapa do dia (aulas, takes descartados, trechos) e importação à mão de transcrições, SRTs da Skoopia e material.
- **Etapa 2 (montagem):** um XML por aula para o Premiere 25, nos formatos TP, TP com palavra-chave, TV e Screencast. Usa os geradores do Fluxo NPD (pasta `montador/motor`), com:
  - marcações da Skoopia (ERRO, BASTIDORES) ou as regras do Fluxo NPD (sem IA), mais SILÊNCIO detectado pelo app;
  - cor de cada tipo de marcação pelas Configurações; nada é apagado;
  - sequências "01 Título"; aula em dois vídeos sai em duas partes;
  - sem efeitos (Lumetri e Desfoque gaussiano saem); vinheta, brasão e fundos com os caminhos desta máquina;
  - relatório de uso ao lado dos XMLs.
- **Etapa 3 (slides e inserções):**
  - o .pptx do professor vira JPEG 1920x1080 (qualidade 95) em `Originais/<nome do pptx>/` — pelo LibreOffice, ou pelo Keynote no Mac sem LibreOffice; imagens já prontas nessa pasta são usadas como estão;
  - com a Skoopia, cada inserção é ligada ao slide pelo código da cartela (C33) ou pelo título; sem IA, pelo assunto do slide na fala (para conferir);
  - TP: o slide entra na V7 pelo tempo da nota do slide ("Exibir por 6 a 8 segundos" → 8 s) ou 15 s (Configurações), com marcador "SLIDE C33"; inserção sem slide vira marcador "CARTELA" com o texto;
  - TV: no ponto de inserção, a exibição (D) entra em tela cheia numa faixa nova por cima, com marcador "TELA CHEIA";
  - Screencast: só cortes.

No modo sem IA, o Montador gera exatamente o mesmo XML que o Fluxo NPD (conferido com `tools/comparar_fluxo.py`), mudando só o nome da sequência, o nome do marcador e a remoção do Lumetri e do Desfoque gaussiano.

## Testar no Mac (antes do app empacotado)

1. **Code > Download ZIP** nesta página e descompacte.
2. Dois cliques em **Abrir Montador.command**. Se o Mac bloquear: no Terminal, `xattr -dr com.apple.quarantine` e arraste a pasta.
3. A janela abre no navegador (`http://127.0.0.1:8767`). Ela fecha sozinha alguns minutos depois que a página é fechada.

Pelo Terminal também dá para ver o mapa sugerido de uma pasta:

```bash
python3 -m montador mapa "/caminho/da/pasta do dia"
```

## Testes

```bash
python3 -m pytest -q tests
```

### Ajustes 0.2.1
- Cortes e inserções da Skoopia feitos a partir do SRT único são divididos sozinhos por vídeo, mesmo sem a tabela: o Montador refaz a posição de cada vídeo dentro do SRT único e confere pelas falas citadas.
- Duração dos vídeos do OBS (MP4 fragmentado) lida pelo cabeçalho ou, se faltar, pelo ffprobe.
- Material: escolher vários arquivos de uma vez, tirar qualquer arquivo da lista (✕) e voltar a usar ("usar"). Arquivos que começam com "TP" (teleprompter) ficam fora por padrão.
