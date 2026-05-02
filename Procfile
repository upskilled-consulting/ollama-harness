# Procfile — run all services with: honcho start
#
# Prerequisites:
#   pip install honcho   (or: uv sync --extra dev)
#
# Start everything:          honcho start
# Start subset:              honcho start api mcp dashboard
# GPU services only:         honcho start ollama llama
# Skip GPU (software only):  honcho start api mcp dashboard

api:       uvicorn harness.api.main:app --host 0.0.0.0 --port 7860
mcp:       python -m harness.mcp_server --http --port 8766
dashboard: node dashboard/node_modules/vite/bin/vite.js dashboard --host 0.0.0.0
ollama:    ollama serve
llama:     llama.cpp\build\bin\llama-server.exe --model models\Qwen3.6-35B-A3B-UD-IQ3_S.gguf --ctx-size 16384 --parallel 2 --port 8083 -ngl 99
