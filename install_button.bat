@echo off
chcp 65001 >nul
echo ========================================================
echo  Установка кнопки "Рассчитать время (Ingro DFM)" в Siemens NX
echo ========================================================
echo.

set TARGET_DIR=D:\Antihrafity\FW\Ingro\ingro_dfm

echo Настройка переменной среды UGII_USER_DIR...
setx UGII_USER_DIR "%TARGET_DIR%" >nul

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [УСПЕХ] Переменная UGII_USER_DIR установлена: %TARGET_DIR%
    echo.
    echo При следующем запуске Siemens NX на ленте автоматически появится:
    echo   - Вкладка: "Ingro DFM"
    echo   - Кнопка  : "Рассчитать время (ЦБНТ)"
    echo.
) else (
    echo [ОШИБКА] Не удалось установить переменную среды.
)

pause
