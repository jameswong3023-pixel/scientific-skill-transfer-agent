from app.config import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    s = Settings()
    assert s.openrouter_api_key == "sk-or-v1-test"
    assert s.openrouter_model == "stealth/ox-alpha"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert s.agent_max_iterations == 8
    assert s.agent_temperature == 0.0


def test_settings_never_defaults_a_real_key():
    s = Settings(openrouter_api_key="")
    assert s.openrouter_api_key == ""
