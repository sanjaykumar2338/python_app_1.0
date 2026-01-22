@echo off
REM Build Windows EXE with PyInstaller (one-folder bundle: EXE + support files)
REM Activate your venv before running this script.

where pyinstaller >nul 2>nul
if %errorlevel%==0 (
  set PYI=pyinstaller
) else (
  set PYI=py -m PyInstaller
)

%PYI% --noconfirm --onedir --windowed ^
  --name "ProbatePDFExtractor" ^
  --hidden-import pytesseract.pytesseract ^
  --hidden-import google.oauth2.service_account ^
  --collect-all gspread ^
  --collect-all google_auth_oauthlib ^
  --collect-all google.oauth2 ^
  --collect-all google.auth ^
  --collect-all googleapiclient ^
  app_gui.py
