import json
import os
import pytest
from shared import config


@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    cfg_file = str(tmp_path / "config.json")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    return cfg_file


def test_load_default_config(temp_config_path):
    cfg = config.load_config()
    assert "telegram" in cfg
    assert "bot_token" in cfg["telegram"]
    assert cfg["telegram"]["allowed_user_id"] == 0
    assert "qbittorrent" in cfg
    assert "paths" in cfg
    assert os.path.exists(temp_config_path)


def test_save_and_reload_config(temp_config_path):
    cfg = config.load_config()
    cfg["telegram"]["bot_token"] = "123456:TEST_TOKEN"
    cfg["telegram"]["allowed_user_id"] = 999888
    cfg["qbittorrent"]["host"] = "http://qbit.local:8080"
    config.save_config(cfg)

    reloaded = config.load_config()
    assert reloaded["telegram"]["bot_token"] == "123456:TEST_TOKEN"
    assert reloaded["telegram"]["allowed_user_id"] == 999888
    assert reloaded["qbittorrent"]["host"] == "http://qbit.local:8080"


def test_legacy_token_migration(temp_config_path):
    legacy_data = {
        "telegram": {
            "mirror_bot_token": "legacy_token_123",
            "allowed_user_id": 555,
        }
    }
    with open(temp_config_path, "w") as f:
        json.dump(legacy_data, f)

    cfg = config.load_config()
    assert cfg["telegram"]["bot_token"] == "legacy_token_123"
    assert config.get_bot_token(cfg) == "legacy_token_123"
    assert config.get_allowed_user_id(cfg) == 555


def test_corrupted_config_fallback(temp_config_path):
    with open(temp_config_path, "w") as f:
        f.write("{ invalid json")

    cfg = config.load_config()
    assert "telegram" in cfg
    assert cfg["telegram"]["bot_token"] == ""
