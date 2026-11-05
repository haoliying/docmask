@echo off
rem 从源码目录直接启动 docmask（Windows）。
rem 用法：
rem   scripts\start.bat --help
rem   scripts\start.bat run .\docs -o .\redacted_output
rem   scripts\start.bat ui

setlocal
set "ROOT=%~dp0.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
"%PYTHON%" -m docmask %*
