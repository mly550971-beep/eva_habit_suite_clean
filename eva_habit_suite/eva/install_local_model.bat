@echo off
setlocal
where ollama >nul 2>&1
if errorlevel 1 (
  echo Ollama is not installed. Install it from https://ollama.com/download/windows
  exit /b 1
)
echo Pulling Gemma 4 E2B...
ollama pull gemma4:e2b
if errorlevel 1 exit /b 1
echo Pulling EmbeddingGemma for local memory search...
ollama pull embeddinggemma
if errorlevel 1 exit /b 1
echo Done. Start EVA normally.
