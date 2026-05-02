#!/usr/bin/env bash
# test_vllm.sh — smoke test for the vLLM endpoint
# Usage: bash test_vllm.sh [base_url]

BASE_URL="${1:-http://localhost:8000}"
MODEL="Qwen/Qwen2.5-14B-Instruct-AWQ"

echo "Testing $BASE_URL ..."

# 1. Health check
echo -n "  /health: "
curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health"
echo

# 2. Chat completion
echo "  /v1/chat/completions:"
curl -s "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  --data-binary @- << BODY | python3 -m json.tool
{"model":"$MODEL","messages":[{"role":"user","content":"Reply with one word: ready"}],"max_tokens":5}
BODY
