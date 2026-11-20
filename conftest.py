import pytest


@pytest.fixture(autouse=True)
def isolate_demo_execution_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EASM_AGENT_STATE_DIR", raising=False)
    monkeypatch.delenv("EASM_AGENT_LAB_CONFIG", raising=False)
