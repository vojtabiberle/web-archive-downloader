# tests/test_memento_client.py

import pytest
import requests
import logging
import json
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

# Modules to test
from api_clients import memento_client
import constants # Import constants used in the module

# Functions under test (mocked)
from html_processor import extract_and_convert_content
from file_handler import save_markdown, save_checkpoint

# --- Fixtures ---

@pytest.fixture
def mock_config():
    """Provides a basic mock config dictionary."""
    return {
        'user_agent': 'Test Memento Agent',
        'request_timeout_api': 3,
        'request_timeout_content': 8,
        'max_retries': 2,
        'retry_delay_seconds': 0.1, # Faster retries for testing
        'output_dir': 'test_output',
        'checkpoint_file': 'test_checkpoint.json',
        'content_selectors': ['body'] # Add this line
    }

@pytest.fixture
def mock_response():
    """Creates a reusable MagicMock for requests.Response."""
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.content = b"Sample content"
    response.text = "Sample text"
    response.encoding = 'utf-8'
    response.url = "http://mocked.url"
    response.json = MagicMock() # Mock json method
    response.close = MagicMock()
    response.raise_for_status = MagicMock()
    return response

@pytest.fixture
def mock_processed_urls_set():
    """Provides an empty set for tracking processed URLs."""
    return set()

# --- Tests for fetch_memento_snapshot ---

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_success_with_wayback_ts(mock_get, mock_config, mock_response, caplog):
    """Test successful Memento snapshot retrieval using Wayback timestamp."""
    original_url = "http://example.com/page"
    wayback_timestamp = "20230101120000"
    expected_memento_uri = "http://memento.example.org/snap/1"
    mock_response.json.return_value = {
        "mementos": {
            "closest": {
                "uri": [expected_memento_uri]
            }
        }
    }
    mock_get.return_value = mock_response
    expected_api_url = f"{constants.MEMENTO_API_BASE_URL}{wayback_timestamp}/{original_url}"

    with caplog.at_level(logging.INFO):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri == expected_memento_uri
    mock_get.assert_called_once_with(
        expected_api_url,
        headers={'User-Agent': mock_config['user_agent']},
        timeout=mock_config['request_timeout_api']
    )
    assert f"Querying Memento API: {expected_api_url}" in caplog.text
    assert f"Found potential Memento URI: {expected_memento_uri}" in caplog.text
    mock_response.close.assert_called_once()
    mock_response.json.assert_called_once()

@patch('api_clients.memento_client.requests.get')
@patch('api_clients.memento_client.datetime')
def test_fetch_memento_snapshot_success_without_wayback_ts(mock_datetime, mock_get, mock_config, mock_response, caplog):
    """Test successful Memento snapshot retrieval using current time."""
    original_url = "http://example.com/another"
    current_time = datetime(2024, 4, 1, 10, 30, 0)
    current_ts_str = "20240401103000"
    mock_datetime.now.return_value = current_time
    expected_memento_uri = "http://memento.example.org/snap/2"
    mock_response.json.return_value = {
        "mementos": {
            "closest": {
                "uri": [expected_memento_uri]
            }
        }
    }
    mock_get.return_value = mock_response
    expected_api_url = f"{constants.MEMENTO_API_BASE_URL}{current_ts_str}/{original_url}"

    with caplog.at_level(logging.INFO):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config) # No timestamp passed

    assert memento_uri == expected_memento_uri
    mock_get.assert_called_once_with(
        expected_api_url,
        headers={'User-Agent': mock_config['user_agent']},
        timeout=mock_config['request_timeout_api']
    )
    assert f"Querying Memento API: {expected_api_url}" in caplog.text
    assert f"Found potential Memento URI: {expected_memento_uri}" in caplog.text
    mock_response.close.assert_called_once()
    mock_response.json.assert_called_once()

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_returns_archive_org_uri(mock_get, mock_config, mock_response, caplog):
    """Test that Memento URIs pointing to web.archive.org are skipped."""
    original_url = "http://example.com/loop"
    wayback_timestamp = "20230101120000"
    archive_org_uri = "https://web.archive.org/web/20230101id_/http://example.com/loop"
    mock_response.json.return_value = {
        "mementos": {
            "closest": {
                "uri": [archive_org_uri]
            }
        }
    }
    mock_get.return_value = mock_response

    with caplog.at_level(logging.WARNING):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri is None
    assert f"Memento API returned a web.archive.org URI ({archive_org_uri}). Skipping fallback to avoid loop." in caplog.text
    mock_get.assert_called_once()
    mock_response.close.assert_called_once()
    mock_response.json.assert_called_once()

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_not_found_404(mock_get, mock_config, mock_response, caplog):
    """Test Memento snapshot retrieval when API returns 404."""
    original_url = "http://example.com/notfound"
    wayback_timestamp = "20230101120000"
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error")
    mock_get.return_value = mock_response

    with caplog.at_level(logging.WARNING):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri is None
    assert f"Memento API returned 404 for {original_url} at timestamp {wayback_timestamp}" in caplog.text
    mock_get.assert_called_once() # Decorator should not retry on 404
    mock_response.close.assert_called_once()
    mock_response.json.assert_not_called() # No JSON processing on 404

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_retry_success(mock_get, mock_config, mock_response, caplog):
    """Test Memento snapshot retrieval succeeds after a retryable error."""
    original_url = "http://example.com/retry"
    wayback_timestamp = "20230101120000"
    expected_memento_uri = "http://memento.example.org/snap/3"

    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 503
    fail_response.url = "http://mocked.url/fail"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("503 Server Error", response=fail_response)

    success_response = mock_response
    success_response.json.return_value = {
        "mementos": {"closest": {"uri": [expected_memento_uri]}}
    }

    mock_get.side_effect = [fail_response, success_response]

    with caplog.at_level(logging.INFO): # Changed WARNING to INFO
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri == expected_memento_uri
    assert mock_get.call_count == 2
    assert f"Memento API request failed with status 503. Decorator will handle retry." in caplog.text
    assert f"Found potential Memento URI: {expected_memento_uri}" in caplog.text
    fail_response.close.assert_called_once()
    success_response.close.assert_called_once()

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_retry_fails(mock_get, mock_config, caplog):
    """Test Memento snapshot retrieval fails after exhausting retries."""
    original_url = "http://example.com/failalways"
    wayback_timestamp = "20230101120000"

    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 500
    fail_response.url = "http://mocked.url/fail_always"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error", response=fail_response)

    max_attempts = mock_config['max_retries'] + 1
    mock_get.side_effect = [fail_response] * max_attempts

    with caplog.at_level(logging.ERROR):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri is None
    assert mock_get.call_count == max_attempts
    assert f"Request failed for http://example.com/failalways... after {mock_config['max_retries']} retries. Last exception: 500 Server Error" in caplog.text
    assert fail_response.close.call_count == max_attempts # Called in func finally + decorator on last fail

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_request_exception(mock_get, mock_config, caplog):
    """Test Memento snapshot retrieval handles requests.exceptions.RequestException."""
    original_url = "http://example.com/timeout"
    wayback_timestamp = "20230101120000"
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
    max_attempts = mock_config['max_retries'] + 1

    with caplog.at_level(logging.ERROR):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri is None
    assert mock_get.call_count == max_attempts
    # Check the final error log from the decorator after retries are exhausted
    expected_api_url = f"{constants.MEMENTO_API_BASE_URL}{wayback_timestamp}/{original_url}"
    assert f"Request failed for http://example.com/timeout... after {mock_config['max_retries']} retries. Last exception: Connection timed out" in caplog.text

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_invalid_json(mock_get, mock_config, mock_response, caplog):
    """Test Memento snapshot retrieval handles invalid JSON response."""
    original_url = "http://example.com/badjson"
    wayback_timestamp = "20230101120000"
    mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
    mock_response.text = "This is not JSON"
    mock_get.return_value = mock_response

    with caplog.at_level(logging.ERROR):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri is None
    assert "Failed to decode JSON response from Memento API" in caplog.text
    mock_get.assert_called_once()
    mock_response.close.assert_called_once()
    mock_response.json.assert_called_once()

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_missing_keys(mock_get, mock_config, mock_response, caplog):
    """Test Memento snapshot retrieval handles missing keys in JSON response."""
    original_url = "http://example.com/missingkeys"
    wayback_timestamp = "20230101120000"
    test_cases = [
        {},
        {"mementos": {}},
        {"mementos": {"closest": {}}},
        {"mementos": {"closest": {"uri": []}}}, # Empty list
        {"mementos": {"closest": {"uri": "not_a_list"}}},
    ]
    mock_get.return_value = mock_response

    for invalid_data in test_cases:
        mock_response.json.return_value = invalid_data
        mock_response.json.reset_mock()
        mock_response.close.reset_mock()
        caplog.clear()

        mock_get.reset_mock() # Reset mock before each iteration

        with caplog.at_level(logging.WARNING):
            memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

        assert memento_uri is None
        assert "did not contain a usable closest memento URI" in caplog.text
        mock_get.assert_called_once()
        mock_response.close.assert_called_once()
        mock_response.json.assert_called_once()

@patch('api_clients.memento_client.requests.get')
def test_fetch_memento_snapshot_unhandled_client_error(mock_get, mock_config, mock_response, caplog):
    """Test Memento snapshot retrieval handles unhandled 4xx client errors."""
    original_url = "http://example.com/clienterror"
    wayback_timestamp = "20230101120000"
    mock_response.status_code = 401 # Unauthorized, not in non_retryable_status
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Client Error")
    mock_get.return_value = mock_response

    with caplog.at_level(logging.ERROR):
        memento_uri = memento_client.fetch_memento_snapshot(original_url, config=mock_config, wayback_timestamp=wayback_timestamp)

    assert memento_uri is None
    assert "Memento API request failed with unhandled client error 401" in caplog.text
    mock_get.assert_called_once() # Should not retry
    mock_response.close.assert_called_once()
    mock_response.json.assert_not_called()


# --- Tests for fetch_and_process_memento_content ---

# Mock dependencies for fetch_and_process_memento_content
@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_success(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                       mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test successful fetching, processing, and saving of Memento content."""
    memento_uri = "http://memento.example.org/snap/success"
    original_url = "http://example.com/original_success"
    mock_response.text = "<html><body>Memento Content</body></html>"
    mock_get.return_value = mock_response
    mock_extract.return_value = ("Test Title", "# Markdown Content")
    mock_save_md.return_value = True # Simulate successful save

    with caplog.at_level(logging.INFO):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is True
    mock_get.assert_called_once_with(
        memento_uri,
        headers={'User-Agent': mock_config['user_agent']},
        timeout=mock_config['request_timeout_content']
    )
    mock_extract.assert_called_once_with(mock_response.text, original_url, mock_config, saved_assets_map={})
    mock_save_md.assert_called_once()
    # Check args for save_markdown (title, content, url, timestamp, config) - timestamp is tricky
    args, kwargs = mock_save_md.call_args
    assert args[0] == "Test Title"
    assert args[1] == "# Markdown Content"
    assert args[2] == original_url
    assert isinstance(args[3], str) and len(args[3]) == 14 # Check timestamp format
    assert args[4] == mock_config

    mock_save_cp.assert_called_once_with(original_url, mock_processed_urls_set, mock_config['checkpoint_file'])
    assert f"Successfully fetched HTML from Memento URI: {memento_uri}" in caplog.text
    assert f"Successfully saved content retrieved via Memento ({memento_uri})" in caplog.text
    mock_response.close.assert_called_once()

@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_non_retryable_fail(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                                  mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test failure on non-retryable status codes (404, 403)."""
    memento_uri = "http://memento.example.org/snap/forbidden"
    original_url = "http://example.com/original_forbidden"
    mock_response.status_code = 403
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("403 Client Error")
    mock_get.return_value = mock_response

    with caplog.at_level(logging.WARNING):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is False
    mock_get.assert_called_once() # Decorator should not retry
    assert f"Memento URI request failed with non-retryable status 403: {memento_uri}" in caplog.text
    mock_extract.assert_not_called()
    mock_save_md.assert_not_called()
    mock_save_cp.assert_not_called()
    mock_response.close.assert_called_once()

@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_retry_success(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                             mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test successful processing after a retryable error."""
    memento_uri = "http://memento.example.org/snap/retry_content"
    original_url = "http://example.com/original_retry"

    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 500
    fail_response.url = "http://mocked.url/fail_content"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error", response=fail_response)

    success_response = mock_response
    success_response.text = "<html>Retry Content</html>"
    mock_extract.return_value = ("Retry Title", "# Retry MD")
    mock_save_md.return_value = True

    mock_get.side_effect = [fail_response, success_response]

    with caplog.at_level(logging.INFO):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is True
    assert mock_get.call_count == 2
    assert f"Memento content request failed with status 500. Decorator will handle retry." in caplog.text
    assert f"Successfully fetched HTML from Memento URI: {memento_uri}" in caplog.text
    mock_extract.assert_called_once()
    mock_save_md.assert_called_once()
    mock_save_cp.assert_called_once()
    fail_response.close.assert_called_once()
    success_response.close.assert_called_once()


@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_retry_fails(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                           mock_config, mock_processed_urls_set, caplog):
    """Test failure after exhausting retries for content fetching."""
    memento_uri = "http://memento.example.org/snap/fail_content_always"
    original_url = "http://example.com/original_fail_always"

    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 502
    fail_response.url = "http://mocked.url/fail_content_always"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("502 Server Error", response=fail_response)

    max_attempts = mock_config['max_retries'] + 1
    mock_get.side_effect = [fail_response] * max_attempts

    with caplog.at_level(logging.ERROR):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is False
    assert mock_get.call_count == max_attempts
    assert f"Request failed for http://memento.example.org/snap/fail_content_always... after {mock_config['max_retries']} retries. Last exception: 502 Server Error" in caplog.text
    assert fail_response.close.call_count == max_attempts # Called in func finally + decorator on last fail
    mock_extract.assert_not_called()
    mock_save_md.assert_not_called()
    mock_save_cp.assert_not_called()

@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_request_exception(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                                 mock_config, mock_processed_urls_set, caplog):
    """Test handling of requests.exceptions.RequestException during content fetch."""
    memento_uri = "http://memento.example.org/snap/timeout_content"
    original_url = "http://example.com/original_timeout"
    mock_get.side_effect = requests.exceptions.ConnectionError("Network unreachable")
    max_attempts = mock_config['max_retries'] + 1

    with caplog.at_level(logging.ERROR):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is False
    assert mock_get.call_count == max_attempts
    # Check the final error log from the decorator after retries are exhausted
    assert f"Request failed for {memento_uri}... after {mock_config['max_retries']} retries." in caplog.text
    mock_extract.assert_not_called()
    mock_save_md.assert_not_called()
    mock_save_cp.assert_not_called()

@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_empty_or_non_html(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                                 mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test handling of empty or non-HTML content from Memento URI."""
    memento_uri = "http://memento.example.org/snap/non_html"
    original_url = "http://example.com/original_non_html"
    test_contents = ["", "Just text", '{"json": true}']

    mock_get.return_value = mock_response

    for content in test_contents:
        # Use PropertyMock to set the text attribute for this iteration
        with patch('requests.Response.text', new_callable=PropertyMock) as mock_text:
            mock_text.return_value = content
            mock_get.reset_mock()
            mock_extract.reset_mock()
            mock_save_md.reset_mock()
            mock_save_cp.reset_mock()
            mock_response.close.reset_mock()
            caplog.clear()

            with caplog.at_level(logging.WARNING):
                success = memento_client.fetch_and_process_memento_content(
                    memento_uri, original_url, mock_config, mock_processed_urls_set
                )

            assert success is False
            mock_get.assert_called_once()
            assert f"Fetched empty or non-HTML content from Memento URI {memento_uri}" in caplog.text
            mock_extract.assert_not_called()
            mock_save_md.assert_not_called()
            mock_save_cp.assert_not_called()
            mock_response.close.assert_called_once()


@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_extract_fail(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                            mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test handling when extract_and_convert_content fails."""
    memento_uri = "http://memento.example.org/snap/extract_fail"
    original_url = "http://example.com/original_extract_fail"
    mock_response.text = "<html><body>Bad Content</body></html>"
    mock_get.return_value = mock_response
    mock_extract.return_value = (None, None) # Simulate extraction failure

    with caplog.at_level(logging.WARNING):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is False
    mock_get.assert_called_once()
    mock_extract.assert_called_once()
    assert f"Failed to extract/convert content from Memento source {memento_uri}" in caplog.text
    mock_save_md.assert_not_called()
    mock_save_cp.assert_not_called()
    mock_response.close.assert_called_once()

@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_save_fail(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                         mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test handling when save_markdown fails."""
    memento_uri = "http://memento.example.org/snap/save_fail"
    original_url = "http://example.com/original_save_fail"
    mock_response.text = "<html><body>Good Content</body></html>"
    mock_get.return_value = mock_response
    mock_extract.return_value = ("Save Fail Title", "# Save Fail MD")
    mock_save_md.return_value = False # Simulate save failure

    with caplog.at_level(logging.ERROR):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is False
    mock_get.assert_called_once()
    mock_extract.assert_called_once()
    mock_save_md.assert_called_once()
    assert f"Failed to save markdown derived from Memento source {memento_uri}" in caplog.text
    mock_save_cp.assert_not_called() # Checkpoint should not be saved on failure
    mock_response.close.assert_called_once()

@patch('api_clients.memento_client.save_checkpoint')
@patch('api_clients.memento_client.save_markdown')
@patch('api_clients.memento_client.extract_and_convert_content')
@patch('api_clients.memento_client.requests.get')
def test_fetch_process_memento_unhandled_client_error(mock_get, mock_extract, mock_save_md, mock_save_cp,
                                                      mock_config, mock_response, mock_processed_urls_set, caplog):
    """Test handling of unhandled client errors during content fetch."""
    memento_uri = "http://memento.example.org/snap/client_error_content"
    original_url = "http://example.com/original_client_error"
    mock_response.status_code = 418 # I'm a teapot
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("418 Client Error")
    mock_get.return_value = mock_response

    with caplog.at_level(logging.ERROR):
        success = memento_client.fetch_and_process_memento_content(
            memento_uri, original_url, config=mock_config, processed_urls_set=mock_processed_urls_set
        )

    assert success is False
    mock_get.assert_called_once() # Should not retry
    assert f"Memento content request failed with unhandled client error 418" in caplog.text
    mock_extract.assert_not_called()
    mock_save_md.assert_not_called()
    mock_save_cp.assert_not_called()
    mock_response.close.assert_called_once()