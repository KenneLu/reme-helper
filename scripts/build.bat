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

rem F11/D12: build and test instances must never share the resident tray data
rem root (config / log / quit.request). Redirect the whole data root to a temp
rem folder so a build can never disturb or be disturbed by the running app.
set "REME_HELPER_DATA_DIR=%TEMP%\reme-helper-builddata"

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

rem ---------------------------------------------------------------------------
rem IDENT line (R-EVID, team-wide 2026-09-19): evidence must carry its own revision.
rem Everything below goes into a log people paste into chat, and without this line a log
rem cannot say WHEN it was taken - "it is wrong" and "it was taken before your fix" are
rem indistinguishable, and the two need opposite responses. Prints first, before anything
rem can fail, and degrades instead of aborting when git or PowerShell is unavailable.
rem ---------------------------------------------------------------------------
set "IDENT_REV=(no git)"
for /f "usebackq delims=" %%r in (`git -C "%CD%" rev-parse --short HEAD 2^>nul`) do set "IDENT_REV=%%r"
set "IDENT_DIRTY=no"
for /f "usebackq delims=" %%s in (`git -C "%CD%" status --porcelain 2^>nul`) do set "IDENT_DIRTY=yes"
set "IDENT_SHA=?"
for /f "usebackq delims=" %%h in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 src\main.py).Hash" 2^>nul`) do set "IDENT_SHA=%%h"
echo [IDENT] rev=%IDENT_REV% dirty=%IDENT_DIRTY% src\main.py sha256=%IDENT_SHA%

rem Interpreter: fixed local path first, otherwise fall back to PATH python
set PY=H:\Tools\Python\Python313\python.exe
if not exist "%PY%" set PY=python
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Set PY=... at the top of build.bat.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

rem Version: read from main.py so the script and the app cannot drift apart.
rem Robust parse: take everything after '=', drop quotes, then keep the FIRST
rem space-delimited token. A trailing comment on the VERSION line can therefore
rem never leak into the version string / release path (same fix in the template).
set VERSION=
for /f "tokens=2 delims==" %%a in ('findstr /b /c:"VERSION = " src\main.py') do set VERSION=%%a
for /f "tokens=1" %%a in ("%VERSION:"=%") do set VERSION=%%a
if not defined VERSION (
  echo [ERROR] Cannot read VERSION from src\main.py.
  if not defined NOPAUSE pause
  call :drop_data_dir
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
  call :drop_data_dir
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem Running-instance guard (D1-02, refined 2026-09-19).
rem History: this gate used to refuse whenever ANY instance was running. Because
rem D1-01 (same-version release dir already exists) is checked FIRST, that form's
rem only real effect was blocking harmless builds of OTHER versions. What is
rem actually unsafe is deleting/overwriting the directory a live instance runs
rem from - so the judgement is directory equality, not 'is an instance running'.
rem NOTE: the 'block' branch below is belt-and-braces - D1-01 already rejects in
rem exactly the case where a live instance could be inside the target dir.
rem The same guard must precede any manual rm/rmdir of a release dir.
rem ---------------------------------------------------------------------------
set "RUNNING_EXE="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Process -Name %APPNAME% -ErrorAction SilentlyContinue).Path | Select-Object -First 1"`) do set "RUNNING_EXE=%%p"
set "RUNNING_DIR="
rem goto-based on purpose: with no %APPNAME%.exe running the probe above yields nothing,
rem and the one-liner form used here before -
rem   if defined RUNNING_DIR if "%RUNNING_DIR:~-1%"=="\" set "RUNNING_DIR=%RUNNING_DIR:~0,-1%"
rem - expands to garbage when the variable is UNDEFINED and cmd aborts the whole script
rem with "The syntax of the command is incorrect." before the tasklist fallback below
rem can run. That is the state on every clean machine and every CI runner, i.e. the
rem build could only ever work on a box where the tray was already up. %%~dpd keeps a
rem trailing backslash; "path\." + %%~f is the standard way to drop it without a
rem string comparison.
if not defined RUNNING_EXE goto :running_dir_ready
for %%d in ("%RUNNING_EXE%") do set "RUNNING_DIR=%%~dpd"
for %%d in ("%RUNNING_DIR%.") do set "RUNNING_DIR=%%~fd"
:running_dir_ready
set "TARGET_DIR="
for %%d in ("%CD%\%RELEASE_DIR%") do set "TARGET_DIR=%%~fd"
if defined RUNNING_DIR if /i "%RUNNING_DIR%"=="%TARGET_DIR%" (
  echo [ERROR] A %APPNAME% instance is running FROM %RELEASE_DIR%.
  echo [ERROR] Exit it from the tray before building that directory.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if defined RUNNING_DIR echo [INFO] %APPNAME% running from "%RUNNING_DIR%" - not the target dir, build continues.
if not defined RUNNING_EXE (
  tasklist /fo csv 2>nul | findstr /i /c:"%APPNAME%.exe" >nul
  if not errorlevel 1 echo [WARN] %APPNAME%.exe is running but its path could not be read; target dir not verified.
)

rem ---------------------------------------------------------------------------
call :mktools
if errorlevel 1 (
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

echo [TEST] unit tests + settings matrix ...
"%PY%" tests\test_helper.py
if errorlevel 1 (
  echo [ERROR] test_helper.py failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

echo [TEST] baseline snapshot ...
"%PY%" tests\test_baseline.py
if errorlevel 1 (
  echo [ERROR] test_baseline.py failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
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
  call :drop_data_dir
  exit /b 1
)
if exist "%TEST_LOGS%\i18n-test.log" type "%TEST_LOGS%\i18n-test.log"

echo [TEST] API key field - load + mask + reveal ...
"%PY%" tests\test_key_field.py
if errorlevel 1 (
  echo [ERROR] test_key_field.py failed. See %TEST_LOGS%\key-field-test.log
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if exist "%TEST_LOGS%\key-field-test.log" type "%TEST_LOGS%\key-field-test.log"

echo [TEST] settings window UI test ...
"%PY%" tests\test_settings_ui.py
if errorlevel 1 (
  echo [ERROR] test_settings_ui.py failed. See %TEST_LOGS%\settings-ui-test.log
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if exist "%TEST_LOGS%\settings-ui-test.log" type "%TEST_LOGS%\settings-ui-test.log"

echo [TEST] theme consistency - no shift, no unreadable text ...
"%PY%" tests\test_theme_ui.py
if errorlevel 1 (
  echo [ERROR] test_theme_ui.py failed. See %TEST_LOGS%\theme-test.log
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if exist "%TEST_LOGS%\theme-test.log" type "%TEST_LOGS%\theme-test.log"

echo [TEST] english mode scan ...
"%PY%" tests\test_en_mode.py
if errorlevel 1 (
  echo [ERROR] test_en_mode.py failed. See %TEST_LOGS%\en-mode-test.log
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if exist "%TEST_LOGS%\en-mode-test.log" type "%TEST_LOGS%\en-mode-test.log"

echo [TEST] console lifecycle - language and theme rebuilds ...
"%PY%" tests\test_console_lifecycle.py
if errorlevel 1 (
  echo [ERROR] test_console_lifecycle.py failed. See %TEST_LOGS%\console-lifecycle-test.log
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if exist "%TEST_LOGS%\console-lifecycle-test.log" type "%TEST_LOGS%\console-lifecycle-test.log"

echo [TEST] update bat success/failure injection ...
"%PY%" tests\test_update_bat.py
if errorlevel 1 (
  echo [ERROR] update bat test failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

echo [TEST] ReMe supported-version pin (four states + prompts) ...
"%PY%" tests\test_reme_version_pin.py
if errorlevel 1 (
  echo [ERROR] ReMe version pin test failed - check that SUPPORTED_REME_VERSION is the
  echo         single source in appconfig and that both prompts pin ==that version.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

echo [TEST] quit path fail-open (dialog unusable must not lock the user in) ...
"%PY%" tests\test_quit_failopen.py
if errorlevel 1 (
  echo [ERROR] Quit fail-open test failed - a broken dialog chain must NOT trap the user.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

if exist "%STAGING%" rmdir /s /q "%STAGING%"

echo [BUILD] icon ...
rem Generate separate state/tray and small-frame-optimised taskbar assets.
"%PY%" src\main.py --make-icon
if errorlevel 1 (
  echo [ERROR] icon generation failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

rem W-f: the i18n word-pair data file (pairs.json) must ship inside the
rem package - frozen i18n loads it from _internal\modules\i18n\.
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
  --add-data "%CD%\src\modules\i18n\pairs.json;modules/i18n" ^
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
  call :drop_data_dir
  exit /b 1
)

echo [PACK] assembling %RELEASE_DIR% ...
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
robocopy "%STAGING%\%APPNAME%" "%RELEASE_DIR%" /E /R:1 /W:1 /NFL /NDL /NP >nul
if errorlevel 8 (
  echo [ERROR] Package copy failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
rem Both READMEs ship: README.md is the canonical English one and README.zh-CN.md is
rem what most users here open. Copying only the English one left the Chinese reader
rem with the English file (each links to the other at the top, so a missing sibling
rem is a dead end). The pair is intentional - see 1.1.2 in CHANGELOG.
copy /y README.md "%RELEASE_DIR%\README.md" >nul
copy /y README.zh-CN.md "%RELEASE_DIR%\README.zh-CN.md" >nul
if not exist "%RELEASE_DIR%\README.zh-CN.md" (
  echo [ERROR] README.zh-CN.md was not copied into %RELEASE_DIR%.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
copy /y LICENSE "%RELEASE_DIR%\LICENSE" >nul
xcopy /e /i /y "doc" "%RELEASE_DIR%\doc" >nul
if errorlevel 1 (
  echo [ERROR] doc copy failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

rem A release ships a template config, never the developer's live config.json:
rem the live one holds the LLM/embedding keys and the user's own targets.
"%PY%" scripts\make_release_config.py "%RELEASE_DIR%\config.json"
if errorlevel 1 (
  echo [ERROR] make_release_config.py failed.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)

rem Deliverable checks: exe + integration doc. The app looks in doc first and
rem then in _internal\doc, so both layouts remain covered.
if not exist "%FROZEN_EXE%" (
  echo [ERROR] %APPNAME%.exe missing from the release.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
rem Guard against a silently empty package: --name and the robocopy source must
rem stay in step. If they ever drift, robocopy copies nothing and still returns
rem below 8, so the zip would ship with the exe and no runtime at all.
if not exist "%RELEASE_DIR%\_internal\base_library.zip" (
  echo [ERROR] _internal has no runtime - the package is incomplete.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
rem Tcl/Tk runtime (D2-02 / C-31). No smoke check can see this: nothing in smoke()
rem creates a Tk object, and Tcl is only read on the FIRST tkinter.Tk() - so a package
rem missing tcl can pass every gate and still die in the user's hands with
rem "Can't find a usable init.tcl". These three files are what the user saw missing
rem once the package had been damaged (a stray rm -rf took the whole _internal with
rem it), so the check exists to catch a damaged/incomplete package, not to fix a
rem packaging omission - all four tools ship them today.
if not exist "%RELEASE_DIR%\_internal\_tkinter.pyd" (
  echo [ERROR] Tk runtime missing: _internal\_tkinter.pyd
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\tcl86t.dll" (
  echo [ERROR] Tk runtime missing: _internal\tcl86t.dll
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\_tcl_data" (
  echo [ERROR] Tk runtime missing: _internal\_tcl_data
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if not exist "%RELEASE_DIR%\doc\zh\setup.md" (
  echo [ERROR] integration doc missing from the release.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if not exist "%RELEASE_DIR%\doc\capture.mjs" (
  echo [ERROR] capture script missing from the release.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if not exist "%RELEASE_DIR%\doc\capture_cc.mjs" (
  echo [ERROR] Claude Code capture script missing from the release.
  if not defined NOPAUSE pause
  call :drop_data_dir
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\reme-helper-taskbar.ico" (
  echo [ERROR] taskbar icon asset missing from the release.
  if not defined NOPAUSE pause
  call :drop_data_dir
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
  call :drop_data_dir
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

call :drop_data_dir

echo [DONE] release: %FROZEN_EXE%
rem The launched app INHERITS REME_HELPER_DATA_DIR and recreates it the moment it
rem writes a log line, so the drop above is not enough. Wait, then drop again:
rem   * app exited by itself - a second instance bows out with "already running"
rem     within about six seconds - so the directory is gone and nothing is left;
rem   * app still up - nobody else was running - rmdir fails and that directory
rem     now belongs to the running app, not to the build. Deleting it underneath
rem     a live instance would be worse than leaving it.
rem The wait below is a REAL sleep, not `ping -n 9`: ping's "one second" only holds
rem while loopback ICMP answers, and where it is dropped every packet waits out the
rem timeout - measured 9.0s per tick instead of 1s (C-33). `timeout`/`choice` are
rem not alternatives: they need a console this build may not have. Absolute path
rem for the same PATH reason as everywhere else in this file.
if defined RUN_AFTER (
  echo [RUN] starting %APPNAME%.exe ...
  start "" "%FROZEN_EXE%"
  %SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "Start-Sleep -Milliseconds 8000"
  call :drop_data_dir
  if exist "%REME_HELPER_DATA_DIR%" echo [INFO] %APPNAME%.exe is still running - the data dir belongs to it now.
  rem Explained above, so do not let the subroutine's WARN turn the build red: here a
  rem survivor is the documented, intended outcome.
  set "DROP_DATA_FAILED="
)
rem With no launched instance nothing can legitimately hold this directory open, so a
rem survivor is a real leftover - red, not a warning (harness rule: after a run, zero
rem family-signature temp dirs, empty ones included).
if not defined RUN_AFTER if defined DROP_DATA_FAILED (
  echo [ERROR] %REME_HELPER_DATA_DIR% could not be removed - leftover temp dir.
  if not defined NOPAUSE pause
  exit /b 1
)
if not defined NOPAUSE pause
exit /b 0

rem ---------------------------------------------------------------------------
rem drop_data_dir: remove the isolated data root this build created.
rem
rem The build pins REME_HELPER_DATA_DIR (see the top of this file) so the suites
rem and the frozen self-checks cannot read or write the user's real
rem %LOCALAPPDATA%. Nothing ever removed it, so every build left a folder behind
rem in %TEMP% - a leak by the harness rule (after a run: zero family-signature
rem temp dirs, empty ones included). Called on the way out of every exit path.
rem ---------------------------------------------------------------------------
:drop_data_dir
rem Read back AFTER deleting. The old body was `rmdir /s /q ... 2>nul` with no check at
rem all, so "the directory survived" and "the directory was removed" produced the same
rem output: nothing. That is the exact gap C-30 names - cleanup that ran vs cleanup that
rem succeeded - and this root sits in %TEMP%, where a survivor stays forever.
rem Not fatal inside this subroutine on purpose: in the RUN_AFTER flow the launched app
rem owns the directory by design (it inherits the env var and rewrites its log), and the
rem caller states that. Every other path reports it.
if not exist "%REME_HELPER_DATA_DIR%" goto drop_data_dir_clean
rmdir /s /q "%REME_HELPER_DATA_DIR%" 2>nul
if not exist "%REME_HELPER_DATA_DIR%" goto drop_data_dir_clean
echo [WARN] %REME_HELPER_DATA_DIR% survived the delete (open handle or a live instance?).
set "DROP_DATA_FAILED=1"
goto :eof
:drop_data_dir_clean
set "DROP_DATA_FAILED="
goto :eof

rem ---------------------------------------------------------------------------
rem release_failed: the packaged self-check said no; never publish this build
rem ---------------------------------------------------------------------------
:release_failed
echo [ERROR] --release check failed. See %RELEASE_DIR%\log\release.log
if exist "%RELEASE_DIR%\log\release.log" type "%RELEASE_DIR%\log\release.log"
if not defined NOPAUSE pause
call :drop_data_dir
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
call :drop_data_dir
exit /b 1

:ui_failed
echo [ERROR] UI check failed. See %RELEASE_DIR%\log\ui-check.log
if exist "%RELEASE_DIR%\log\ui-check.log" type "%RELEASE_DIR%\log\ui-check.log"
if not defined NOPAUSE pause
call :drop_data_dir
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
  call :drop_data_dir
  exit /b 1
)

:mktools_use
echo [SETUP] installing build requirements ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements.txt
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet pyinstaller
if errorlevel 1 (
  echo [ERROR] pip install failed.
  call :drop_data_dir
  exit /b 1
)
echo [SETUP] using %VENV%\Scripts\python.exe for this build
set PY=%VENV%\Scripts\python.exe
exit /b 0
