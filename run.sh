#!/usr/bin/env bash
# 제주 데이터 길잡이 실행(macOS/Linux). Windows는 run.bat을 더블클릭하세요.
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo "[설치] uv 패키지 관리자를 설치합니다..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[안내] .env 파일을 만들었습니다. AI 모델 설정을 채운 뒤 다시 실행하세요."
  exit 1
fi
echo "제주 데이터 길잡이: http://localhost:8501"
exec uv run --frozen jeju-data-agent ui
