# Module for interacting with the Memento Time Travel API

import requests
import logging
import time
import json
from datetime import datetime
from urllib.parse import urlparse
import constants # Import constants
from .decorators import retry_request # Import the decorator

from html_processor import extract_and_convert_content
from file_handler import save_markdown, save_checkpoint


# --- Memento Fallback ---
@retry_request(non_retryable_status=[404])
def fetch_memento_snapshot(original_url, config, wayback_timestamp=None):
    """
    Queries the Memento Time Travel API for a snapshot of the URL using retry decorator.
    Returns the Memento URI string or None on failure or if a loop is detected.
    """
    user_agent = config.get('user_agent', constants.DEFAULT_USER_AGENT)
    request_timeout = config.get('request_timeout_api', constants.DEFAULT_TIMEOUT_API) 

    # Use Wayback timestamp if available, otherwise current time
    if wayback_timestamp and len(wayback_timestamp) == 14 and wayback_timestamp.isdigit():
        memento_dt_str = wayback_timestamp
    else:
        memento_dt_str = datetime.now().strftime('%Y%m%d%H%M%S')

    # Use constant for base URL
    memento_api_url = f"{constants.MEMENTO_API_BASE_URL}{memento_dt_str}/{original_url}"
    headers = {'User-Agent': user_agent}
    
    logging.info(f"Querying Memento API: {memento_api_url}")

    # Decorator handles try/except for RequestException/Timeout and retry loop/delay
    response = requests.get(memento_api_url, headers=headers, timeout=request_timeout)
    
    memento_uri = None # Initialize to None
    try:
        if response.status_code == 200:
            try:
                data = response.json()
                # Check structure carefully before accessing keys
                if (data and isinstance(data, dict) and 
                    'mementos' in data and isinstance(data['mementos'], dict) and
                    'closest' in data['mementos'] and isinstance(data['mementos']['closest'], dict) and
                    'uri' in data['mementos']['closest'] and isinstance(data['mementos']['closest']['uri'], list) and
                    len(data['mementos']['closest']['uri']) > 0):
                    
                    potential_uri = data['mementos']['closest']['uri'][0] # URI is usually in a list
                    
                    # CRITICAL CHECK: Avoid web.archive.org loops
                    if 'web.archive.org' not in urlparse(potential_uri).netloc:
                        logging.info(f"Found potential Memento URI: {potential_uri}")
                        memento_uri = potential_uri
                    else:
                         logging.warning(f"Memento API returned a web.archive.org URI ({potential_uri}). Skipping fallback to avoid loop.")
                         # memento_uri remains None
                else:
                    logging.warning(f"Memento API response for {original_url} did not contain a usable closest memento URI. Response structure invalid or missing keys. Response: {data}")
                    # memento_uri remains None
            except json.JSONDecodeError:
                logging.error(f"Failed to decode JSON response from Memento API. URL: {memento_api_url}, Response text: {response.text[:500]}...")
                # memento_uri remains None
            except Exception as e:
                logging.error(f"Unexpected error processing Memento JSON response for {original_url}: {e}")
                # memento_uri remains None

        # --- Let decorator handle retries/failures for non-200 ---
        elif response.status_code == 404: # Explicitly handle non-retryable status
             logging.warning(f"Memento API returned 404 for {original_url} at timestamp {memento_dt_str}. No snapshot found.")
             # memento_uri remains None
        elif response.status_code == 429 or response.status_code >= 500:
            logging.warning(f"Memento API request failed with status {response.status_code}. Decorator will handle retry.")
            response.raise_for_status() # Raise HTTPError to trigger retry in decorator
        else: # Other client errors (4xx not in non_retryable_status list)
            logging.error(f"Memento API request failed with unhandled client error {response.status_code}. Skipping. URL: {response.url}")
            # memento_uri remains None
            
    finally:
        # Ensure the response is always closed
        if 'response' in locals() and response:
             response.close()

    return memento_uri

@retry_request(non_retryable_status=[404, 403], return_on_failure=False)
def fetch_and_process_memento_content(memento_uri, original_url, config, processed_urls_set):
    """
    Fetches, processes, and saves content from a Memento URI using retry decorator.
    Returns True on success, False on failure.
    """
    # Imports moved to top level

    user_agent = config.get('user_agent', constants.DEFAULT_USER_AGENT)
    request_timeout = config.get('request_timeout_content', constants.DEFAULT_TIMEOUT_CONTENT)
    headers = {'User-Agent': user_agent}

    logging.info(f"Attempting to fetch content from Memento URI: {memento_uri}")

    # Decorator handles try/except for RequestException/Timeout and retry loop/delay
    response = requests.get(memento_uri, headers=headers, timeout=request_timeout)

    success = False # Initialize success flag
    try:
        if response.status_code == 200:
            try:
                response.encoding = 'utf-8' # Assume UTF-8
                memento_html = response.text
                if memento_html and "<html" in memento_html.lower():
                    logging.info(f"Successfully fetched HTML from Memento URI: {memento_uri}")

                    # --- Process Memento HTML --- 
                    title, markdown_content = extract_and_convert_content(memento_html, original_url, config, saved_assets_map={}) # Pass empty map

                    if not title or not markdown_content:
                        logging.warning(f"Failed to extract/convert content from Memento source {memento_uri} for original URL {original_url}. Skipping save.")
                        return False
                        return False
                        # success remains False
                    else:
                        # Save markdown
                        memento_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                        save_success = save_markdown(title, markdown_content, original_url, memento_timestamp, config)
                        
                        if save_success:
                            logging.info(f"Successfully saved content retrieved via Memento ({memento_uri}) for original URL {original_url}")
                            save_checkpoint(original_url, processed_urls_set, config['checkpoint_file'])
                            success = True # Set success flag
                        else:
                            logging.error(f"Failed to save markdown derived from Memento source {memento_uri} for original URL {original_url}.")
                            return False
                            return False
                            # success remains False
                else:
                    logging.warning(f"Fetched empty or non-HTML content from Memento URI {memento_uri}. Skipping.")
                    return False
                    return False
                    # success remains False

            except Exception as e:
                logging.error(f"Error processing content from Memento URI {memento_uri}: {e}", exc_info=True)
                # success remains False

        # --- Let decorator handle retries/failures for non-200 ---
        elif response.status_code in [404, 403]: # Explicitly handle non-retryable status
             logging.warning(f"Memento URI request failed with non-retryable status {response.status_code}: {memento_uri}. Skipping.")
             # success remains False
        elif response.status_code == 429 or response.status_code >= 500:
            logging.warning(f"Memento content request failed with status {response.status_code}. Decorator will handle retry.")
            response.raise_for_status() # Raise HTTPError to trigger retry in decorator
        else: # Other client errors (4xx not in non_retryable_status list)
            logging.error(f"Memento content request failed with unhandled client error {response.status_code}. Skipping. URL: {response.url}")
            # success remains False
            
    finally:
        # Ensure the response is always closed
        if 'response' in locals() and response:
             response.close()

    return success
