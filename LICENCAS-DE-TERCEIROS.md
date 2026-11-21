# Licenças de terceiros

O código do Montador é licenciado sob a **GPL-3.0-or-later** (arquivo [LICENSE](LICENSE)).
O app pronto (Releases) leva dentro os programas e dados abaixo. Todos têm licença livre e compatível
com a GPL-3.0. Nenhum deles se conecta à internet quando o app está em uso.

| Peça | Licença | Para que serve no app | Código-fonte |
|---|---|---|---|
| LibreOffice (versão "stable" oficial do dia da montagem) | MPL-2.0 (e outras livres, ver o próprio pacote) | converter os slides (.pptx → PDF) | https://www.libreoffice.org |
| pypdfium2 / PDFium | Apache-2.0 ou BSD-3-Clause / BSD-3-Clause e Apache-2.0 | PDF → imagem dos slides | https://github.com/pypdfium2-team/pypdfium2 |
| Montserrat | SIL Open Font License 1.1 | fonte dos slides do professor | https://github.com/JulietaUla/Montserrat |
| Poppins | SIL Open Font License 1.1 | fonte das cartelas de palavra-chave | https://github.com/google/fonts/tree/main/ofl/poppins |
| Carlito | SIL Open Font License 1.1 | substituta métrica da Calibri nos slides | https://github.com/google/fonts/tree/main/ofl/carlito |
| html2canvas 1.4.1 | MIT | desenhar as thumbs em PNG | https://github.com/niklasvh/html2canvas |
| Python | PSF License 2.0 | o app em si | https://www.python.org |
| Pillow | MIT-CMU (HPND) | imagens | https://python-pillow.org |
| PyInstaller (bootloader) | GPL-2.0-or-later com exceção do bootloader | empacotar o app | https://pyinstaller.org |

As licenças das fontes vão junto (`fontes/OFL-*.txt` dentro do app) e a do html2canvas em
[montador/ui/vendor/html2canvas-LICENSE.txt](montador/ui/vendor/html2canvas-LICENSE.txt).

**O que não vai no app:** a fonte das thumbs (Cronos Pro, licenciada) e as artes de fundo das thumbs. O
Montador as lê do `index.html` do gerador de thumbnail da equipe, apontado nas Configurações de cada
computador.

A forma como cada peça é baixada está em [packaging/build_deps.py](packaging/build_deps.py), e a montagem
é feita pelo GitHub Actions ([.github/workflows/montar.yml](.github/workflows/montar.yml)), com o registro
público de cada montagem.
