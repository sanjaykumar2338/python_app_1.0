@echo off
REM Build Windows EXE with PyInstaller (bundles all Python libs)
REM Activate your venv before running this script.

set PYI=pyinstaller

%PYI% --noconfirm --onefile --windowed ^
  --name "ProbatePDFExtractor" ^
  --hidden-import pytesseract.pytesseract ^
  --hidden-import google.oauth2.service_account ^
  --collect-all gspread ^
  --collect-all google_auth_oauthlib ^
  --collect-all google.oauth2 ^
  --collect-all google.auth ^
  --collect-all googleapiclient ^
  app_gui.py
