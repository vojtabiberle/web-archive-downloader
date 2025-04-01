import pytest
import json
import sys
from unittest.mock import patch
import os
from io import StringIO

# Add project root to sys.path to allow importing project modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

import config_loader
import constants

def test_load_config_valid(tmp_path):
    """Tests loading a valid configuration file."""
    valid_config_data = {
        "target_domain": "example.com",
        "output_dir": "test_output",
        "content_selectors": ["main", ".content"],
        "request_delay_seconds": 1,
        "max_retries": 5,
        "user_agent": "TestAgent/1.0",
        "checkpoint_file": "test_checkpoint.json",
        "log_file": "test_scraping.log",
        "cdx_api_url": "http://test-cdx-server.com/cdx",
        # Optional keys to test defaults are NOT applied if present
        "request_timeout_api": 20,
        "request_timeout_content": 40,
        "download_js": True,
        "download_css": True,
        "download_images": True,
        "save_original_html": True,
        "rewrite_asset_links": False,
        "asset_save_structure": "per_page"
    }
    config_file = tmp_path / "valid_config.json"
    config_file.write_text(json.dumps(valid_config_data))

    loaded_config = config_loader.load_config(str(config_file))

    # Assert all required keys are present and match
    for key, value in valid_config_data.items():
        assert key in loaded_config
        assert loaded_config[key] == value

    # Assert defaults for any keys *not* provided in the minimal valid file
    # (In this case, all keys were provided, so this check is less relevant here,
    # but good practice for tests with minimal configs)
    assert loaded_config.get('request_timeout_api') == 20 # Check it wasn't overwritten by default
    assert loaded_config.get('request_timeout_content') == 40 # Check it wasn't overwritten by default
    assert loaded_config.get('download_js') is True
    assert loaded_config.get('download_css') is True
    assert loaded_config.get('download_images') is True
    assert loaded_config.get('save_original_html') is True
    assert loaded_config.get('rewrite_asset_links') is False
    assert loaded_config.get('asset_save_structure') == 'per_page'


# Remove stderr/exit mocks, expect ValueError directly
def test_load_config_missing_required_key(tmp_path):
    """Tests loading a config file missing a required key raises ValueError."""
    invalid_config_data = {
        # Missing "target_domain"
        "output_dir": "test_output",
        "content_selectors": ["main"],
        "request_delay_seconds": 1,
        "max_retries": 5,
        "user_agent": "TestAgent/1.0",
        "checkpoint_file": "test_checkpoint.json",
        "log_file": "test_scraping.log",
        "cdx_api_url": "http://test-cdx-server.com/cdx"
    }
    config_file = tmp_path / "missing_key_config.json"
    config_file.write_text(json.dumps(invalid_config_data))

    with pytest.raises(ValueError) as e:
        config_loader.load_config(str(config_file))

    # Check the exception message
    assert "missing required keys: target_domain" in str(e.value)


# Expect ValueError for invalid JSON
def test_load_config_invalid_json(tmp_path):
    """Tests loading a file with invalid JSON raises ValueError."""
    invalid_json_content = '{"target_domain": "example.com", "output_dir": "test_output", ...' # Malformed JSON
    config_file = tmp_path / "invalid_json.json"
    config_file.write_text(invalid_json_content)

    with pytest.raises(ValueError) as e:
        config_loader.load_config(str(config_file))

    # Check the exception message (should mention decoding error)
    assert "Error decoding JSON" in str(e.value)


def test_load_config_defaults(tmp_path):
    """Tests that default values are applied for missing optional keys."""
    minimal_config_data = {
        "target_domain": "example.com",
        "output_dir": "test_output",
        "content_selectors": ["main"],
        "request_delay_seconds": 1, # Provide some required, check defaults for others
        "max_retries": 5,
        "user_agent": "TestAgent/1.0",
        "checkpoint_file": "test_checkpoint.json",
        "log_file": "test_scraping.log",
        "cdx_api_url": "http://test-cdx-server.com/cdx"
        # Missing optional keys like timeouts, download flags etc.
    }
    config_file = tmp_path / "defaults_config.json"
    config_file.write_text(json.dumps(minimal_config_data))

    loaded_config = config_loader.load_config(str(config_file))

    # Assert required keys are still present
    assert loaded_config['target_domain'] == "example.com"

    # Assert defaults were applied for missing optional keys
    assert loaded_config['request_timeout_api'] == constants.DEFAULT_TIMEOUT_API
    assert loaded_config['request_timeout_content'] == constants.DEFAULT_TIMEOUT_CONTENT
    assert loaded_config['download_js'] is False # Default
    assert loaded_config['download_css'] is False # Default
    assert loaded_config['download_images'] is False # Default
    assert loaded_config['save_original_html'] is False # Default
    assert loaded_config['rewrite_asset_links'] is True # Default
    assert loaded_config['asset_save_structure'] == 'per_page' # Default


# Expect ValueError for invalid value type
def test_load_config_invalid_value_type(tmp_path):
    """Tests loading a config file with an invalid value type raises ValueError."""
    invalid_config_data = {
        "target_domain": "example.com",
        "output_dir": "test_output",
        "content_selectors": ["main"],
        "request_delay_seconds": -1, # Invalid value
        "max_retries": 5,
        "user_agent": "TestAgent/1.0",
        "checkpoint_file": "test_checkpoint.json",
        "log_file": "test_scraping.log",
        "cdx_api_url": "http://test-cdx-server.com/cdx"
    }
    config_file = tmp_path / "invalid_value_config.json"
    config_file.write_text(json.dumps(invalid_config_data))

    # Expect ValueError for invalid value type
    with pytest.raises(ValueError) as e:
        config_loader.load_config(str(config_file))

    # Check the exception message
    assert "Config 'request_delay_seconds' must be a non-negative number." in str(e.value)


# Expect FileNotFoundError
def test_load_config_file_not_found():
    """Tests loading a non-existent config file raises FileNotFoundError."""
    non_existent_path = "non_existent_config.json"

    # Ensure the file does not exist before the test
    if os.path.exists(non_existent_path):
        os.remove(non_existent_path)

    # Expect FileNotFoundError directly
    with pytest.raises(FileNotFoundError):
        config_loader.load_config(non_existent_path)

# --- All config_loader tests updated ---