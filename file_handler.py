# Module for file system operations (saving, sanitizing, checkpointing)

import os
import json
import logging
import re
from datetime import datetime
from urllib.parse import urlparse, unquote
import constants # Import constants


# --- Checkpointing ---
def load_checkpoint(checkpoint_file):
    """Loads the set of processed URLs from the checkpoint file."""
    processed_urls = set()
    try:
        if os.path.exists(checkpoint_file):
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    processed_urls = set(data)
                    logging.info(f"Loaded {len(processed_urls)} processed URLs from checkpoint file: {checkpoint_file}")
                else:
                    logging.warning(f"Checkpoint file {checkpoint_file} does not contain a valid list. Starting fresh.")
    except json.JSONDecodeError:
        logging.warning(f"Could not decode JSON from checkpoint file {checkpoint_file}. Starting fresh.")
    except Exception as e:
        logging.error(f"Error loading checkpoint file {checkpoint_file}: {e}. Starting fresh.")
    return processed_urls

def save_checkpoint(original_url, processed_urls_set, checkpoint_file):
    """Adds a URL to the processed set and saves the updated set to the checkpoint file."""
    processed_urls_set.add(original_url)
    try:
        # Write the entire set back on each update.
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(list(processed_urls_set), f, indent=2) # Save as a list
    except Exception as e:
        logging.error(f"Error saving checkpoint file {checkpoint_file}: {e}")


# --- File Saving ---
def sanitize_filename(name):
    """Sanitizes a string to be used as a valid filename."""
    # Remove invalid characters
    name = re.sub(r'[\\/*?:\'"<>|]', '', name) # Keep single quote removal
    # Remove leading/trailing whitespace/periods FIRST
    name = name.strip(' .')
    # Replace remaining spaces with underscores
    name = name.replace(' ', '_')
    # Limit length using constant
    name = name[:constants.FILENAME_MAX_LENGTH]
    # Strip again in case limiting length left trailing dots/spaces (less likely now)
    name = name.strip(' .')
    # Ensure filename is not empty after sanitization
    if not name:
        name = constants.UNTITLED_FILENAME # Use constant
    return name


# --- Internal Utilities ---
def _ensure_page_directory(original_url, output_dir):
    """
    Creates the necessary directory structure based on the original URL's path
    and returns the final directory path where the corresponding file should be saved.
    Handles sanitization of path components.
    Returns the path to the page's parent directory or None on error.
    """
    try:
        parsed_url = urlparse(original_url)
        full_path = unquote(parsed_url.path).strip('/')
        path_segments = full_path.split('/') if full_path else []

        # Determine which parts represent directories to create
        # If the original URL ends with '/' or the path is empty/root, all segments are directories
        # Otherwise, the last segment is assumed to be the page/file name, so we exclude it
        if original_url.endswith('/') or not full_path:
            dir_parts = path_segments
        else:
            dir_parts = path_segments[:-1] # Exclude the last part

        # Sanitize the directory parts
        dir_parts = [sanitize_filename(part) for part in dir_parts if part]
        # Filter out any parts that became empty after sanitization
        dir_parts = [part for part in dir_parts if part]

        current_path = output_dir
        os.makedirs(current_path, exist_ok=True) # Ensure base output dir exists

        # Create directories for the parts determined to be directories
        for safe_part in dir_parts:
            current_path = os.path.join(current_path, safe_part)
            os.makedirs(current_path, exist_ok=True)

        # Return the path to the directory where the page/asset itself would be saved
        return current_path
    except OSError as e:
        logging.error(f"Error creating directory structure for {original_url} in {output_dir}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error ensuring page directory for {original_url}: {e}")
        return None


def save_markdown(title, markdown_content, original_url, timestamp, config):
    """Saves the markdown content to the appropriate file path."""
    if not title or not markdown_content:
        logging.warning(f"Skipping save for {original_url} (timestamp: {timestamp}) due to missing title or content.")
        return False

    output_dir = config.get('output_dir', constants.DEFAULT_OUTPUT_DIR)
    parsed_url = urlparse(original_url)
    path_parts = [part for part in unquote(parsed_url.path).strip('/').split('/') if part]

    page_save_dir = _ensure_page_directory(original_url, output_dir)
    if not page_save_dir:
        return False

    # Handle root path specifically
    if not path_parts:
         base_filename = constants.INDEX_FILENAME_BASE # Use constant
    else:
         base_filename = sanitize_filename(title)

    filename = f"{base_filename}.md"
    full_path = os.path.join(page_save_dir, filename)

    # Handle filename collisions
    counter = 1
    original_full_path = full_path
    while os.path.exists(full_path):
        filename = f"{base_filename}-{counter}.md"
        full_path = os.path.join(page_save_dir, filename)
        counter += 1
        if counter > constants.FILENAME_COLLISION_LIMIT: # Use constant
             logging.error(f"Could not find unique filename for {original_url} after {constants.FILENAME_COLLISION_LIMIT} attempts. Base path: {original_full_path}")
             return False

    # Write the file
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\\n\\n")
            f.write(f"_Source URL: {original_url}_\\n")
            f.write(f"_Archived Timestamp: {datetime.strptime(timestamp, '%Y%m%d%H%M%S').strftime('%Y-%m-%d %H:%M:%S')}_\\n\\n")
            f.write(markdown_content)
        logging.info(f"Successfully saved: {full_path}")
        return True
    except OSError as e:
        logging.error(f"Error writing file {full_path}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error saving file {full_path}: {e}")
        return False


def save_html(html_content, title, original_url, config):
    """Saves the raw original HTML content to an .html file."""
    if not title or not html_content:
        logging.warning(f"Skipping HTML save for {original_url} due to missing title or content.")
        return False

    output_dir = config.get('output_dir', constants.DEFAULT_OUTPUT_DIR)
    parsed_url = urlparse(original_url)
    path_parts = [part for part in unquote(parsed_url.path).strip('/').split('/') if part]

    page_save_dir = _ensure_page_directory(original_url, output_dir)
    if not page_save_dir:
        return False

    # Determine filename
    if not path_parts: # Handle root path
        base_filename = constants.INDEX_FILENAME_BASE # Use constant
    else:
        base_filename = sanitize_filename(title)

    filename = f"{base_filename}.html"
    full_path = os.path.join(page_save_dir, filename)

    # Handle filename collisions
    counter = 1
    original_full_path = full_path
    while os.path.exists(full_path):
        filename = f"{base_filename}-{counter}.html"
        full_path = os.path.join(page_save_dir, filename)
        counter += 1
        if counter > constants.FILENAME_COLLISION_LIMIT: # Use constant
            logging.error(f"Could not find unique HTML filename for {original_url} after {constants.FILENAME_COLLISION_LIMIT} attempts. Base path: {original_full_path}")
            return False

    # Write the HTML file (text mode)
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logging.info(f"Successfully saved original HTML: {full_path}")
        return True
    except OSError as e:
        logging.error(f"Error writing HTML file {full_path}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error saving HTML file {full_path}: {e}")
        return False


# --- Asset Saving ---
def save_asset(asset_content, asset_url, original_page_url, config, asset_type):
    """Saves the downloaded asset content to the appropriate file path."""
    if not asset_content:
        logging.warning(f"Skipping save for asset {asset_url} due to empty content.")
        return None

    output_dir = config.get('output_dir', constants.DEFAULT_OUTPUT_DIR)

    page_save_dir = _ensure_page_directory(original_page_url, output_dir)
    if not page_save_dir:
        return None

    # Determine asset type subdirectory using constants
    asset_type_dir = constants.UNKNOWN_ASSET_DIR_NAME # Default
    if asset_type == 'js':
        asset_type_dir = constants.JS_DIR_NAME
    elif asset_type == 'css':
        asset_type_dir = constants.CSS_DIR_NAME
    elif asset_type == 'img':
        asset_type_dir = constants.IMG_DIR_NAME
    else:
        logging.warning(f"Unknown asset type '{asset_type}' for {asset_url}. Saving in '{constants.UNKNOWN_ASSET_DIR_NAME}'.")

    # Construct the full asset save directory path
    try:
        # _ensure_page_directory already created page_save_dir
        asset_save_dir = os.path.join(page_save_dir, constants.ASSETS_DIR_NAME, asset_type_dir)
        os.makedirs(asset_save_dir, exist_ok=True)
    except OSError as e:
        logging.error(f"Error creating asset directory structure for {asset_url} in {page_save_dir}: {e}")
        return None

    # Derive filename from asset URL
    parsed_asset_url = urlparse(asset_url)
    asset_filename_raw = os.path.basename(unquote(parsed_asset_url.path))
    if not asset_filename_raw:
        asset_filename_raw = f"{constants.ASSET_FALLBACK_FILENAME_BASE}_{hash(asset_url)}.bin" # Use constant
        logging.warning(f"Could not derive filename from asset URL path: {asset_url}. Using fallback: {asset_filename_raw}")

    base_filename, ext = os.path.splitext(asset_filename_raw)
    safe_base_filename = sanitize_filename(base_filename)
    filename = f"{safe_base_filename}{ext}"
    if not filename or filename == ext: # Check if sanitization resulted in empty name (or just extension)
         filename = constants.DEFAULT_ASSET_FILENAME # Use constant

    full_path = os.path.join(asset_save_dir, filename)

    # Handle filename collisions
    counter = 1
    original_full_path = full_path
    while os.path.exists(full_path):
        base, ext = os.path.splitext(filename)
        base = re.sub(r'-\d+$', '', base) # Remove previous counter
        new_filename = f"{base}-{counter}{ext}"
        full_path = os.path.join(asset_save_dir, new_filename)
        counter += 1
        if counter > constants.FILENAME_COLLISION_LIMIT: # Use constant
            logging.error(f"Could not find unique filename for asset {asset_url} after {constants.FILENAME_COLLISION_LIMIT} attempts. Base path: {original_full_path}")
            return None

    # Write the asset file (binary mode)
    try:
        with open(full_path, 'wb') as f:
            f.write(asset_content)
        logging.info(f"Successfully saved asset: {full_path}")
        return full_path # Return the absolute path of the saved file
    except OSError as e:
        logging.error(f"Error writing asset file {full_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error saving asset file {full_path}: {e}")
        return None
