@echo off
cd /d "%~dp0.."

:: 1. 尝试使用项目内 venv (推荐)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
) else (
    :: 2. 回退到系统全局 Python
    echo [INFO] 未检测到 venv，尝试使用系统 Python...
    set "PYTHON_CMD=python"
)

:: 执行
"%PYTHON_CMD%" src/server.py
pause

