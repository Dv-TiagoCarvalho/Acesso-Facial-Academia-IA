#!/bin/sh
# Inicia o sistema no macOS ou Linux. Na primeira vez (e quando o programa é
# atualizado), instala o que falta.
cd "$(dirname "$0")" || exit 1
if [ ! -f .venv/pronto.txt ] || [ requirements.txt -nt .venv/pronto.txt ]; then
  echo "Preparando o ambiente. Isso leva alguns minutos só na primeira vez..."
  [ -d .venv ] || python3 -m venv .venv || { echo "Instale o Python 3.10 ou mais novo (python.org/downloads) e tente de novo."; exit 1; }
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt || { echo "Não consegui instalar as dependências. Confira a internet e tente de novo."; exit 1; }
  date > .venv/pronto.txt
fi
exec .venv/bin/python app.py "$@"
