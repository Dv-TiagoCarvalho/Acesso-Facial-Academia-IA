#!/bin/sh
# macOS: dê dois cliques neste arquivo para iniciar o sistema.
cd "$(dirname "$0")" || exit 1
sh iniciar.sh
echo
echo "O programa foi encerrado. Pode fechar esta janela."
