@echo off
chcp 65001 > nul
rem 센터 PC(GTX 1060 6GB / RAM 32GB)에서 인터넷 AI 키 없이 로컬 AI로 실행하도록 준비한다.
rem 1) Ollama 설치  2) 컨텍스트 16K 설정  3) 모델 내려받기  4) .env를 로컬 모델로 설정
cd /d "%~dp0"
set "MODEL=%~1"
if "%MODEL%"=="" set "MODEL=qwen3.5:4b"

where ollama > nul 2>&1
if errorlevel 1 (
  echo [설치] Ollama를 설치합니다...
  winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
  set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
)

rem 도구 결과가 길어 기본 컨텍스트로는 부족하다. 사용자 환경변수로 고정하고 Ollama를 다시 띄운다.
setx OLLAMA_CONTEXT_LENGTH 16384 > nul
set "OLLAMA_CONTEXT_LENGTH=16384"
taskkill /IM "ollama app.exe" /F > nul 2>&1
taskkill /IM "ollama.exe" /F > nul 2>&1
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
timeout /t 5 > nul

echo [모델] %MODEL% 내려받는 중(약 3~5GB)...
ollama pull %MODEL%
if errorlevel 1 (
  echo [오류] 모델을 받지 못했습니다. 인터넷 연결을 확인하세요.
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" > nul
powershell -NoProfile -Command ^
  "$p='.env'; $t=Get-Content $p -Encoding UTF8;" ^
  "$set=@{'LLM_BASE_URL'='http://127.0.0.1:11434/v1';'LLM_MODEL'='%MODEL%';'LLM_API_KEY'='ollama'};" ^
  "foreach($k in $set.Keys){ if($t -match ('^'+$k+'=')){ $t=$t -replace ('^'+$k+'=.*'),($k+'='+$set[$k]) } else { $t+=($k+'='+$set[$k]) } };" ^
  "Set-Content $p $t -Encoding UTF8"
echo [완료] 로컬 AI(%MODEL%)로 설정했습니다. run.bat을 실행하세요.
pause
