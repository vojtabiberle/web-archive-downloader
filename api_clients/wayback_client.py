# Module for fetching content/assets from Wayback Machine

import requests
import logging
import time
from .decorators import retry_request # Import the decorator

# --- Asset Fetching --- 
@retry_request(non_retryable_status=[404])
def fetch_asset(asset_url, original_page_timestamp, config):
    """
    Fetches the raw content of a specific archived asset snapshot using retry decorator.
    Returns asset content as bytes or None on failure.
    """
    user_agent = config['user_agent']
    request_timeout = config.get('request_timeout_seconds', 60) # Use a configurable timeout
    
    # Construct the Wayback Machine URL for raw asset content (using id_ flag)
    archive_url = f"https://web.archive.org/web/{original_page_timestamp}id_/{asset_url}"
    headers = {'User-Agent': user_agent}

    logging.debug(f"Attempting to fetch asset: {archive_url}")

    # Decorator handles try/except for RequestException/Timeout and retry loop/delay
    # Use stream=True for potentially large assets
    response = requests.get(archive_url, headers=headers, timeout=request_timeout, stream=True) 

    content = None # Initialize content to None
    try:
        if response.status_code == 200:
            # Success - return raw bytes
            try:
                asset_content = response.content # Read raw bytes
                if asset_content:
                    logging.debug(f"Successfully fetched asset: {asset_url} from {archive_url}")
                    content = asset_content
                else:
                    logging.warning(f"Fetched empty asset content from {archive_url}. Skipping.")
                    # content remains None
            except Exception as e:
                logging.error(f"Error reading content bytes from {archive_url}: {e}")
                # content remains None

        # --- Let decorator handle retries/failures for non-200 ---
        elif response.status_code == 404: # Explicitly handle non-retryable status
            logging.warning(f"Asset not found (404) on Wayback Machine: {archive_url}. Skipping.")
            # content remains None
        elif response.status_code == 429 or response.status_code >= 500:
            logging.warning(f"Wayback Machine asset request failed with status {response.status_code}. Decorator will handle retry.")
            response.raise_for_status() # Raise HTTPError to trigger retry in decorator
        else: # Other client errors (4xx not in non_retryable_status list)
            logging.error(f"Wayback Machine asset request failed with unhandled client error {response.status_code}. Skipping. URL: {response.url}")
            # content remains None
    finally:
         # Ensure the response is always closed
         if 'response' in locals() and response:
              response.close()

    return content # Return the processed content or None


# --- Page Fetching --- 
@retry_request(non_retryable_status=[404])
def fetch_page_content(original_url, timestamp, config):
    """
    Fetches the raw HTML content of a specific archived page snapshot using retry decorator.
    Returns HTML content as string or None on failure.
    """
    user_agent = config['user_agent']
    request_timeout = config.get('request_timeout_seconds', 60) # Use a configurable timeout

    archive_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
    headers = {'User-Agent': user_agent}

    logging.debug(f"Attempting to fetch: {archive_url}")
    
    # Decorator handles try/except for RequestException/Timeout and retry loop/delay
    response = requests.get(archive_url, headers=headers, timeout=request_timeout)
    
    content = None # Initialize content to None
    try:
        if response.status_code == 200:
            # Success - attempt to decode content
            try:
                # Try decoding with UTF-8 first, then let requests guess
                response.encoding = 'utf-8' # Assume UTF-8 initially
                content_text = response.text
                # Basic validation: Check if content seems non-empty/valid HTML
                if content_text and "<html" in content_text.lower():
                    logging.debug(f"Successfully fetched content for: {original_url}")
                    content = content_text # Assign to content variable
                else:
                    logging.warning(f"Fetched empty or non-HTML content from {archive_url}. Skipping.")
                    # content remains None
            except Exception as e:
                logging.error(f"Error decoding content from {archive_url}: {e}")
                # content remains None

        # --- Let decorator handle retries/failures for non-200 ---
        elif response.status_code == 404: # Explicitly handle non-retryable status
             logging.warning(f"Page not found (404) on Wayback Machine: {archive_url}. Skipping.")
             # content remains None
        elif response.status_code == 429 or response.status_code >= 500:
            logging.warning(f"Wayback Machine request failed with status {response.status_code}. Decorator will handle retry.")
            response.raise_for_status() # Raise HTTPError to trigger retry in decorator
        else: # Other client errors (4xx not in non_retryable_status list)
            logging.error(f"Wayback Machine request failed with unhandled client error {response.status_code}. Skipping. URL: {response.url}")
            # content remains None
    finally:
         # Ensure the response is always closed
         if 'response' in locals() and response:
              response.close()

    return content # Return the processed content or None
