"""실행 설정. `.env` 파일과 환경변수에서 읽는다(환경변수가 우선)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    jeju_project_key: str | None
    data_dir: Path
    output_dir: Path
    center_data_dir: Path | None
    max_steps: int

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        file_values = _load_dotenv(env_file or PROJECT_ROOT / ".env")

        def get(key: str, default: str = "") -> str:
            return os.environ.get(key) or file_values.get(key) or default

        data_dir = Path(get("DATA_DIR", str(PROJECT_ROOT / "data")))
        center = get("CENTER_DATA_DIR")
        return cls(
            llm_base_url=get("LLM_BASE_URL"),
            llm_model=get("LLM_MODEL"),
            # 로컬 Ollama처럼 키가 필요 없는 서버도 OpenAI 클라이언트에는 빈 값이 아닌 키가 필요하다.
            llm_api_key=get("LLM_API_KEY", "not-needed"),
            jeju_project_key=get("JEJU_DATAHUB_PROJECT_KEY") or None,
            data_dir=data_dir,
            output_dir=Path(get("OUTPUT_DIR", str(PROJECT_ROOT / "outputs"))),
            center_data_dir=Path(center) if center else None,
            max_steps=int(get("AGENT_MAX_STEPS", "14")),
        )
