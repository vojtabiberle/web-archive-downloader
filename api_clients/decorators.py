# Decorators for API client functions
import time
import logging;
import requests
import functools

DEFAULT_TIMEOUT = 60 # Default timeout for requests within the decorator

def retry_request(max_retries_key="max_retries", delay_key="request_delay_seconds", non_retryable_status=[404], return_on_failure=None):
    """
    Decorator to add retry logic with exponential backoff to functions making HTTP requests.
    Assumes the wrapped function:
    - Makes a single primary `requests` call (e.g., requests.get).
    - Accepts a 'config' dictionary keyword argument (`config=...`) containing keys
      specified by `max_retries_key` and `delay_key`.
    - Returns the successful result (e.g., response object, processed data) or raises
      an appropriate `requests.exceptions.RequestException` on failure.
    - Handles non-retryable conditions (like 404 returning None) internally if needed.

    Args:
        max_retries_key (str): Key in the config dict for max retries.
        delay_key (str): Key in the config dict for base delay in seconds.
        non_retryable_status (list): List of HTTP status codes that should NOT trigger a retry.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # --- Config Finding ---
            config = kwargs.get('config')
            if not config or not isinstance(config, dict):
                logging.error(
                    f"Decorator @retry_request requires 'config' dictionary as a keyword argument "
                    f"for function {func.__name__}. Retries disabled."
                )
                # Call the function once without retry logic
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.RequestException as e:
                    log_url_snippet = f"in {func.__name__}"
                    url_to_log = kwargs.get('url') # Prioritize 'url' kwarg
                    if not url_to_log:
                        for arg in args:
                            if isinstance(arg, str) and arg.startswith('http'):
                                url_to_log = arg
                                break
                    if url_to_log:
                        log_url_snippet = f"for {url_to_log[:80]}..."
                    logging.error(f"Request failed {log_url_snippet} (no retries applied): {e}")
                    if hasattr(e, 'response') and e.response:
                        try:
                            e.response.close()
                        except Exception:
                            pass # Ignore errors during close
                    return return_on_failure
                except Exception as e:
                    logging.error(f"Unexpected error during {func.__name__} execution (no retries applied): {e}", exc_info=True)
                    return return_on_failure

            max_retries = config.get(max_retries_key, 3)
            delay = config.get(delay_key, 1)

            # --- URL Snippet Finding (Improved) ---
            log_url_snippet = f"for function {func.__name__}"
            url_to_log = kwargs.get('url') # Prioritize 'url' kwarg
            if not url_to_log:
                # Find first string arg starting with http
                for arg in args:
                    if isinstance(arg, str) and arg.startswith('http'):
                        url_to_log = arg
                        break
            # If still not found, check other kwargs (less likely)
            if not url_to_log:
                 for key, value in kwargs.items():
                     if key != 'config' and isinstance(value, str) and value.startswith('http'):
                         url_to_log = value
                         break
            if url_to_log:
                log_url_snippet = f"for {url_to_log[:80]}..." # Log truncated URL

            # --- Retry Loop ---
            retries = 0
            logging.debug(f"DEBUG: Decorator: Starting retry loop for {func.__name__} {log_url_snippet}, max_retries={max_retries}")
            last_exception = None

            while True: # Loop until success, non-retryable error, or max retries exceeded
                try:
                    logging.debug(f"DEBUG: Decorator: Loop iteration start, retries={retries}")
                    # --- Delay ---
                    if retries > 0:
                        wait_time = (2 ** (retries - 1)) * delay
                        logging.warning(f"Retrying request {log_url_snippet} ({retries}/{max_retries}) after delay of {wait_time:.2f} seconds...")
                        time.sleep(wait_time)

                    # --- Call Original Function ---
                    logging.debug(f"DEBUG: Decorator: Calling wrapped function {func.__name__}")
                    result = func(*args, **kwargs)
                    # --- Return Immediately on Success (Any result, including None) ---
                    logging.debug(f"DEBUG: Decorator: Wrapped function returned: {type(result)} {str(result)[:100]}") # Log type and snippet
                    logging.debug(f"DEBUG: Decorator: Returning result immediately.")
                    return result

                # --- Exception Handling ---
                except requests.exceptions.HTTPError as e:
                    last_exception = e
                    status_code = None
                    response_obj = None
                    logging.debug(f"DEBUG: Decorator: Entering HTTPError block, exception={e}")
                    should_close_response = False

                    if hasattr(e, 'response') and e.response is not None:
                        response_obj = e.response
                        status_code = response_obj.status_code
                        should_close_response = True # Mark for closing later

                    # Check for non-retryable status codes FIRST
                    if status_code in non_retryable_status:
                        logging.warning(f"HTTP error {status_code} {log_url_snippet} is non-retryable. Failing.")
                        logging.debug(f"DEBUG: Decorator: Non-retryable status {status_code}, returning None.")
                        # Removed explicit close call; wrapped function's finally should handle it.
                        return return_on_failure # Non-retryable failure


                    # Check for retryable status codes NEXT (429 or 5xx)
                    elif status_code and (status_code == 429 or status_code >= 500):
                        if retries < max_retries:
                            logging.warning(f"Retryable HTTP error {status_code} {log_url_snippet}. Retrying ({retries+1}/{max_retries})...")
                            retries += 1
                            # Removed response_obj.close() here to avoid double closing before retry
                            logging.debug(f"DEBUG: Decorator: Continuing loop for retryable HTTPError {status_code}, retries={retries}")
                            continue # Go to next iteration for retry
                        else:
                            logging.warning(f"Retryable HTTP error {status_code} {log_url_snippet}. Max retries ({max_retries}) reached.")
                            logging.debug(f"DEBUG: Decorator: Breaking loop after max retries for HTTPError {status_code}")
                            # Removed explicit close call; wrapped function's finally should handle it.
                            break # Exit loop to log final error


                    # Handle other HTTP errors (e.g., other 4xx or if status_code is None)
                    else:
                        err_msg = f"Unhandled HTTP error ({status_code or 'no status code'}) encountered {log_url_snippet}: {e}"
                        logging.error(err_msg)
                        # Removed explicit close call; wrapped function's finally should handle it.
                        logging.debug(f"DEBUG: Decorator: Returning None for unhandled HTTPError ({status_code or 'no status code'}).")
                        return return_on_failure # Indicate failure for unhandled HTTP errors

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    last_exception = e
                    exc_type = type(e).__name__
                    logging.debug(f"DEBUG: Decorator: Entering {exc_type} block, exception={e}")
                    if retries < max_retries:
                        logging.warning(f"{exc_type} occurred {log_url_snippet}. Retrying ({retries+1}/{max_retries})...")
                        retries += 1
                        logging.debug(f"DEBUG: Decorator: Continuing loop for {exc_type}, retries={retries}")
                        continue # Go to next iteration for retry
                    else:
                        logging.warning(f"{exc_type} occurred {log_url_snippet}. Max retries ({max_retries}) reached.")
                        logging.debug(f"DEBUG: Decorator: Breaking loop after max retries for {exc_type}")
                        break # Exit loop to log final error

                except requests.exceptions.RequestException as e:
                    # Catch other request exceptions AFTER specific ones
                    last_exception = e
                    logging.error(f"Unhandled RequestException {log_url_snippet}: {e}")
                    # Ensure response is closed if it exists on the exception
                    logging.debug(f"DEBUG: Decorator: Entering unhandled RequestException block, exception={e}")
                    if hasattr(e, 'response') and e.response:
                        try:
                            e.response.close()
                        except Exception:
                            pass
                    return return_on_failure # Don't retry unknown RequestExceptions


                except Exception as e:
                     # Catch unexpected errors from func itself
                     last_exception = e
                     logging.debug(f"DEBUG: Decorator: Entering unexpected Exception block, exception={e}")
                     logging.error(f"Unexpected error during {func.__name__} execution {log_url_snippet}: {e}", exc_info=True)
                     logging.debug(f"DEBUG: Decorator: Returning None for unexpected Exception.")
                     return return_on_failure # Indicate failure

            # --- After Loop (Max Retries Reached for a retryable error) ---
            logging.error(f"Request failed {log_url_snippet} after {max_retries} retries. Last exception: {last_exception}")
            logging.debug(f"DEBUG: Decorator: Returning None after loop (max retries reached).")
            return return_on_failure # Indicate final failure after retries

        return wrapper
    return decorator