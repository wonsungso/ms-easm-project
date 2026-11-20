import os
from pathlib import Path


def state_path(root: Path, *parts: str) -> Path:
    override = os.environ.get("EASM_AGENT_STATE_DIR")
    if override is None:
        directory = root / ".easm-agent"
    else:
        directory = Path(override)
        if not directory.is_absolute():
            raise ValueError("EASM_AGENT_STATE_DIR에는 절대 경로가 필요합니다.")
    return directory.joinpath(*parts)
