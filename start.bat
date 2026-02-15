@echo off
echo ============================================
echo Final Trade - 快速启动脚本
echo ============================================
echo.

echo [1/3] 启动后端服务...
cd backend
start "Final Trade Backend" python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
echo 后端启动中... 请等待5秒
timeout /t 5 /nobreak >nul

echo.
echo [2/3] 检查后端服务...
curl -s http://127.0.0.1:8000/api/config >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ 后端服务启动成功！
    echo   API地址: http://127.0.0.1:8000
) else (
    echo ✗ 后端服务启动失败，请检查错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 启动前端服务...
cd ..\frontend
start "Final Trade Frontend" npm run dev
echo 前端启动中... 请等待5秒
timeout /t 5 /nobreak >nul

echo.
echo ============================================
echo 启动完成！
echo ============================================
echo.
echo 前端地址: http://localhost:4173
echo 后端API:  http://127.0.0.1:8000
echo.
echo 按任意键打开浏览器...
pause >nul

echo 正在打开浏览器...
start http://localhost:4173

echo.
echo 提示：
echo - 后端和前端服务将在独立窗口中运行
echo - 关闭窗口即可停止对应服务
echo - 详细文档请查看 docs/QUICKSTART.md
echo.
pause