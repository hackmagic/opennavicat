@echo off
cd /d "%~dp0"
echo ========================================
echo  OpenNavicat GUI 启动中...
echo ========================================
echo.
python -m open_navicat.main gui
if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请确保依赖已安装
    echo 运行: pip install PySide6 aiomysql sqlparse typer rich httpx openai
    pause
)
