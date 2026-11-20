# Montador

Monta as sequências das videoaulas do Núcleo de Produção Digital (PUC Minas / IEC) no Premiere a partir da transcrição, das marcações da IA (ou das regras sem IA) e do material de inserção.

O desenho completo está em [DESENHO.md](DESENHO.md).

## Estado

**Etapa 1 (base):** configurações deste computador (arquivos dos projetos, como o Link Media), leitura da pasta do dia e do cartão, títulos (inclusive grudados) e o mapa do dia com aulas, takes descartados e trechos. A montagem do XML chega na etapa 2.

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
