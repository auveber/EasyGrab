# Сторонние библиотеки

EasyGrab использует перечисленные ниже библиотеки. Они остаются за своими
авторами и распространяются на своих условиях. Лицензии сверены
с метаданными установленных пакетов.

| Библиотека | Лицензия | Исходники |
|---|---|---|
| CustomTkinter | MIT | https://github.com/TomSchimansky/CustomTkinter |
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| instagrapi | MIT | https://github.com/subzeroid/instagrapi |
| instaloader | MIT | https://github.com/instaloader/instaloader |
| browser_cookie3 | LGPL-3.0 | https://github.com/borisbabic/browser_cookie3 |
| openpyxl | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| ReportLab | BSD | https://www.reportlab.com/ |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |
| Requests | Apache-2.0 | https://github.com/psf/requests |
| Pydantic | MIT | https://github.com/pydantic/pydantic |
| Python | PSF | https://www.python.org/ |

## На что обратить внимание при распространении

**MIT, BSD, Apache-2.0** разрешают любое использование, включая коммерческое,
и требуют одного: сохранять указание авторства и текст лицензии в поставке.
Этот файл закрывает требование.

**Unlicense** (yt-dlp) — общественное достояние, условий нет.

**LGPL-3.0** (browser_cookie3) — единственная копилефт-лицензия здесь.
Она разрешает коммерческое использование, но требует, чтобы пользователь мог
заменить эту библиотеку своей версией. При обычной установке через pip это
выполняется само собой. Если приложение будут собирать в один исполняемый
файл, условие усложняется — в этом случае библиотеку проще сделать
необязательной: она нужна только для чтения сессии Instagram из браузера,
и это запасной путь, а не основной.

## Про сам код EasyGrab

Код приложения — самостоятельное произведение: библиотеки он вызывает,
а не содержит в себе. Собран вручную при помощи ИИ.

Контакт автора: t.me/auveber

