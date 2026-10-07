@echo off
rem Inicia o sistema no Windows. Na primeira vez (e quando o programa e atualizado), instala o que falta.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\pronto-2.txt" (
  echo Preparando o ambiente. Isso leva alguns minutos so na primeira vez...
  if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || goto erro
  ".venv\Scripts\python" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python" -m pip install --quiet -r requirements.txt || goto erro
  echo ok> ".venv\pronto-2.txt"
)
".venv\Scripts\python" app.py %*
pause
exit /b
:erro
echo.
echo Nao consegui preparar o ambiente. Confira se o Python 3.10 ou mais novo esta instalado
echo (python.org/downloads, marcando "Add Python to PATH") e tente de novo.
pause
