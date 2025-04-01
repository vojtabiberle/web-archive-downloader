# Module for interacting with the CDX API

import requests
import logging
import time
import json
import constants # Import constants
from .decorators import retry_request # Import the decorator

# --- CDX API Fetching --- 
@retry_request(non_retryable_status=[404]) # Apply decorator, 404 is not retryable here
def fetch_cdx_index(config):
    """
    Fetches the CDX index for the target domain using the retry decorator.
    Returns list of results, empty list, or None on failure.
    """
    cdx_url = config.get('cdx_api_url', constants.CDX_API_URL) # Use constant default
    target_domain = config['target_domain']
    user_agent = config.get('user_agent', constants.DEFAULT_USER_AGENT)
    request_timeout = config.get('request_timeout_api', constants.DEFAULT_TIMEOUT_API) # Use constant default

    params = {
        'url': f'{target_domain}/*',
        'output': 'json',
        'fl': constants.CDX_FIELDS, # Use constant
        'filter': [constants.CDX_FILTER_STATUS, constants.CDX_FILTER_MIMETYPE], # Use constants
    }
    headers = {'User-Agent': user_agent}

    logging.info(f"Querying CDX API ({cdx_url}) for {target_domain}...")
    
    # The decorator handles the try/except for RequestException/Timeout and the retry loop/delay
    response = requests.get(cdx_url, params=params, headers=headers, timeout=request_timeout)

    try:
        if response.status_code == 200:
            try:
                data = response.json()
                if data and isinstance(data, list) and len(data) > 0:
                    # Check if first item looks like header, remove if so
                    if data[0] == constants.CDX_JSON_HEADER_ROW: # Use constant
                        logging.debug("Removing CDX header row.")
                        return data[1:]
                    else:
                        return data # Assume no header row
                else:
                    logging.warning("CDX API returned empty or invalid data.")
                    return [] # Return empty list for no results
            except json.JSONDecodeError:
                logging.error(f"Failed to decode JSON response from CDX API. Response text: {response.text[:500]}...")
                return None # Indicate failure
            except Exception as e:
                 logging.error(f"Unexpected error processing CDX JSON response: {e}")
                 return None

        # --- Let decorator handle retries/failures for non-200 ---
        elif response.status_code == 404: # Explicitly handle non-retryable status
             logging.warning(f"CDX API returned 404 for {target_domain}. No results found?")
             return [] # Return empty list for 404
        elif response.status_code == 429 or response.status_code >= 500:
            logging.warning(f"CDX API request failed with status {response.status_code}. Decorator will handle retry.")
            response.raise_for_status() # Raise HTTPError to trigger retry in decorator
        
        # For other non-200 codes not in non_retryable_status list (e.g., other 4xx)
        else:
            logging.error(f"CDX API request failed with unhandled status code: {response.status_code}. URL: {response.url}")
            return None # Indicate non-retryable failure
            
    finally:
         # Ensure the response is always closed
         if 'response' in locals() and response:
              response.close()
              
    # This part should ideally not be reached if the decorator handles retries correctly
    # and the function returns None or [] or data, or raises an exception.
    # If the decorator returns None after exhausting retries, that None will be returned.
    return None 


# --- CDX Data Processing --- 
def process_cdx_data(cdx_data):
    """
    Processes the raw CDX data to find the latest snapshot for each unique URL.
    
    Args:
        cdx_data (list): A list of lists, where each inner list represents a 
                         snapshot [original_url, timestamp, mimetype].
                         Assumes header row is already removed if present.

    Returns:
        dict: A dictionary where keys are original URLs and values are the 
              latest corresponding timestamps (as strings). Returns None on error.
    """
    if cdx_data is None:
        logging.error("Cannot process CDX data: input is None.")
        return None
    if not isinstance(cdx_data, list):
        logging.error(f"Cannot process CDX data: input is not a list (type: {type(cdx_data)}).")
        return None

    latest_snapshots = {}
    processed_count = 0
    skipped_count = 0

    logging.info(f"Processing {len(cdx_data)} CDX records...")

    for record in cdx_data:
        if not isinstance(record, list) or len(record) < 2:
            logging.warning(f"Skipping invalid CDX record: {record}")
            skipped_count += 1
            continue

        original_url = record[0]
        timestamp_str = record[1]
        # mimetype = record[2] # Mimetype available if needed later

        if not original_url or not timestamp_str:
             logging.warning(f"Skipping CDX record with missing URL or timestamp: {record}")
             skipped_count += 1
             continue

        # Basic validation of timestamp format (YYYYMMDDHHMMSS)
        if not (len(timestamp_str) == 14 and timestamp_str.isdigit()):
            logging.warning(f"Skipping CDX record with invalid timestamp format '{timestamp_str}': {record}")
            skipped_count += 1
            continue
            
        # Check if this URL is already tracked and if the current timestamp is newer
        if original_url not in latest_snapshots or timestamp_str > latest_snapshots[original_url]:
            latest_snapshots[original_url] = timestamp_str
        
        processed_count += 1
        if processed_count % 1000 == 0: # Log progress periodically
             logging.info(f"Processed {processed_count} CDX records...")

    logging.info(f"Finished processing CDX data. Found latest snapshots for {len(latest_snapshots)} unique URLs.")
    if skipped_count > 0:
        logging.warning(f"Skipped {skipped_count} invalid CDX records during processing.")
        
    return latest_snapshots
