@echo off
chcp 65001 > nul
cd /d "%~dp0"
where uv > nul 2>&1
if errorlevel 1 (
  echo [설치] uv 패키지 관리자를 설치합니다...
  powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
if not exist ".env" (
  copy ".env.example" ".env" > nul
  echo [안내] .env 파일을 만들었습니다. 메모장으로 열어 AI 모델 설정을 채운 뒤 다시 실행하세요.
  notepad ".env"
)
echo 제주 데이터 길잡이를 시작합니다. 준비되면 브라우저에 http://localhost:8501 이 자동으로 열립니다.
uv run --frozen jeju-data-agent ui
pause
