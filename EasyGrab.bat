@echo off
rem Запуск EasyGrab двойным щелчком (Windows).
rem Скрипт сам переходит в свою папку, поэтому её можно переносить куда угодно.

cd /d "%~dp0"

rem Свой venv предпочтительнее системного Python: в нём уже стоят
rem customtkinter, openpyxl, reportlab и yt-dlp.
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" main.py
    goto :eof
)

rem pythonw вместо python — чтобы не висело чёрное окно консоли за приложением.
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw main.py
    goto :eof
)

where python >nul 2>&1
if %errorlevel%==0 (
    python main.py
    if errorlevel 1 (
        echo.
        echo EasyGrab завершился с ошибкой. Текст причины — выше.
        pause
    )
    goto :eof
)

echo Не найден Python 3. Установите его с python.org,
echo при установке отметьте галочку "Add Python to PATH", и запустите снова.
pause
