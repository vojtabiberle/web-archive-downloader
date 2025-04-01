import pytest
import os
import sys
import json
import logging
from unittest.mock import patch, mock_open, MagicMock
import re # Import re

# Add project root to sys.path to allow importing project modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

import file_handler
import constants

# --- Tests for sanitize_filename ---

@pytest.mark.parametrize("input_name, expected_name", [
    ("Valid Filename", "Valid_Filename"),
    ("File with spaces", "File_with_spaces"),
    ("File/with\\invalid*chars?:<>|\"", "Filewithinvalidchars"),
    ("  Leading and trailing spaces  ", "Leading_and_trailing_spaces"),
    (".Leading and trailing dots.", "Leading_and_trailing_dots"),
    ("", constants.UNTITLED_FILENAME), # Empty input
    ("..", constants.UNTITLED_FILENAME), # Input becomes empty after stripping dots
    ("///", constants.UNTITLED_FILENAME), # Input becomes empty after removing invalid chars
    ("a" * (constants.FILENAME_MAX_LENGTH + 50), "a" * constants.FILENAME_MAX_LENGTH), # Too long
    ("Valid_Name-123.txt", "Valid_Name-123.txt"), # With extension and hyphen
    ("你好世界", "你好世界"), # Unicode characters (should be preserved)
])
def test_sanitize_filename(input_name, expected_name):
    """Tests the sanitize_filename function with various inputs."""
    assert file_handler.sanitize_filename(input_name) == expected_name


# --- Tests for Checkpointing ---

@patch('os.path.exists', return_value=False)
@patch('logging.info') # Check that info isn't called inappropriately
def test_load_checkpoint_file_not_exist(mock_log_info, mock_exists):
    """Tests loading checkpoint when the file doesn't exist."""
    checkpoint_file = "non_existent_checkpoint.json"
    processed_urls = file_handler.load_checkpoint(checkpoint_file)
    assert processed_urls == set()
    mock_exists.assert_called_once_with(checkpoint_file)
    # No specific log message expected here by default, maybe info if implemented

@patch('os.path.exists', return_value=True)
@patch('builtins.open', new_callable=mock_open, read_data='["http://example.com/page1", "http://example.com/page2"]')
@patch('logging.info')
def test_load_checkpoint_valid_file(mock_log_info, mock_file_open, mock_exists):
    """Tests loading a valid checkpoint file."""
    checkpoint_file = "valid_checkpoint.json"
    expected_urls = {"http://example.com/page1", "http://example.com/page2"}
    processed_urls = file_handler.load_checkpoint(checkpoint_file)
    assert processed_urls == expected_urls
    mock_exists.assert_called_once_with(checkpoint_file)
    mock_file_open.assert_called_once_with(checkpoint_file, 'r', encoding='utf-8')
    mock_log_info.assert_called_once_with(f"Loaded {len(expected_urls)} processed URLs from checkpoint file: {checkpoint_file}")

@patch('os.path.exists', return_value=True)
@patch('builtins.open', new_callable=mock_open, read_data='') # Empty file
@patch('logging.warning')
def test_load_checkpoint_empty_file(mock_log_warning, mock_file_open, mock_exists):
    """Tests loading an empty checkpoint file (causes JSONDecodeError)."""
    checkpoint_file = "empty_checkpoint.json"
    processed_urls = file_handler.load_checkpoint(checkpoint_file)
    assert processed_urls == set()
    mock_exists.assert_called_once_with(checkpoint_file)
    mock_file_open.assert_called_once_with(checkpoint_file, 'r', encoding='utf-8')
    mock_log_warning.assert_called_once_with(f"Could not decode JSON from checkpoint file {checkpoint_file}. Starting fresh.")

@patch('os.path.exists', return_value=True)
@patch('builtins.open', new_callable=mock_open, read_data='{"key": "not a list"}') # Invalid format
@patch('logging.warning')
def test_load_checkpoint_invalid_format(mock_log_warning, mock_file_open, mock_exists):
    """Tests loading a checkpoint file with valid JSON but not a list."""
    checkpoint_file = "invalid_format_checkpoint.json"
    processed_urls = file_handler.load_checkpoint(checkpoint_file)
    assert processed_urls == set()
    mock_exists.assert_called_once_with(checkpoint_file)
    mock_file_open.assert_called_once_with(checkpoint_file, 'r', encoding='utf-8')
    mock_log_warning.assert_called_once_with(f"Checkpoint file {checkpoint_file} does not contain a valid list. Starting fresh.")


@patch('builtins.open', new_callable=mock_open)
@patch('logging.error')
def test_save_checkpoint_new(mock_log_error, mock_file_open):
    """Tests saving a checkpoint for the first time."""
    checkpoint_file = "new_checkpoint.json"
    processed_urls = set()
    new_url = "http://example.com/new_page"

    file_handler.save_checkpoint(new_url, processed_urls, checkpoint_file)

    assert new_url in processed_urls # Check the set is updated in memory
    mock_file_open.assert_called_once_with(checkpoint_file, 'w', encoding='utf-8')
    handle = mock_file_open()
    # Check that json.dump was called with the correct data (a list containing the new URL)
    # json.dump writes multiple times, we check the final content structure
    written_content = "".join(call[0][0] for call in handle.write.call_args_list)
    assert json.loads(written_content) == [new_url]
    mock_log_error.assert_not_called()


@patch('builtins.open', new_callable=mock_open)
@patch('logging.error')
def test_save_checkpoint_append(mock_log_error, mock_file_open):
    """Tests adding a URL to an existing checkpoint set."""
    checkpoint_file = "append_checkpoint.json"
    processed_urls = {"http://example.com/existing_page"}
    new_url = "http://example.com/another_page"
    expected_saved_list = ["http://example.com/existing_page", "http://example.com/another_page"]

    file_handler.save_checkpoint(new_url, processed_urls, checkpoint_file)

    assert new_url in processed_urls
    assert "http://example.com/existing_page" in processed_urls
    mock_file_open.assert_called_once_with(checkpoint_file, 'w', encoding='utf-8')
    handle = mock_file_open()
    written_content = "".join(call[0][0] for call in handle.write.call_args_list)
    # Order doesn't matter in the set, but json.dump(list(set)) might have arbitrary order
    # So, we load the written JSON and compare sets
    assert set(json.loads(written_content)) == set(expected_saved_list)
    mock_log_error.assert_not_called()


@patch('builtins.open', new_callable=mock_open)
@patch('logging.error')
def test_save_checkpoint_error(mock_log_error, mock_file_open):
    """Tests error handling during checkpoint save."""
    checkpoint_file = "error_checkpoint.json"
    processed_urls = {"http://example.com/page"}
    new_url = "http://example.com/another"
    mock_file_open.side_effect = OSError("Disk full") # Simulate write error

    file_handler.save_checkpoint(new_url, processed_urls, checkpoint_file)

    mock_file_open.assert_called_once_with(checkpoint_file, 'w', encoding='utf-8')
    mock_log_error.assert_called_once_with(f"Error saving checkpoint file {checkpoint_file}: Disk full")


# --- Tests for _ensure_page_directory ---

@patch('os.makedirs')
@patch('logging.error')
def test_ensure_page_directory_root(mock_log_error, mock_makedirs, tmp_path):
    """Tests creating directory for a root URL."""
    output_dir = str(tmp_path / "output")
    url = "http://example.com/"
    expected_path = output_dir # Root URL should just ensure the base output dir exists

    result_path = file_handler._ensure_page_directory(url, output_dir)

    assert result_path == expected_path
    # Check that makedirs was called for the base output directory
    mock_makedirs.assert_any_call(output_dir, exist_ok=True)
    # It might be called multiple times depending on implementation details,
    # ensure it was called at least for the final expected path.
    assert any(call == ((expected_path,), {'exist_ok': True}) for call in mock_makedirs.call_args_list)
    mock_log_error.assert_not_called()


@patch('os.makedirs')
@patch('logging.error')
def test_ensure_page_directory_simple_path(mock_log_error, mock_makedirs, tmp_path):
    """Tests creating directory for a simple path."""
    output_dir = str(tmp_path / "output")
    url = "http://example.com/page1"
    # Expect the parent directory path
    expected_path = output_dir # Function returns parent path

    result_path = file_handler._ensure_page_directory(url, output_dir)

    assert result_path == expected_path # Function returns parent path
    mock_makedirs.assert_any_call(output_dir, exist_ok=True)
    # Ensure the parent dir was created
    mock_makedirs.assert_any_call(expected_path, exist_ok=True)
    mock_log_error.assert_not_called()


@patch('os.makedirs')
@patch('logging.error')
def test_ensure_page_directory_nested_path(mock_log_error, mock_makedirs, tmp_path):
    """Tests creating directory for a nested path."""
    output_dir = str(tmp_path / "output")
    url = "http://example.com/dir1/dir2/page"
    path1 = os.path.join(output_dir, "dir1")
    path2 = os.path.join(path1, "dir2")
    # The function should return the parent directory path for a file URL
    expected_path = path2 # Expecting the parent directory

    result_path = file_handler._ensure_page_directory(url, output_dir)

    assert result_path == expected_path # Check it returns the parent directory path
    mock_makedirs.assert_any_call(output_dir, exist_ok=True)
    mock_makedirs.assert_any_call(path1, exist_ok=True)
    # Ensure the parent dir was created by the loop
    mock_makedirs.assert_any_call(expected_path, exist_ok=True)
    mock_log_error.assert_not_called()


@patch('os.makedirs')
@patch('logging.error')
def test_ensure_page_directory_sanitization(mock_log_error, mock_makedirs, tmp_path):
    """Tests creating directory with path components needing sanitization."""
    output_dir = str(tmp_path / "output")
    url = "http://example.com/dir with space/file*name?"
    # sanitize_filename replaces space with _ and removes *?
    sanitized_dir = "dir_with_space"
    # sanitized_file_dir = "filename" # Last part is excluded
    path1 = os.path.join(output_dir, sanitized_dir)
    # Expect the parent directory path
    expected_path = path1 # Function returns parent path

    result_path = file_handler._ensure_page_directory(url, output_dir)

    assert result_path == expected_path # Function returns parent path
    mock_makedirs.assert_any_call(output_dir, exist_ok=True)
    mock_makedirs.assert_any_call(path1, exist_ok=True)
    # Ensure the parent dir was created
    mock_makedirs.assert_any_call(expected_path, exist_ok=True)
    mock_log_error.assert_not_called()


@patch('os.makedirs', side_effect=OSError("Permission denied"))
@patch('logging.error')
def test_ensure_page_directory_os_error(mock_log_error, mock_makedirs, tmp_path):
    """Tests error handling when os.makedirs fails."""
    output_dir = str(tmp_path / "output")
    url = "http://example.com/fail"

    result_path = file_handler._ensure_page_directory(url, output_dir)

    assert result_path is None
    mock_makedirs.assert_any_call(output_dir, exist_ok=True) # First call might succeed
    # Check that error was logged (the exact message might vary slightly)
    assert mock_log_error.call_count > 0
    assert "Error creating directory structure" in mock_log_error.call_args[0][0]


# --- Tests for save_markdown ---

# Helper fixture for common config
@pytest.fixture
def mock_config(tmp_path):
    return {"output_dir": str(tmp_path / "output")}

@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False) # Assume no collision initially
@patch('logging.info')
@patch('logging.warning')
@patch('logging.error')
def test_save_markdown_success(mock_log_error, mock_log_warning, mock_log_info, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests successful saving of a markdown file."""
    title = "Test Page Title"
    markdown_content = "This is the markdown content."
    original_url = "http://example.com/path/to/page"
    timestamp = "20230101120000"
    # _ensure_page_directory returns the parent dir
    page_save_dir = str(tmp_path / "output" / "path" / "to") # Corrected expected parent dir
    mock_ensure_dir.return_value = page_save_dir
    expected_filename = "Test_Page_Title.md"
    # The full path is constructed using the returned parent dir
    expected_full_path = os.path.join(page_save_dir, expected_filename)

    result = file_handler.save_markdown(title, markdown_content, original_url, timestamp, mock_config)

    assert result is True
    mock_ensure_dir.assert_called_once_with(original_url, mock_config['output_dir'])
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
    handle = mock_file_open()
    # Check content structure (basic check)
    written_content = "".join(call[0][0] for call in handle.write.call_args_list)
    assert f"# {title}" in written_content
    assert f"_Source URL: {original_url}_" in written_content
    assert f"_Archived Timestamp: 2023-01-01 12:00:00_" in written_content # Check formatted timestamp
    assert markdown_content in written_content
    mock_log_info.assert_called_once_with(f"Successfully saved: {expected_full_path}")
    mock_log_warning.assert_not_called()
    mock_log_error.assert_not_called()


@patch('file_handler._ensure_page_directory')
@patch('logging.warning')
def test_save_markdown_missing_title(mock_log_warning, mock_ensure_dir, mock_config):
    """Tests skipping save when title is missing."""
    result = file_handler.save_markdown("", "content", "url", "ts", mock_config)
    assert result is False
    mock_ensure_dir.assert_not_called() # Should not proceed to create dir
    mock_log_warning.assert_called_once()
    assert "missing title or content" in mock_log_warning.call_args[0][0]


@patch('file_handler._ensure_page_directory', return_value=None) # Simulate dir creation failure
@patch('logging.warning')
@patch('logging.error') # _ensure_page_directory logs error internally
def test_save_markdown_dir_creation_fails(mock_log_error, mock_log_warning, mock_ensure_dir, mock_config):
    """Tests skipping save when directory creation fails."""
    result = file_handler.save_markdown("title", "content", "url", "ts", mock_config)
    assert result is False
    mock_ensure_dir.assert_called_once()
    mock_log_warning.assert_not_called() # Warning is for missing title/content
    # Error is logged by _ensure_page_directory, not directly by save_markdown in this case


@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists') # Need to control multiple calls
@patch('logging.info')
def test_save_markdown_filename_collision(mock_log_info, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests handling filename collisions."""
    title = "Collision Title"
    original_url = "http://example.com/collision"
    page_save_dir = str(tmp_path / "output" / "collision") # Parent dir
    mock_ensure_dir.return_value = page_save_dir
    base_filename = "Collision_Title"
    path1 = os.path.join(page_save_dir, f"{base_filename}.md")
    path2 = os.path.join(page_save_dir, f"{base_filename}-1.md")
    path3 = os.path.join(page_save_dir, f"{base_filename}-2.md")

    # Simulate first two exist, third one doesn't
    mock_exists.side_effect = lambda p: p in [path1, path2]
    valid_timestamp = "20240101000000" # Use a valid timestamp

    result = file_handler.save_markdown(title, "content", original_url, valid_timestamp, mock_config)

    assert result is True
    assert mock_exists.call_count == 3 # Called for path1, path2, path3
    mock_exists.assert_any_call(path1)
    mock_exists.assert_any_call(path2)
    mock_exists.assert_any_call(path3)
    mock_file_open.assert_called_once_with(path3, 'w', encoding='utf-8') # Saved with -2 suffix
    mock_log_info.assert_called_once_with(f"Successfully saved: {path3}")


@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False)
@patch('logging.error')
def test_save_markdown_write_error(mock_log_error, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests error handling during file writing."""
    title = "Write Error Page"
    original_url = "http://example.com/write_error"
    page_save_dir = str(tmp_path / "output" / "write_error") # Parent dir
    mock_ensure_dir.return_value = page_save_dir
    expected_filename = "Write_Error_Page.md"
    expected_full_path = os.path.join(page_save_dir, expected_filename)

    # Simulate OSError on write
    mock_file_open.side_effect = OSError("Cannot write")

    # Provide valid timestamp to avoid unrelated error
    valid_timestamp = "20240101000000"
    result = file_handler.save_markdown(title, "content", original_url, valid_timestamp, mock_config)

    assert result is False
    mock_ensure_dir.assert_called_once()
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
    mock_log_error.assert_called_once()
    assert f"Error writing file {expected_full_path}" in mock_log_error.call_args[0][0]


@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False)
@patch('logging.info')
def test_save_markdown_root_url(mock_log_info, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests saving markdown for a root URL (should use index filename)."""
    title = "Root Page" # Title is ignored for filename at root
    original_url = "http://example.com/"
    page_save_dir = str(tmp_path / "output") # Root save dir
    mock_ensure_dir.return_value = page_save_dir
    expected_filename = f"{constants.INDEX_FILENAME_BASE}.md" # e.g., index.md
    expected_full_path = os.path.join(page_save_dir, expected_filename)
    valid_timestamp = "20240101000000" # Use a valid timestamp

    result = file_handler.save_markdown(title, "content", original_url, valid_timestamp, mock_config)

    assert result is True
    mock_ensure_dir.assert_called_once_with(original_url, mock_config['output_dir'])
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
    mock_log_info.assert_called_once_with(f"Successfully saved: {expected_full_path}")


# --- Tests for save_html ---

@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False) # Assume no collision initially
@patch('logging.info')
@patch('logging.warning')
@patch('logging.error')
def test_save_html_success(mock_log_error, mock_log_warning, mock_log_info, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests successful saving of an HTML file."""
    title = "Test HTML Page"
    html_content = "<html><body><h1>Test</h1></body></html>"
    original_url = "http://example.com/html/page.html" # Note: .html in URL doesn't affect dir structure
    page_save_dir = str(tmp_path / "output" / "html") # Parent dir
    mock_ensure_dir.return_value = page_save_dir
    expected_filename = "Test_HTML_Page.html" # Filename based on title
    expected_full_path = os.path.join(page_save_dir, expected_filename)

    result = file_handler.save_html(html_content, title, original_url, mock_config)

    assert result is True
    mock_ensure_dir.assert_called_once_with(original_url, mock_config['output_dir'])
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
    handle = mock_file_open()
    handle.write.assert_called_once_with(html_content)
    mock_log_info.assert_called_once_with(f"Successfully saved original HTML: {expected_full_path}")
    mock_log_warning.assert_not_called()
    mock_log_error.assert_not_called()


@patch('file_handler._ensure_page_directory')
@patch('logging.warning')
def test_save_html_missing_content(mock_log_warning, mock_ensure_dir, mock_config):
    """Tests skipping HTML save when content is missing."""
    result = file_handler.save_html("", "title", "url", mock_config)
    assert result is False
    mock_ensure_dir.assert_not_called()
    mock_log_warning.assert_called_once()
    assert "missing title or content" in mock_log_warning.call_args[0][0]


@patch('file_handler._ensure_page_directory', return_value=None) # Simulate dir creation failure
@patch('logging.warning')
@patch('logging.error') # _ensure_page_directory logs error internally
def test_save_html_dir_creation_fails(mock_log_error, mock_log_warning, mock_ensure_dir, mock_config):
    """Tests skipping HTML save when directory creation fails."""
    result = file_handler.save_html("content", "title", "url", mock_config)
    assert result is False
    mock_ensure_dir.assert_called_once()
    mock_log_warning.assert_not_called()


@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists') # Need to control multiple calls
@patch('logging.info')
def test_save_html_filename_collision(mock_log_info, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests handling HTML filename collisions."""
    title = "HTML Collision"
    original_url = "http://example.com/collision.html"
    page_save_dir = str(tmp_path / "output" / "collision") # Parent dir
    mock_ensure_dir.return_value = page_save_dir
    base_filename = "HTML_Collision"
    path1 = os.path.join(page_save_dir, f"{base_filename}.html")
    path2 = os.path.join(page_save_dir, f"{base_filename}-1.html")
    path3 = os.path.join(page_save_dir, f"{base_filename}-2.html")

    mock_exists.side_effect = lambda p: p in [path1, path2]

    result = file_handler.save_html("content", title, original_url, mock_config)

    assert result is True
    assert mock_exists.call_count == 3
    mock_exists.assert_any_call(path1)
    mock_exists.assert_any_call(path2)
    mock_exists.assert_any_call(path3)
    mock_file_open.assert_called_once_with(path3, 'w', encoding='utf-8')
    mock_log_info.assert_called_once_with(f"Successfully saved original HTML: {path3}")


@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False)
@patch('logging.error')
def test_save_html_write_error(mock_log_error, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests error handling during HTML file writing."""
    title = "HTML Write Error"
    original_url = "http://example.com/html_write_error"
    page_save_dir = str(tmp_path / "output" / "html_write_error") # Parent dir
    mock_ensure_dir.return_value = page_save_dir
    expected_filename = "HTML_Write_Error.html"
    expected_full_path = os.path.join(page_save_dir, expected_filename)

    mock_file_open.side_effect = OSError("Disk quota exceeded")

    result = file_handler.save_html("content", title, original_url, mock_config)

    assert result is False
    mock_ensure_dir.assert_called_once()
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
    mock_log_error.assert_called_once()
    assert f"Error writing HTML file {expected_full_path}" in mock_log_error.call_args[0][0]


@patch('file_handler._ensure_page_directory')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False)
@patch('logging.info')
def test_save_html_root_url(mock_log_info, mock_exists, mock_file_open, mock_ensure_dir, mock_config, tmp_path):
    """Tests saving HTML for a root URL (should use index filename)."""
    title = "HTML Root Page" # Title ignored for filename
    original_url = "http://example.com/"
    page_save_dir = str(tmp_path / "output")
    mock_ensure_dir.return_value = page_save_dir
    expected_filename = f"{constants.INDEX_FILENAME_BASE}.html" # e.g., index.html
    expected_full_path = os.path.join(page_save_dir, expected_filename)

    result = file_handler.save_html("content", title, original_url, mock_config)

    assert result is True
    mock_ensure_dir.assert_called_once_with(original_url, mock_config['output_dir'])
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'w', encoding='utf-8')
    mock_log_info.assert_called_once_with(f"Successfully saved original HTML: {expected_full_path}")


# --- Tests for save_asset ---

@pytest.mark.parametrize("asset_type, expected_subdir", [
    ('js', constants.JS_DIR_NAME),
    ('css', constants.CSS_DIR_NAME),
    ('img', constants.IMG_DIR_NAME),
    ('unknown', constants.UNKNOWN_ASSET_DIR_NAME),
    ('font', constants.UNKNOWN_ASSET_DIR_NAME), # Example of another unknown type
])
@patch('file_handler._ensure_page_directory')
@patch('os.makedirs') # Mock makedirs called within save_asset
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False) # Assume no collision initially
@patch('logging.info')
@patch('logging.warning')
@patch('logging.error')
def test_save_asset_success(mock_log_error, mock_log_warning, mock_log_info, mock_exists, mock_file_open, mock_os_makedirs, mock_ensure_page_dir, asset_type, expected_subdir, mock_config, tmp_path):
    """Tests successful saving of different asset types."""
    asset_content = b"binary asset content"
    asset_url = f"http://example.com/assets/style.{asset_type if asset_type in ['js', 'css', 'img'] else 'bin'}" # Give a plausible extension
    original_page_url = "http://example.com/page"
    page_save_dir = str(tmp_path / "output" / "page") # Parent dir
    mock_ensure_page_dir.return_value = page_save_dir

    expected_asset_dir = os.path.join(page_save_dir, constants.ASSETS_DIR_NAME, expected_subdir)
    expected_filename = f"style.{asset_type if asset_type in ['js', 'css', 'img'] else 'bin'}"
    expected_full_path = os.path.join(expected_asset_dir, expected_filename)

    result_path = file_handler.save_asset(asset_content, asset_url, original_page_url, mock_config, asset_type)

    assert result_path == expected_full_path
    mock_ensure_page_dir.assert_called_once_with(original_page_url, mock_config['output_dir'])
    # Check that makedirs was called for the specific asset subdirectory
    mock_os_makedirs.assert_called_with(expected_asset_dir, exist_ok=True)
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'wb') # Binary mode
    handle = mock_file_open()
    handle.write.assert_called_once_with(asset_content)
    mock_log_info.assert_called_once_with(f"Successfully saved asset: {expected_full_path}")
    if asset_type not in ['js', 'css', 'img']:
         mock_log_warning.assert_called_once_with(f"Unknown asset type '{asset_type}' for {asset_url}. Saving in '{constants.UNKNOWN_ASSET_DIR_NAME}'.")
    else:
        mock_log_warning.assert_not_called()
    mock_log_error.assert_not_called()


@patch('logging.warning')
def test_save_asset_empty_content(mock_log_warning, mock_config):
    """Tests skipping save when asset content is empty."""
    result = file_handler.save_asset(b"", "http://example.com/asset.js", "page_url", mock_config, "js")
    assert result is None
    mock_log_warning.assert_called_once()
    assert "Skipping save for asset" in mock_log_warning.call_args[0][0]


@patch('file_handler._ensure_page_directory', return_value=None)
@patch('logging.warning')
@patch('logging.error') # _ensure_page_directory logs error
def test_save_asset_page_dir_fails(mock_log_error, mock_log_warning, mock_ensure_page_dir, mock_config):
    """Tests failure when the page directory cannot be ensured."""
    result = file_handler.save_asset(b"content", "asset_url", "page_url", mock_config, "css")
    assert result is None
    mock_ensure_page_dir.assert_called_once()
    mock_log_warning.assert_not_called() # Warning is for empty content


@patch('file_handler._ensure_page_directory')
@patch('os.makedirs', side_effect=OSError("Cannot create asset dir"))
@patch('logging.error')
def test_save_asset_asset_dir_fails(mock_log_error, mock_os_makedirs, mock_ensure_page_dir, mock_config, tmp_path):
    """Tests failure when the asset type subdirectory cannot be created."""
    asset_url = "http://example.com/assets/image.png"
    original_page_url = "http://example.com/gallery"
    page_save_dir = str(tmp_path / "output" / "gallery")
    mock_ensure_page_dir.return_value = page_save_dir
    expected_asset_dir = os.path.join(page_save_dir, constants.ASSETS_DIR_NAME, constants.IMG_DIR_NAME)

    result = file_handler.save_asset(b"content", asset_url, original_page_url, mock_config, "img")

    assert result is None
    mock_ensure_page_dir.assert_called_once()
    mock_os_makedirs.assert_called_once_with(expected_asset_dir, exist_ok=True)
    mock_log_error.assert_called_once()
    assert "Error creating asset directory structure" in mock_log_error.call_args[0][0]


@patch('file_handler._ensure_page_directory')
@patch('os.makedirs')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists')
@patch('logging.info')
def test_save_asset_collision(mock_log_info, mock_exists, mock_file_open, mock_os_makedirs, mock_ensure_page_dir, mock_config, tmp_path):
    """Tests asset filename collision handling."""
    asset_content = b"collision content"
    asset_url = "http://example.com/assets/script.js"
    original_page_url = "http://example.com/page"
    page_save_dir = str(tmp_path / "output" / "page")
    mock_ensure_page_dir.return_value = page_save_dir
    asset_save_dir = os.path.join(page_save_dir, constants.ASSETS_DIR_NAME, constants.JS_DIR_NAME)
    mock_os_makedirs.return_value = None # Simulate successful creation

    base_filename = "script"
    ext = ".js"
    path1 = os.path.join(asset_save_dir, f"{base_filename}{ext}")
    path2 = os.path.join(asset_save_dir, f"{base_filename}-1{ext}")
    path3 = os.path.join(asset_save_dir, f"{base_filename}-2{ext}")

    mock_exists.side_effect = lambda p: p in [path1, path2]

    result_path = file_handler.save_asset(asset_content, asset_url, original_page_url, mock_config, "js")

    assert result_path == path3
    assert mock_exists.call_count == 3
    mock_exists.assert_any_call(path1)
    mock_exists.assert_any_call(path2)
    mock_exists.assert_any_call(path3)
    mock_file_open.assert_called_once_with(path3, 'wb')
    mock_log_info.assert_called_once_with(f"Successfully saved asset: {path3}")


@patch('file_handler._ensure_page_directory')
@patch('os.makedirs')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False)
@patch('logging.error')
def test_save_asset_write_error(mock_log_error, mock_exists, mock_file_open, mock_os_makedirs, mock_ensure_page_dir, mock_config, tmp_path):
    """Tests error handling during asset file writing."""
    asset_url = "http://example.com/assets/data.bin"
    original_page_url = "http://example.com/data_page"
    page_save_dir = str(tmp_path / "output" / "data_page")
    mock_ensure_page_dir.return_value = page_save_dir
    asset_save_dir = os.path.join(page_save_dir, constants.ASSETS_DIR_NAME, constants.UNKNOWN_ASSET_DIR_NAME)
    mock_os_makedirs.return_value = None
    expected_filename = "data.bin"
    expected_full_path = os.path.join(asset_save_dir, expected_filename)

    mock_file_open.side_effect = OSError("Permission denied")

    result = file_handler.save_asset(b"content", asset_url, original_page_url, mock_config, "bin")

    assert result is None
    mock_ensure_page_dir.assert_called_once()
    mock_os_makedirs.assert_called_once_with(asset_save_dir, exist_ok=True)
    mock_exists.assert_called_once_with(expected_full_path)
    mock_file_open.assert_called_once_with(expected_full_path, 'wb')
    mock_log_error.assert_called_once()
    assert f"Error writing asset file {expected_full_path}" in mock_log_error.call_args[0][0]


@patch('file_handler._ensure_page_directory')
@patch('os.makedirs')
@patch('builtins.open', new_callable=mock_open)
@patch('os.path.exists', return_value=False)
@patch('logging.info')
@patch('logging.warning')
def test_save_asset_no_filename_in_url(mock_log_warning, mock_log_info, mock_exists, mock_file_open, mock_os_makedirs, mock_ensure_page_dir, mock_config, tmp_path):
    """Tests asset saving when the URL path doesn't provide a filename."""
    asset_content = b"content"
    asset_url = "http://example.com/assets/generated/" # No filename part
    original_page_url = "http://example.com/page"
    page_save_dir = str(tmp_path / "output" / "page")
    mock_ensure_page_dir.return_value = page_save_dir
    asset_save_dir = os.path.join(page_save_dir, constants.ASSETS_DIR_NAME, constants.CSS_DIR_NAME)
    mock_os_makedirs.return_value = None

    # Expecting fallback filename structure
    expected_fallback_base = constants.ASSET_FALLBACK_FILENAME_BASE
    # The exact hash is hard to predict, so we check the structure
    # Allow digits, hyphen (for negative hash), and potentially other word chars
    expected_filename_pattern = rf"{expected_fallback_base}_-?\d+\.bin"

    result_path = file_handler.save_asset(asset_content, asset_url, original_page_url, mock_config, "css")

    assert result_path is not None
    saved_filename = os.path.basename(result_path)
    assert re.match(expected_filename_pattern, saved_filename), f"Filename '{saved_filename}' did not match pattern '{expected_filename_pattern}'"
    assert result_path.startswith(asset_save_dir)

    mock_ensure_page_dir.assert_called_once()
    mock_os_makedirs.assert_called_once_with(asset_save_dir, exist_ok=True)
    mock_exists.assert_called_once_with(result_path) # Check existence of the generated path
    mock_file_open.assert_called_once_with(result_path, 'wb')
    mock_log_warning.assert_called_once() # Warning about fallback filename
    assert f"Could not derive filename from asset URL path: {asset_url}" in mock_log_warning.call_args[0][0]
    mock_log_info.assert_called_once_with(f"Successfully saved asset: {result_path}")

# Need to import re for the last test
# import re # Already imported at top