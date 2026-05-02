@echo off
REM test_harness_vllm.bat — end-to-end harness test against vLLM
REM Run from the harness root directory.
REM Requires: vLLM serving on localhost:8000 (WSL2), INFERENCE_BACKEND=vllm in .env

cd /d "%~dp0"
call conda activate ollama-pi 2>nul || call activate ollama-pi 2>nul

echo.
echo ============================================================
echo  Step 1: inference shim unit test
echo ============================================================
python test_inference_shim.py
if errorlevel 1 (
    echo FAILED: inference shim test. Is vLLM running in WSL2?
    exit /b 1
)

echo.
echo ============================================================
echo  Step 2: agent run (short task, no wiggum)
echo ============================================================
python agent.py --no-wiggum "Summarize in two sentences what prefix caching is in LLM inference and save to harness-engineering/vllm_test_output.md"

echo.
echo ============================================================
echo  Step 3: check output
echo ============================================================
if exist vllm_test_output.md (
    echo Output file created:
    type vllm_test_output.md
) else (
    echo WARNING: vllm_test_output.md not found
)

echo.
echo Done.
