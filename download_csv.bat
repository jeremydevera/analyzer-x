@echo off
rem The full CSV of a Stored strategies filter, built with its progress on
rem screen and saved to G:\Download\yyyy-mm-dd\ (tradingagents/csv_download.py).
rem The Backtest screen prints the exact line to paste for the filter it shows.
rem pushd: the module is found from the repo folder, whatever folder cmd is in.
setlocal
pushd "%~dp0"
".venv\Scripts\python.exe" -m tradingagents.csv_download %*
set rc=%errorlevel%
popd
exit /b %rc%
