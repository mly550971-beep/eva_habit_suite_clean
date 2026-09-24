# EVA local AI setup

EVA now uses Ollama locally; no Gemini API key is required.

1. Install Ollama for Windows.
2. Run `install_local_model.bat` once, or manually:
   `ollama pull gemma4:e2b`
   `ollama pull embeddinggemma`
3. Start Ollama, then start EVA.

## Hardware note
Gemma 4 E2B is the default because it is the smallest official Gemma 4 edge model available in Ollama. Its package is still larger than 6 GB, so an RTX 4050 6 GB may offload some work to system RAM. If latency is poor, reduce `local_model.context_window` in `config.yaml` to 16384.

## Self-improvement
EVA has a `self_improve` tool. It asks the local model for a focused unified diff, validates paths, creates a backup, checks the patch, applies it, runs pytest, and rolls the change back if tests fail. Credentials, memory, sessions, logs, and arbitrary file deletion are blocked from automatic edits.
