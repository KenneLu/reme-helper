@echo off
rem ---------------------------------------------------------------------------
rem reme-helper local release build: tests -> icon -> PyInstaller -> verify
rem
rem ASCII-only on purpose: cmd.exe parses .bat with the machine ANSI code page,
rem so non-ASCII comments can be mis-read and break the script.
rem
rem Usage: scripts\build.bat [release] [norun] [nopause] [clean] [--force]
rem   release   pass --release to main.py so the tray startup path is verified
rem   norun     do not start the built exe (starting it is the default)
rem   nopause   unattended (no "press any key") - used by CI
rem   clean     remove the build cache; add --force to delete releases too
rem
rem Version comes from src\main.py VERSION (single source of truth).
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0.."

set RUN_AFTER=1
set NOPAUSE=
set CLEAN_ONLY=
set FORCE_CLEAN=
set RELEASE_FLAG=
set BUILD_ARGS=%*
if not defined BUILD_ARGS goto :args_done
for %%a in (%BUILD_ARGS%) do (
  if /i "%%a"=="release" set RELEASE_FLAG=--release
  if /i "%%a"=="norun" set RUN_AFTER=
  if /i "%%a"=="nopause" set NOPAUSE=1
  if /i "%%a"=="clean" set CLEAN_ONLY=1
  if /i "%%a"=="--force" set FORCE_CLEAN=1
)
:args_done

rem Interpreter: fixed local path first, otherwise fall back to PATH python
set PY=H:\Tools\Python\Python313\python.exe
if not exist "%PY%" set PY=python
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Set PY=... at the top of build.bat.
  if not defined NOPAUSE pause
  exit /b 1
)

rem Version: read it from main.py so the script and the app cannot drift apart
set VERSION=
for /f "tokens=1,2,*" %%a in ('findstr /b /c:"VERSION = " src\main.py') do set VERSION=%%~c
if not defined VERSION (
  echo [ERROR] Cannot read VERSION from src\main.py.
  if not defined NOPAUSE pause
  exit /b 1
)
set PACKAGE=reme-helper-%VERSION%
rem The release folder and the zip keep the version, but the exe inside must NOT:
rem the autostart registry value stores the full path to the exe, so a versioned
rem name would leave a stale entry behind on every in-place update.
set APPNAME=reme-helper
set RELEASE_DIR=release\%PACKAGE%
set FROZEN_EXE=%RELEASE_DIR%\%APPNAME%.exe
set BUILD_CACHE=.cache
set STAGING=%BUILD_CACHE%\dist
set WRK=%BUILD_CACHE%\work
set SPEC=%BUILD_CACHE%\spec
set VENV=%BUILD_CACHE%\venv

echo [VERSION] %VERSION%  release: %RELEASE_DIR%

if defined CLEAN_ONLY goto :clean

if exist "%RELEASE_DIR%" (
  echo [ERROR] %RELEASE_DIR% already exists. Run "build.bat clean --force" first.
  echo         One folder per version keeps releases reproducible.
  if not defined NOPAUSE pause
  exit /b 1
)

rem No reme-helper of any version may run: files would be locked and two trays
rem would fight over the same config, service and tunnels
tasklist /fo csv 2>nul | findstr /i /c:"reme-helper-" >nul
if not errorlevel 1 (
  echo [ERROR] reme-helper is running. Exit it from the tray before building.
  if not defined NOPAUSE pause
  exit /b 1
)

call :mktools
if errorlevel 1 (
  if not defined NOPAUSE pause
  exit /b 1
)

echo [TEST] unit tests + settings matrix ...
"%PY%" tests\test_helper.py
if errorlevel 1 (
  echo [ERROR] test_helper.py failed.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [TEST] baseline snapshot ...
"%PY%" tests\test_baseline.py
if errorlevel 1 (
  echo [ERROR] test_baseline.py failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem The suites write their logs to log\tests\, not to the repository root - see
rem TOOL in tests/conftest.py. Every "type" below used to look in the root, so
rem instead of printing the log it printed "The system cannot find the file
rem specified." six times: the build's own "see <log>" pointer had never worked,
rem and the noise was indistinguishable from a real error.
set "TEST_LOGS=log\tests"

echo [TEST] i18n table + source coverage ...
"%PY%" tests\test_i18n.py
if errorlevel 1 (
  echo [ERROR] test_i18n.py failed. See %TEST_LOGS%\i18n-test.log
  if not defined NOPAUSE pause
  exit /b 1
)
if exist "%TEST_LOGS%\i18n-test.log" type "%TEST_LOGS%\i18n-test.log"

echo [TEST] API key field - load + mask + reveal ...
"%PY%" tests\test_key_field.py
if errorlevel 1 (
  echo [ERROR] test_key_field.py failed. See %TEST_LOGS%\key-field-test.log
  if not defined NOPAUSE pause
  exit /b 1
)
if exist "%TEST_LOGS%\key-field-test.log" type "%TEST_LOGS%\key-field-test.log"

echo [TEST] settings window UI test ...
"%PY%" tests\test_settings_ui.py
if errorlevel 1 (
  echo [ERROR] test_settings_ui.py failed. See %TEST_LOGS%\settings-ui-test.log
  if not defined NOPAUSE pause
  exit /b 1
)
if exist "%TEST_LOGS%\settings-ui-test.log" type "%TEST_LOGS%\settings-ui-test.log"

echo [TEST] theme consistency - no shift, no unreadable text ...
"%PY%" tests\test_theme_ui.py
if errorlevel 1 (
  echo [ERROR] test_theme_ui.py failed. See %TEST_LOGS%\theme-test.log
  if not defined NOPAUSE pause
  exit /b 1
)
if exist "%TEST_LOGS%\theme-test.log" type "%TEST_LOGS%\theme-test.log"

echo [TEST] english mode scan ...
"%PY%" tests\test_en_mode.py
if errorlevel 1 (
  echo [ERROR] test_en_mode.py failed. See %TEST_LOGS%\en-mode-test.log
  if not defined NOPAUSE pause
  exit /b 1
)
if exist "%TEST_LOGS%\en-mode-test.log" type "%TEST_LOGS%\en-mode-test.log"

echo [TEST] console lifecycle - language and theme rebuilds ...
"%PY%" tests\test_console_lifecycle.py
if errorlevel 1 (
  echo [ERROR] test_console_lifecycle.py failed. See %TEST_LOGS%\console-lifecycle-test.log
  if not defined NOPAUSE pause
  exit /b 1
)
if exist "%TEST_LOGS%\console-lifecycle-test.log" type "%TEST_LOGS%\console-lifecycle-test.log"

if exist "%STAGING%" rmdir /s /q "%STAGING%"

echo [BUILD] icon ...
rem Generate separate state/tray and small-frame-optimised taskbar assets.
"%PY%" src\main.py --make-icon
if errorlevel 1 (
  echo [ERROR] icon generation failed.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [BUILD] PyInstaller onedir noconsole ...
rem onedir (not onefile) keeps tray startup instant: onefile unpacks the whole
rem runtime into %TEMP% on every launch.
rem Size control: numpy and the PIL avif/webp decoders are unused here and cost
rem about 34MB (package was ~70.7MB, becomes ~34.5MB). stdlib test/debug modules
rem dropped as well.
"%PY%" -m PyInstaller --noconfirm --clean --onedir --noconsole ^
  --name %APPNAME% ^
  --icon "%CD%\reme-helper-taskbar.ico" ^
  --add-data "%CD%\reme-helper.ico;." ^
  --add-data "%CD%\reme-helper-taskbar.ico;." ^
  --add-data "%CD%\doc;doc" ^
  --exclude-module numpy ^
  --exclude-module numpy.core ^
  --exclude-module PIL._avif ^
  --exclude-module PIL._webp ^
  --exclude-module unittest ^
  --exclude-module doctest ^
  --exclude-module pydoc ^
  --exclude-module pdb ^
  --distpath "%STAGING%" ^
  --workpath "%WRK%" ^
  --paths src ^
  --specpath "%SPEC%" ^
  %CD%\src\main.py ^
  --collect-all psutil ^
  --collect-all tkinter ^
  --collect-all yaml ^
  --hidden-import pystray ^
  --hidden-import PIL.ImageDraw
if errorlevel 1 (
  echo [ERROR] PyInstaller failed.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [PACK] assembling %RELEASE_DIR% ...
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
robocopy "%STAGING%\%APPNAME%" "%RELEASE_DIR%" /E /R:1 /W:1 /NFL /NDL /NP >nul
if errorlevel 8 (
  echo [ERROR] Package copy failed.
  if not defined NOPAUSE pause
  exit /b 1
)
copy /y README.md "%RELEASE_DIR%\README.md" >nul
copy /y LICENSE "%RELEASE_DIR%\LICENSE" >nul
xcopy /e /i /y "doc" "%RELEASE_DIR%\doc" >nul
if errorlevel 1 (
  echo [ERROR] doc copy failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem A release ships a template config, never the developer's live config.json:
rem the live one holds the LLM/embedding keys and the user's own targets.
"%PY%" scripts\make_release_config.py "%RELEASE_DIR%\config.json"
if errorlevel 1 (
  echo [ERROR] make_release_config.py failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem Deliverable checks: exe + integration doc. The app looks in doc first and
rem then in _internal\doc, so both layouts remain covered.
if not exist "%FROZEN_EXE%" (
  echo [ERROR] %APPNAME%.exe missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)
rem Guard against a silently empty package: --name and the robocopy source must
rem stay in step. If they ever drift, robocopy copies nothing and still returns
rem below 8, so the zip would ship with the exe and no runtime at all.
if not exist "%RELEASE_DIR%\_internal\base_library.zip" (
  echo [ERROR] _internal has no runtime - the package is incomplete.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\doc\zh\setup.md" (
  echo [ERROR] integration doc missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\doc\capture.mjs" (
  echo [ERROR] capture script missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\doc\capture_cc.mjs" (
  echo [ERROR] Claude Code capture script missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\reme-helper-taskbar.ico" (
  echo [ERROR] taskbar icon asset missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\doc\en\setup.md" (
  echo [WARN] doc not found under _internal - the copy next to the exe still works.
)

rem Point every packaged check at the config that ships with THIS package, not at
rem whatever the developer's machine keeps in %LOCALAPPDATA%\reme-helper. Without
rem this the --release gate reads a live config and trips its own assertions
rem (llm empty / no personal targets / no autostart).
set "REME_HELPER_CONFIG=%RELEASE_DIR%\config.json"

echo [TEST] smoke test ...
"%FROZEN_EXE%" --smoke
if errorlevel 1 goto :smoke_failed
type "%RELEASE_DIR%\log\smoke.log"
echo.
echo [TEST] settings window build check ...
"%FROZEN_EXE%" --ui-check
if errorlevel 1 goto :ui_failed
type "%RELEASE_DIR%\log\ui-check.log"
echo.
echo [TEST] packaged icon generation - PIL inside the frozen build ...
rem after excluding numpy and the avif/webp decoders, prove the tray icon still
rem renders in the packaged environment
"%FROZEN_EXE%" --make-icon >nul
if errorlevel 1 (
  echo [ERROR] Packaged icon generation failed - a PIL dependency was excluded.
  if not defined NOPAUSE pause
  exit /b 1
)
echo.

rem The release gate: goto-based on purpose. Nested if-blocks plus errorlevel
rem checks inside them are parsed unreliably by cmd (a stray "(" in an echo or a
rem nested failure can silently skip the exit), and this gate must never be
rem skipped - it is what keeps a broken package from being published.
if not defined RELEASE_FLAG goto :release_done
echo [TEST] tray startup path, --release ...
"%FROZEN_EXE%" --release
if errorlevel 1 goto :release_failed
type "%RELEASE_DIR%\log\release.log"
echo.

:release_done

rem Diagnostics are never part of a release. This runs as the LAST thing before
rem launch on purpose: each check below starts the frozen exe, which recreates
rem log/ while writing its own diagnostics, so cleaning earlier leaves an empty
rem log/ in the shipped folder (defeats the point of shipping none).
if exist "%RELEASE_DIR%\log" rmdir /s /q "%RELEASE_DIR%\log"
for %%f in (smoke.log ui-check.log release.log i18n_review.md lang-audit.log) do if exist "%%f" del /q "%%f"
if exist "log\tests" rmdir /s /q "log\tests"
if exist "%RELEASE_DIR%\log" (
  echo [WARN] %RELEASE_DIR%\log came back while packaging - check for a stray writer.
)

echo [DONE] release: %FROZEN_EXE%
if defined RUN_AFTER (
  echo [RUN] starting %APPNAME%.exe ...
  start "" "%FROZEN_EXE%"
)
if not defined NOPAUSE pause
exit /b 0

rem ---------------------------------------------------------------------------
rem release_failed: the packaged self-check said no; never publish this build
rem ---------------------------------------------------------------------------
:release_failed
echo [ERROR] --release check failed. See %RELEASE_DIR%\log\release.log
if exist "%RELEASE_DIR%\log\release.log" type "%RELEASE_DIR%\log\release.log"
if not defined NOPAUSE pause
exit /b 1

rem ---------------------------------------------------------------------------
rem smoke_failed / ui_failed: same shape as release_failed, and for the same
rem reason. The diagnostic log lives in %RELEASE_DIR%\log, which exists only on
rem the machine that ran the build - on CI it is destroyed with the runner. A
rem failure that says "see smoke.log" and then prints nothing is a failure
rem nobody can act on: the first v1.0.7 release died on exactly that.
rem ---------------------------------------------------------------------------
:smoke_failed
echo [ERROR] Smoke test failed. See %RELEASE_DIR%\log\smoke.log
if exist "%RELEASE_DIR%\log\smoke.log" type "%RELEASE_DIR%\log\smoke.log"
if not defined NOPAUSE pause
exit /b 1

:ui_failed
echo [ERROR] UI check failed. See %RELEASE_DIR%\log\ui-check.log
if exist "%RELEASE_DIR%\log\ui-check.log" type "%RELEASE_DIR%\log\ui-check.log"
if not defined NOPAUSE pause
exit /b 1

rem ---------------------------------------------------------------------------
rem clean
rem ---------------------------------------------------------------------------
:clean
if exist "%BUILD_CACHE%" rmdir /s /q "%BUILD_CACHE%"
echo [CLEAN] removed %BUILD_CACHE%
if defined FORCE_CLEAN (
  if exist release rmdir /s /q release
  echo [CLEAN] removed release
) else (
  echo [CLEAN] kept release - add --force to delete built releases too
)
for %%f in (smoke.log ui-check.log release.log i18n_review.md lang-audit.log) do if exist %%f del /q %%f
if not defined NOPAUSE pause
exit /b 0

rem ---------------------------------------------------------------------------
rem mktools: PyInstaller must be runnable; install it into an isolated venv when
rem the interpreter does not have it, so a clean machine (CI) just works.
rem ---------------------------------------------------------------------------
:mktools
"%PY%" -c "import PyInstaller" >nul 2>nul
if not errorlevel 1 exit /b 0
if exist "%VENV%\Scripts\python.exe" goto :mktools_use

echo [SETUP] PyInstaller missing - creating %VENV% ...
"%PY%" -m venv "%VENV%"
if errorlevel 1 (
  echo [ERROR] Could not create the build venv.
  exit /b 1
)

:mktools_use
echo [SETUP] installing build requirements ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements.txt
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet pyinstaller
if errorlevel 1 (
  echo [ERROR] pip install failed.
  exit /b 1
)
echo [SETUP] using %VENV%\Scripts\python.exe for this build
set PY=%VENV%\Scripts\python.exe
exit /b 0
