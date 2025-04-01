# tests/test_wayback_client.py

import pytest
import requests
import logging
from unittest.mock import MagicMock, patch

# Modules to test
from api_clients import wayback_client # Corrected import

# --- Fixtures ---

@pytest.fixture
def mock_config():
    """Provides a basic mock config dictionary."""
    return {
        'user_agent': 'Test User Agent',
        'request_timeout_seconds': 5,
        'max_retries': 2,
        'retry_delay_seconds': 1
    }

@pytest.fixture
def mock_response():
    """Creates a reusable MagicMock for requests.Response."""
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.content = b"Sample asset content"
    response.text = "<html><body>Sample HTML</body></html>"
    response.encoding = 'utf-8'
    response.url = "http://mocked.url"
    # Mock the close method
    response.close = MagicMock()
    # Mock raise_for_status to potentially raise HTTPError
    response.raise_for_status = MagicMock()
    return response

# --- Tests for fetch_asset ---

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_success(mock_get, mock_config, mock_response, caplog):
    """Test successful fetching of asset content."""
    mock_response.content = b"Test asset bytes"
    mock_get.return_value = mock_response

    asset_url = "http://example.com/style.css"
    timestamp = "20230101000000"
    expected_archive_url = f"https://web.archive.org/web/{timestamp}id_/{asset_url}"

    with caplog.at_level(logging.DEBUG):
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content == b"Test asset bytes"
    mock_get.assert_called_once_with(
        expected_archive_url,
        headers={'User-Agent': mock_config['user_agent']},
        timeout=mock_config['request_timeout_seconds'],
        stream=True
    )
    assert f"Successfully fetched asset: {asset_url}" in caplog.text
    mock_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_not_found_404(mock_get, mock_config, mock_response, caplog):
    """Test fetch_asset when the asset returns a 404 status."""
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error")
    mock_get.return_value = mock_response

    asset_url = "http://example.com/not_found.jpg"
    timestamp = "20230101000000"

    with caplog.at_level(logging.WARNING):
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content is None
    assert f"Asset not found (404) on Wayback Machine" in caplog.text
    mock_get.assert_called_once() # Decorator should not retry on 404
    mock_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_retry_success(mock_get, mock_config, mock_response, caplog):
    """Test fetch_asset successfully fetches after a retryable error."""
    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 503
    fail_response.url = "http://mocked.url/fail"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("503 Server Error", response=fail_response)

    success_response = mock_response # Use the fixture for success
    success_response.content = b"Success after retry"

    # Simulate failure then success
    mock_get.side_effect = [fail_response, success_response]

    asset_url = "http://example.com/retry.js"
    timestamp = "20230101000000"

    with caplog.at_level(logging.DEBUG): # Reverted level to DEBUG
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content == b"Success after retry"
    assert mock_get.call_count == 2
    assert f"Wayback Machine asset request failed with status 503. Decorator will handle retry." in caplog.text
    assert f"Successfully fetched asset: {asset_url}" in caplog.text # Check success log
    fail_response.close.assert_called_once()
    success_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_retry_fails(mock_get, mock_config, caplog):
    """Test fetch_asset fails after exhausting retries."""
    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 500
    fail_response.url = "http://mocked.url/fail_always"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error", response=fail_response)

    # Simulate failures for all attempts (initial + retries)
    max_attempts = mock_config['max_retries'] + 1
    mock_get.side_effect = [fail_response] * max_attempts

    asset_url = "http://example.com/fail_always.css"
    timestamp = "20230101000000"

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content is None
    assert mock_get.call_count == max_attempts
    # Check the final error log from the decorator after retries are exhausted
    assert f"Request failed for {asset_url}... after {mock_config['max_retries']} retries. Last exception: 500 Server Error" in caplog.text
    assert fail_response.close.call_count == max_attempts

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_request_exception(mock_get, mock_config, caplog):
    """Test fetch_asset handles requests.exceptions.RequestException."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

    asset_url = "http://example.com/timeout.png"
    timestamp = "20230101000000"
    max_attempts = mock_config['max_retries'] + 1

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content is None
    assert mock_get.call_count == max_attempts
    # Check the final error log from the decorator after retries are exhausted
    assert f"Request failed for {asset_url}... after {mock_config['max_retries']} retries. Last exception: Connection timed out" in caplog.text

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_empty_content(mock_get, mock_config, mock_response, caplog):
    """Test fetch_asset handles empty but successful response."""
    mock_response.content = b"" # Empty content
    mock_get.return_value = mock_response

    asset_url = "http://example.com/empty.gif"
    timestamp = "20230101000000"

    with caplog.at_level(logging.WARNING):
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content is None
    assert "Fetched empty asset content" in caplog.text
    mock_get.assert_called_once()
    mock_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_asset_unhandled_client_error(mock_get, mock_config, mock_response, caplog):
    """Test fetch_asset handles unhandled 4xx client errors."""
    mock_response.status_code = 403 # Forbidden, not in non_retryable_status by default
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("403 Client Error")
    mock_get.return_value = mock_response

    asset_url = "http://example.com/forbidden.dat"
    timestamp = "20230101000000"

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_asset(asset_url, timestamp, config=mock_config)

    assert content is None
    assert "Wayback Machine asset request failed with unhandled client error 403" in caplog.text
    mock_get.assert_called_once() # Should not retry
    mock_response.close.assert_called_once()


# --- Tests for fetch_page_content ---

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_success(mock_get, mock_config, mock_response, caplog):
    """Test successful fetching of page HTML content."""
    mock_response.text = "<html><head><title>Test Page</title></head><body>Content</body></html>"
    mock_get.return_value = mock_response

    original_url = "http://example.com/page.html"
    timestamp = "20230101000000"
    expected_archive_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"

    with caplog.at_level(logging.DEBUG):
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content == "<html><head><title>Test Page</title></head><body>Content</body></html>"
    mock_get.assert_called_once_with(
        expected_archive_url,
        headers={'User-Agent': mock_config['user_agent']},
        timeout=mock_config['request_timeout_seconds']
    )
    assert f"Successfully fetched content for: {original_url}" in caplog.text
    mock_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_not_found_404(mock_get, mock_config, mock_response, caplog):
    """Test fetch_page_content when the page returns a 404 status."""
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error")
    mock_get.return_value = mock_response

    original_url = "http://example.com/not_found.html"
    timestamp = "20230101000000"

    with caplog.at_level(logging.WARNING):
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content is None
    assert f"Page not found (404) on Wayback Machine" in caplog.text
    mock_get.assert_called_once() # Decorator should not retry on 404
    mock_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_retry_success(mock_get, mock_config, mock_response, caplog):
    """Test fetch_page_content successfully fetches after a retryable error."""
    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 429 # Too Many Requests
    fail_response.url = "http://mocked.url/fail_page"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Client Error", response=fail_response)

    success_response = mock_response # Use the fixture for success
    success_response.text = "<html>Retry Success</html>"

    # Simulate failure then success
    mock_get.side_effect = [fail_response, success_response]

    original_url = "http://example.com/retry_page.php"
    timestamp = "20230101000000"

    with caplog.at_level(logging.DEBUG): # Reverted level to DEBUG
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content == "<html>Retry Success</html>"
    assert mock_get.call_count == 2
    assert f"Wayback Machine request failed with status 429. Decorator will handle retry." in caplog.text
    assert f"Successfully fetched content for: {original_url}" in caplog.text # Check success log
    fail_response.close.assert_called_once()
    success_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_retry_fails(mock_get, mock_config, caplog):
    """Test fetch_page_content fails after exhausting retries."""
    fail_response = MagicMock(spec=requests.Response)
    fail_response.status_code = 500
    fail_response.url = "http://mocked.url/fail_always_page"
    fail_response.close = MagicMock()
    fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error", response=fail_response)

    # Simulate failures for all attempts (initial + retries)
    max_attempts = mock_config['max_retries'] + 1
    mock_get.side_effect = [fail_response] * max_attempts

    original_url = "http://example.com/fail_always_page.aspx"
    timestamp = "20230101000000"

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content is None
    assert mock_get.call_count == max_attempts
    # Check the final error log from the decorator after retries are exhausted
    assert f"Request failed for {original_url}... after {mock_config['max_retries']} retries. Last exception: 500 Server Error" in caplog.text
    assert fail_response.close.call_count == max_attempts

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_request_exception(mock_get, mock_config, caplog):
    """Test fetch_page_content handles requests.exceptions.RequestException."""
    mock_get.side_effect = requests.exceptions.ConnectionError("DNS lookup failed")

    original_url = "http://nonexistent.domain/page"
    timestamp = "20230101000000"
    max_attempts = mock_config['max_retries'] + 1

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content is None
    assert mock_get.call_count == max_attempts
    # Check the final error log from the decorator after retries are exhausted
    assert f"Request failed for {original_url}... after {mock_config['max_retries']} retries. Last exception: DNS lookup failed" in caplog.text

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_empty_or_non_html(mock_get, mock_config, mock_response, caplog):
    """Test fetch_page_content handles empty or non-HTML successful response."""
    test_cases = [
        "", # Empty string
        "Just some text, no HTML tags",
        '{"json": "data"}',
    ]
    original_url = "http://example.com/non_html"
    timestamp = "20230101000000"

    for text_content in test_cases:
        mock_response.text = text_content
        mock_get.return_value = mock_response
        mock_get.reset_mock()
        mock_response.close.reset_mock()
        caplog.clear()

        with caplog.at_level(logging.WARNING):
            content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

        assert content is None
        assert "Fetched empty or non-HTML content" in caplog.text
        mock_get.assert_called_once()
        mock_response.close.assert_called_once()


@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_decoding_error(mock_get, mock_config, mock_response, caplog):
    """Test fetch_page_content handles errors during text decoding."""
    # Configure the mock response's text property to raise an error
    type(mock_response).text = property(fget=MagicMock(side_effect=UnicodeDecodeError("utf-8", b"\x80abc", 0, 1, "invalid start byte")))
    mock_get.return_value = mock_response

    original_url = "http://example.com/bad_encoding"
    timestamp = "20230101000000"

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content is None
    assert "Error decoding content" in caplog.text
    assert "invalid start byte" in caplog.text
    mock_get.assert_called_once()
    mock_response.close.assert_called_once()

@patch('api_clients.wayback_client.requests.get')
def test_fetch_page_content_unhandled_client_error(mock_get, mock_config, mock_response, caplog):
    """Test fetch_page_content handles unhandled 4xx client errors."""
    mock_response.status_code = 401 # Unauthorized
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Client Error")
    mock_get.return_value = mock_response

    original_url = "http://example.com/unauthorized_page"
    timestamp = "20230101000000"

    with caplog.at_level(logging.ERROR):
        content = wayback_client.fetch_page_content(original_url, timestamp, config=mock_config)

    assert content is None
    assert "Wayback Machine request failed with unhandled client error 401" in caplog.text
    mock_get.assert_called_once() # Should not retry
    mock_response.close.assert_called_once()