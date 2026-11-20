#!/bin/bash
# Abre o Montador (versão de teste, antes do app empacotado). Dois cliques no Finder.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Este Mac não tem o python3. Instale pelas Ferramentas de Linha de Comando: xcode-select --install"
  read -r -p "Pressione Enter para fechar..."
  exit 1
fi
python3 -m montador abrir --fechar-sozinho
