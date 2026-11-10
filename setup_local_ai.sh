#!/usr/bin/env bash
# 인터넷 AI 키 없이 로컬 AI(Ollama)로 실행하도록 준비한다(macOS/Linux). Windows는 setup_local_ai.bat.
# 사용: ./setup_local_ai.sh [모델]   (기본 qwen3.5:4b, 6GB GPU용)
set -euo pipefail
cd "$(dirname "$0")"
MODEL="${1:-qwen3.5:4b}"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama가 필요합니다: https://ollama.com/download 에서 설치 후 다시 실행하세요." >&2
  exit 1
fi
cat <<'NOTE'
[안내] 도구 결과가 길어 Ollama 컨텍스트를 16K로 띄워야 합니다.
  macOS 앱: launchctl setenv OLLAMA_CONTEXT_LENGTH 16384 후 Ollama 앱 재시작
  Linux 서비스: systemctl edit ollama → Environment=OLLAMA_CONTEXT_LENGTH=16384 → 재시작
NOTE
ollama pull "$MODEL"
[ -f .env ] || cp .env.example .env
for kv in "LLM_BASE_URL=http://127.0.0.1:11434/v1" "LLM_MODEL=$MODEL" "LLM_API_KEY=ollama"; do
  key="${kv%%=*}"
  if grep -q "^$key=" .env; then
    python3 - "$key" "$kv" <<'PY'
import sys, re, pathlib
key, kv = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
p.write_text(re.sub(rf"^{re.escape(key)}=.*$", kv, p.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
PY
  else
    echo "$kv" >> .env
  fi
done
echo "[완료] 로컬 AI($MODEL)로 설정했습니다. ./run.sh 를 실행하세요."
