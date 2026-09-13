@echo off
rem ---------------------------------------------------------------------------
rem reme-helper release: tag the current commit and push the tag.
rem
rem Pushing a v* tag is what triggers .github/workflows/release.yml, which builds
rem the Windows package, runs the packaged --release gate, and publishes the zip
rem (plus its sha256) as a GitHub Release. Nothing is built here on purpose: the
rem release artifacts must come from a clean checkout, not from this machine.
rem
rem Usage: release.bat            tag and push (asks to confirm)
rem        release.bat --dry-run   show what would happen, change nothing
rem
rem ASCII-only: cmd.exe parses .bat with the machine ANSI code page.
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"

rem Releases come from here unless the environment says otherwise.
set "RELEASE_BRANCH=main"
if defined REME_RELEASE_BRANCH set "RELEASE_BRANCH=%REME_RELEASE_BRANCH%"

set DRY_RUN=
if /i "%~1"=="--dry-run" set DRY_RUN=1

rem Version is read from src\main.py - the app and the tag can never disagree.
set VERSION=
for /f "tokens=1,2,*" %%a in ('findstr /b /c:"VERSION = " src\main.py') do set VERSION=%%~c
if not defined VERSION (
  echo [ERROR] Cannot read VERSION from src\main.py.
  exit /b 1
)
set TAG=v%VERSION%
echo [VERSION] %VERSION%   [TAG] %TAG%

rem Refuse to tag a dirty tree: the release would not match any commit.
git diff --quiet 2>nul
if errorlevel 1 (
  echo [ERROR] Working tree has uncommitted changes. Commit or stash them first.
  exit /b 1
)
git diff --cached --quiet 2>nul
if errorlevel 1 (
  echo [ERROR] Staged but uncommitted changes present. Commit them first.
  exit /b 1
)

rem A tag must point at a commit the world can already see. Both of these used to
rem be checked by hand before every release; on one occasion the local branch was
rem the thing that needed checking and nothing in this script would have caught
rem it. Compare SHAs rather than parsing "git status": the sha is the fact.
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
if /i not "%BRANCH%"=="%RELEASE_BRANCH%" (
  echo [ERROR] On branch %BRANCH%, not %RELEASE_BRANCH%. Releases are tagged on %RELEASE_BRANCH%.
  exit /b 1
)
for /f "delims=" %%l in ('git rev-parse HEAD') do set LOCAL_SHA=%%l
for /f "delims=" %%r in ('git rev-parse @{u}') do set REMOTE_SHA=%%r
if not defined REMOTE_SHA (
  echo [ERROR] %RELEASE_BRANCH% has no upstream. Set one before releasing.
  exit /b 1
)
if not "%LOCAL_SHA%"=="%REMOTE_SHA%" (
  echo [ERROR] Local %RELEASE_BRANCH% is not what the remote has.
  echo         local  = %LOCAL_SHA%
  echo         remote = %REMOTE_SHA%
  echo         Push or pull first - a tag must point at a commit everyone can see.
  exit /b 1
)

git rev-parse -q --verify "refs/tags/%TAG%" >nul 2>nul
if not errorlevel 1 (
  echo [WARN] Tag %TAG% already exists.
  if not defined DRY_RUN (
    set /p ANSWER=Delete and recreate it? [y/N] 
    if /i not "%ANSWER%"=="y" (
      echo [STOP] Keeping the existing tag.
      exit /b 1
    )
    git tag -d "%TAG%" || exit /b 1
  )
)

if defined DRY_RUN (
  echo [DRY-RUN] would run: git tag %TAG%
  echo [DRY-RUN] would run: git push origin %TAG%
  echo [DRY-RUN] CI would then build and publish reme-helper-%VERSION%-windows-x64.zip
  exit /b 0
)

git tag "%TAG%"
if errorlevel 1 (
  echo [ERROR] Failed to create tag %TAG%.
  exit /b 1
)
echo [OK] Tag %TAG% created.

git push origin "%TAG%"
if errorlevel 1 (
  rem Brackets, not parentheses: cmd.exe does not nest-count parens inside a
  rem parenthesised if-block, so "(git remote -v)" would close the block early
  rem and turn the following "exit /b 1" into an unconditional top-level command.
  rem That made this script exit 1 on SUCCESS, after the tag had already been
  rem pushed - the worst possible failure mode for a release script.
  echo [ERROR] Failed to push %TAG%. Is the remote configured? See: git remote -v
  exit /b 1
)
echo [OK] Tag %TAG% pushed - CI is building the release.
echo      Watch it at: https://github.com/KenneLu/reme-helper/actions
