@echo off
pushd "%~dp0.." >nul

if not defined HYBRID_API_BASE (
    set "HYBRID_API_BASE=http://127.0.0.1:8001/api"
)
if not defined HYBRID_SESSION_ID (
    set "HYBRID_SESSION_ID=hybrid-seed-runner"
)
if not defined HYBRID_CDP_ENDPOINT (
    set "HYBRID_CDP_ENDPOINT=http://127.0.0.1:9223"
)
if not defined HYBRID_RUN_MODE (
    set "HYBRID_RUN_MODE=hybrid"
)
if not defined TAOBAO_AUTH_PROFILE_DIR (
    set "TAOBAO_AUTH_PROFILE_DIR=output\taobao-auth-profile"
)
if not defined HYBRID_RESPECT_OPERATOR_GUIDANCE (
    set "HYBRID_RESPECT_OPERATOR_GUIDANCE=1"
)
if not defined HYBRID_FAIL_ON_OPERATOR_ESCALATION (
    set "HYBRID_FAIL_ON_OPERATOR_ESCALATION=0"
)
if not defined HYBRID_STOP_ON_OPERATOR_ESCALATION (
    set "HYBRID_STOP_ON_OPERATOR_ESCALATION=0"
)
if not defined HYBRID_OPERATOR_ESCALATION_EXIT_CODE (
    set "HYBRID_OPERATOR_ESCALATION_EXIT_CODE=42"
)
if not defined HYBRID_RUNTIME_SUMMARY_PATH (
    set "HYBRID_RUNTIME_SUMMARY_PATH=datas\avm\hybrid_seed_collection_runtime.json"
)
if not defined HYBRID_EXTRA_ARGS (
    set "HYBRID_EXTRA_ARGS="
)

set "HYBRID_GUIDANCE_FLAG="
if "%HYBRID_RESPECT_OPERATOR_GUIDANCE%"=="1" (
    set "HYBRID_GUIDANCE_FLAG=--respect-operator-guidance"
)

set "HYBRID_ESCALATION_FLAG="
if "%HYBRID_FAIL_ON_OPERATOR_ESCALATION%"=="1" (
    set "HYBRID_ESCALATION_FLAG=--fail-on-operator-escalation --operator-escalation-exit-code %HYBRID_OPERATOR_ESCALATION_EXIT_CODE%"
)

set "HYBRID_STOP_ESCALATION_FLAG="
if "%HYBRID_STOP_ON_OPERATOR_ESCALATION%"=="1" (
    set "HYBRID_STOP_ESCALATION_FLAG=--stop-on-operator-escalation"
)

REM 1. Prefer externally injected PYTHON_CMD for smoke/wrapper overrides
if defined PYTHON_CMD (
    echo [INFO] Using preset PYTHON_CMD: %PYTHON_CMD%
) else (
    REM 2. Prefer the project-local venv when available
    if exist "venv\Scripts\python.exe" (
        set "PYTHON_CMD=venv\Scripts\python.exe"
    ) else (
        REM 3. Fallback to system Python
        echo [INFO] Local venv not found, falling back to system Python...
        set "PYTHON_CMD=python"
    )
)

echo [INFO] Hybrid API base: %HYBRID_API_BASE%
echo [INFO] Hybrid session id: %HYBRID_SESSION_ID%
echo [INFO] Hybrid CDP endpoint: %HYBRID_CDP_ENDPOINT%
echo [INFO] Hybrid mode: %HYBRID_RUN_MODE%
echo [INFO] Hybrid auth profile: %TAOBAO_AUTH_PROFILE_DIR%
echo [INFO] Hybrid respect operator guidance: %HYBRID_RESPECT_OPERATOR_GUIDANCE%
echo [INFO] Hybrid fail on operator escalation: %HYBRID_FAIL_ON_OPERATOR_ESCALATION%
echo [INFO] Hybrid stop on operator escalation: %HYBRID_STOP_ON_OPERATOR_ESCALATION%
echo [INFO] Hybrid runtime summary path: %HYBRID_RUNTIME_SUMMARY_PATH%
if defined HYBRID_EXTRA_ARGS (
    echo [INFO] Hybrid extra args: %HYBRID_EXTRA_ARGS%
)

call "%PYTHON_CMD%" tools/run_hybrid_seed_collection.py --api-base "%HYBRID_API_BASE%" --session-id "%HYBRID_SESSION_ID%" --cdp-endpoint "%HYBRID_CDP_ENDPOINT%" --mode "%HYBRID_RUN_MODE%" --profile-dir "%TAOBAO_AUTH_PROFILE_DIR%" --runtime-summary-path "%HYBRID_RUNTIME_SUMMARY_PATH%" --submit --loop --open-browser-fallback %HYBRID_GUIDANCE_FLAG% %HYBRID_ESCALATION_FLAG% %HYBRID_STOP_ESCALATION_FLAG% %HYBRID_EXTRA_ARGS%
set "HYBRID_RUN_EXIT_CODE=%ERRORLEVEL%"

if "%HYBRID_RUN_EXIT_CODE%"=="%HYBRID_OPERATOR_ESCALATION_EXIT_CODE%" (
    echo [WARN] Hybrid runner exited with operator escalation code %HYBRID_RUN_EXIT_CODE%
    if exist "%HYBRID_RUNTIME_SUMMARY_PATH%" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0emit_hybrid_operator_banner.ps1" -SummaryPath "%HYBRID_RUNTIME_SUMMARY_PATH%"
    )
)

popd >nul
pause
exit /b %HYBRID_RUN_EXIT_CODE%
