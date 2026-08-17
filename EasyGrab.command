#!/bin/bash
# Запуск EasyGrab двойным щелчком (macOS и Linux).
#
# Первый раз файл может не запуститься — macOS помечает скачанные файлы как
# недоверенные. Тогда один раз выполните в Терминале:
#     chmod +x "путь/до/EasyGrab.command"
# либо кликните правой кнопкой -> Открыть -> Открыть.
#
# Скрипт сам находит папку приложения относительно себя, поэтому папку
# можно переносить куда угодно — путь внутри не зашит.

cd "$(dirname "$0")" || exit 1

# Свой venv предпочтительнее системного Python: в нём уже стоят
# customtkinter, openpyxl, reportlab и yt-dlp.
if [ -x "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "Не найден Python 3. Установите его с python.org и запустите снова."
    echo "Нажмите Enter, чтобы закрыть окно."
    read -r _
    exit 1
fi

"$PYTHON" main.py
STATUS=$?

# Окно закрывается само при удачном запуске. Если приложение упало —
# оставляем окно открытым, иначе текст ошибки промелькнёт и пропадёт.
if [ $STATUS -ne 0 ]; then
    echo ""
    echo "EasyGrab завершился с ошибкой (код $STATUS)."
    echo "Скопируйте текст выше — по нему видно причину."
    echo "Нажмите Enter, чтобы закрыть окно."
    read -r _
fi
