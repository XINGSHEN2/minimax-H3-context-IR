from backend.agent import reasoning_provider_config


def test_default_reasoning_provider_is_deepseek_litellm(monkeypatch):
    monkeypatch.delenv("CONTEXT_IR_LLM_PROVIDER", raising=False)

    config = reasoning_provider_config()

    assert config == {
        "selection": "deepseek_litellm",
        "name": "DeepSeek via LiteLLM",
        "provider_id": "deepseek_litellm",
        "model": "deepseek-v4-flash",
        "base_url": "http://litellm-poc.pgw.metax-tech.com/v1",
        "api_key_env": "LITELLM_API_KEY",
        "http_host_env": "",
    }


def test_official_deepseek_provider_is_preserved(monkeypatch):
    monkeypatch.setenv("CONTEXT_IR_LLM_PROVIDER", "deepseek")

    config = reasoning_provider_config()

    assert config["selection"] == "deepseek"
    assert config["base_url"] == "https://api.deepseek.com"
    assert config["api_key_env"] == "DEEPSEEK_API_KEY"
    assert config["model"] == "deepseek-v4-flash"


def test_litellm_provider_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CONTEXT_IR_LLM_PROVIDER", "deepseek_litellm")
    monkeypatch.setenv("DEEPSEEK_LITELLM_RESPONSES_BASE_URL", "http://proxy.example/v1")
    monkeypatch.setenv("DEEPSEEK_LITELLM_MODEL", "custom-deepseek")

    config = reasoning_provider_config()

    assert config["base_url"] == "http://proxy.example/v1"
    assert config["model"] == "custom-deepseek"
