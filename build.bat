@echo off
rem Thin wrapper: the real build lives in scripts\build.bat so the repository root
rem stays readable. Everything after this line is passed straight through.
rem
rem   build.bat                  tests + icon + package + verify, then start it
rem   build.bat release          the same, plus the packaged --release gate
rem   build.bat nopause          unattended (no "press any key"); used by CI
rem   build.bat clean --force    remove the build cache and built releases
call "%~dp0scripts\build.bat" %*