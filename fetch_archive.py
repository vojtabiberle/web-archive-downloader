import requests
import json
import os
import time
import logging
from bs4 import BeautifulSoup
import html2text
from urllib.parse import urlparse, urljoin, unquote
import re
from datetime import datetime
import sys
import os.path # Added for relative path calculation

# --- Configuration Loading ---
def load_config(config_path="config.json"):
    """Loads configuration from a JSON file."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        # Basic validation (add more as needed)
        required_keys = ["target_domain", "output_dir", "content_selectors", 
                         "request_delay_seconds", "max_retries", "user_agent", 
                         "checkpoint_file", "log_file", "cdx_api_url"]
        if not all(key in config for key in required_keys):
            raise ValueError("Config file is missing required keys.")

        # Set defaults for optional asset/HTML download keys if they are missing
        config['download_js'] = config.get('download_js', False)
        config['download_css'] = config.get('download_css', False)
        config['download_images'] = config.get('download_images', False)
        config['save_original_html'] = config.get('save_original_html', False)
        config['rewrite_asset_links'] = config.get('rewrite_asset_links', True) # Default True as per plan
        config['asset_save_structure'] = config.get('asset_save_structure', 'per_page')

        # Validate asset_save_structure (optional but good practice)
        if config['asset_save_structure'] not in ['per_page']: # Add 'central' if implemented later
            # Use print here as logging might not be configured yet
            print(f"Warning: Invalid asset_save_structure '{config['asset_save_structure']}' in config. Defaulting to 'per_page'.", file=sys.stderr)
            config['asset_save_structure'] = 'per_page'

        return config
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {config_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {config_path}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid configuration: {e}", file=sys.stderr)
        sys.exit(1)

# --- Logging Setup ---
def setup_logging(log_file):
    """Sets up logging to console and file."""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # File handler
    try:
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # Make failure to open log file fatal
        print(f"Error: Could not set up file logging to {log_file}: {e}", file=sys.stderr)
        sys.exit(1) # Exit if file logging fails

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

# --- Asset Discovery ---
def find_assets(html_content, original_page_url, config):
    """Finds JS, CSS, and Image assets within HTML content from the target domain."""
    found_assets = {'js': set(), 'css': set(), 'img': set()}
    target_domain = config['target_domain']

    if not html_content:
        return {k: list(v) for k, v in found_assets.items()} # Return empty lists

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # Find JS files
        for script_tag in soup.find_all('script', src=True):
            src = script_tag['src']
            if src:
                abs_url = urljoin(original_page_url, src)
                parsed_url = urlparse(abs_url)
                if parsed_url.netloc == target_domain:
                    found_assets['js'].add(abs_url)

        # Find CSS files
        for link_tag in soup.find_all('link', rel='stylesheet', href=True):
            href = link_tag['href']
            if href:
                abs_url = urljoin(original_page_url, href)
                parsed_url = urlparse(abs_url)
                if parsed_url.netloc == target_domain:
                    found_assets['css'].add(abs_url)

        # Find Image files
        for img_tag in soup.find_all('img', src=True):
            src = img_tag['src']
            # Basic check to ignore inline data URIs
            if src and not src.startswith('data:'):
                abs_url = urljoin(original_page_url, src)
                parsed_url = urlparse(abs_url)
                if parsed_url.netloc == target_domain:
                    found_assets['img'].add(abs_url)
        
        # TODO: Consider adding srcset handling for images if needed

    except Exception as e:
        logging.error(f"Error parsing HTML to find assets for {original_page_url}: {e}", exc_info=True)
        # Return whatever was found before the error

    # Convert sets to lists before returning
    return {k: list(v) for k, v in found_assets.items()}

# --- CDX API Fetching ---
def fetch_cdx_index(config):
    """Fetches the CDX index for the target domain."""
    cdx_url = config['cdx_api_url']
    target_domain = config['target_domain']
    user_agent = config['user_agent']
    delay = config['request_delay_seconds']
    max_retries = config['max_retries']
    
    # Parameters for CDX API
    # Note: collapse=urlkey might miss some intermediate versions if needed later.
    # Fetching all text/html initially. Can filter further later.
    params = {
        'url': f'{target_domain}/*',
        'output': 'json',
        'fl': 'original,timestamp,mimetype',
        'filter': ['statuscode:200', 'mimetype:text/html'],
        # 'filter': 'mimetype:text/html', # Re-enable if needed, but JSON output might not respect this well
        # 'collapse': 'urlkey' # Consider implications carefully
    }
    
    headers = {'User-Agent': user_agent}
    retries = 0
    
    logging.info(f"Querying CDX API for {target_domain}...")
    
    while retries <= max_retries:
        try:
            # Apply delay before each request
            time.sleep(delay)
            
            response = requests.get(cdx_url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                try:
                    # The first line might be the header fields, skip it
                    data = response.json()
                    if data and isinstance(data, list) and len(data) > 0:
                         # Check if first item looks like header, remove if so
                        if data[0] == ['original', 'timestamp', 'mimetype']:
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

            elif response.status_code == 429: # Too Many Requests
                logging.warning(f"Rate limit hit (429). Retrying in {2**retries} seconds...")
                time.sleep(2**retries)
                retries += 1
            else:
                logging.error(f"CDX API request failed with status code: {response.status_code}. URL: {response.url}")
                return None # Indicate failure after non-429 error

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error during CDX API request: {e}")
            if retries < max_retries:
                logging.warning(f"Retrying CDX request ({retries+1}/{max_retries})...")
                time.sleep(2**retries) # Exponential backoff for network errors too
                retries += 1
            else:
                logging.error("Max retries reached for CDX request.")
                return None # Indicate failure after max retries

    logging.error("CDX API request failed after multiple retries.")
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
        # For very large sets, appending might be considered, but requires careful handling.
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(list(processed_urls_set), f, indent=2) # Save as a list
    except Exception as e:
        logging.error(f"Error saving checkpoint file {checkpoint_file}: {e}")

# --- Page Fetching ---
def fetch_page_content(original_url, timestamp, config):
    """Fetches the raw HTML content of a specific archived page snapshot."""
    user_agent = config['user_agent']
    delay = config['request_delay_seconds']
    max_retries = config['max_retries']
    
    # Construct the Wayback Machine URL for raw content (using id_ flag)
    archive_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
    headers = {'User-Agent': user_agent}
    retries = 0

    logging.debug(f"Attempting to fetch: {archive_url}")

    while retries <= max_retries:
        try:
            # Apply delay before each request
            time.sleep(delay)
            
            response = requests.get(archive_url, headers=headers, timeout=60) # Longer timeout for content pages

            if response.status_code == 200:
                # Success - attempt to decode content
                try:
                    # Try decoding with UTF-8 first, then let requests guess
                    response.encoding = 'utf-8' # Assume UTF-8 initially
                    content = response.text
                    # Basic validation: Check if content seems non-empty/valid HTML
                    if content and "<html" in content.lower(): 
                        logging.debug(f"Successfully fetched content for: {original_url}")
                        return content
                    else:
                        logging.warning(f"Fetched empty or non-HTML content from {archive_url}. Skipping.")
                        return None # Treat as failure if content looks invalid
                except Exception as e:
                    logging.error(f"Error decoding content from {archive_url}: {e}")
                    return None # Treat decoding error as failure

            elif response.status_code == 429: # Too Many Requests
                wait_time = 2**retries * delay # Exponential backoff based on delay
                logging.warning(f"Rate limit hit (429) fetching {archive_url}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                retries += 1
            elif response.status_code == 404: # Not Found
                logging.warning(f"Page not found (404) on Wayback Machine: {archive_url}. Skipping.")
                return None # Don't retry 404s
            elif response.status_code >= 500: # Server error
                 wait_time = 2**retries * delay
                 logging.warning(f"Server error ({response.status_code}) fetching {archive_url}. Retrying in {wait_time:.2f} seconds ({retries+1}/{max_retries})...")
                 time.sleep(wait_time)
                 retries += 1
            else: # Other client errors (4xx)
                logging.error(f"Client error ({response.status_code}) fetching {archive_url}. Skipping. URL: {response.url}")
                return None # Don't retry other 4xx errors generally

        except requests.exceptions.Timeout:
            logging.warning(f"Timeout occurred fetching {archive_url}. Retrying ({retries+1}/{max_retries})...")
            time.sleep(2**retries * delay)
            retries += 1
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching {archive_url}: {e}")
            if retries < max_retries:
                logging.warning(f"Retrying fetch ({retries+1}/{max_retries})...")
                time.sleep(2**retries * delay)
                retries += 1
            else:
                logging.error(f"Max retries reached fetching {archive_url}.")
                return None # Indicate failure after max retries

    logging.error(f"Failed to fetch {archive_url} after multiple retries.")
    return None

# --- Asset Fetching ---
def fetch_asset(asset_url, original_page_timestamp, config):
    """Fetches the raw content of a specific archived asset snapshot."""
    user_agent = config['user_agent']
    delay = config['request_delay_seconds']
    max_retries = config['max_retries']
    
    # Construct the Wayback Machine URL for raw asset content (using id_ flag)
    # Use the timestamp of the *page* the asset was found on
    archive_url = f"https://web.archive.org/web/{original_page_timestamp}id_/{asset_url}"
    headers = {'User-Agent': user_agent}
    retries = 0

    logging.debug(f"Attempting to fetch asset: {archive_url}")

    while retries <= max_retries:
        try:
            # Apply delay before each request
            time.sleep(delay)
            
            # Use stream=True for potentially large assets, though fetch size is unknown
            response = requests.get(archive_url, headers=headers, timeout=60, stream=True) 

            if response.status_code == 200:
                # Success - return raw bytes
                try:
                    content = response.content # Read raw bytes
                    if content:
                        logging.debug(f"Successfully fetched asset: {asset_url} from {archive_url}")
                        return content
                    else:
                        logging.warning(f"Fetched empty asset content from {archive_url}. Skipping.")
                        return None
                except Exception as e:
                    logging.error(f"Error reading content bytes from {archive_url}: {e}")
                    return None
                finally:
                    response.close() # Ensure connection is closed if stream=True

            elif response.status_code == 429: # Too Many Requests
                response.close()
                wait_time = 2**retries * delay
                logging.warning(f"Rate limit hit (429) fetching asset {archive_url}. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                retries += 1
            elif response.status_code == 404: # Not Found
                response.close()
                logging.warning(f"Asset not found (404) on Wayback Machine: {archive_url}. Skipping.")
                return None # Don't retry 404s
            elif response.status_code >= 500: # Server error
                response.close()
                wait_time = 2**retries * delay
                logging.warning(f"Server error ({response.status_code}) fetching asset {archive_url}. Retrying in {wait_time:.2f} seconds ({retries+1}/{max_retries})...")
                time.sleep(wait_time)
                retries += 1
            else: # Other client errors (4xx)
                response.close()
                logging.error(f"Client error ({response.status_code}) fetching asset {archive_url}. Skipping.")
                return None # Don't retry other 4xx errors generally

        except requests.exceptions.Timeout:
            logging.warning(f"Timeout occurred fetching asset {archive_url}. Retrying ({retries+1}/{max_retries})...")
            time.sleep(2**retries * delay)
            retries += 1
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching asset {archive_url}: {e}")
            if retries < max_retries:
                logging.warning(f"Retrying asset fetch ({retries+1}/{max_retries})...")
                time.sleep(2**retries * delay)
                retries += 1
            else:
                logging.error(f"Max retries reached fetching asset {archive_url}.")
                return None # Indicate failure after max retries

    logging.error(f"Failed to fetch asset {archive_url} after multiple retries.")
    return None


# --- Asset Saving ---
def save_asset(asset_content, asset_url, original_page_url, config, asset_type):
    """Saves the downloaded asset content to the appropriate file path."""
    if not asset_content:
        logging.warning(f"Skipping save for asset {asset_url} due to empty content.")
        return None

    output_dir = config['output_dir']
    parsed_page_url = urlparse(original_page_url)
    page_path_parts = [part for part in unquote(parsed_page_url.path).strip('/').split('/') if part]

    # Determine base directory for the page
    page_save_dir = output_dir
    os.makedirs(page_save_dir, exist_ok=True) # Ensure base output dir exists
    for part in page_path_parts:
        safe_part = sanitize_filename(part)
        if safe_part:
            page_save_dir = os.path.join(page_save_dir, safe_part)
            # Don't create page dir here yet, wait until markdown/html save
            # os.makedirs(page_save_dir, exist_ok=True)

    # Determine asset type subdirectory
    asset_type_dir = ''
    if asset_type == 'js':
        asset_type_dir = 'js'
    elif asset_type == 'css':
        asset_type_dir = 'css'
    elif asset_type == 'img':
        asset_type_dir = 'img'
    else:
        logging.warning(f"Unknown asset type '{asset_type}' for {asset_url}. Saving in '_unknown'.")
        asset_type_dir = '_unknown'

    # Construct the full asset save directory path
    asset_save_dir = os.path.join(page_save_dir, '_assets', asset_type_dir)
    try:
        os.makedirs(asset_save_dir, exist_ok=True)
    except OSError as e:
        logging.error(f"Error creating asset directory {asset_save_dir}: {e}")
        return None

    # Derive filename from asset URL
    parsed_asset_url = urlparse(asset_url)
    asset_filename_raw = os.path.basename(unquote(parsed_asset_url.path))
    if not asset_filename_raw:
        # If path ends in '/', try to generate a name (e.g., from query or hash)
        # For now, use a placeholder or hash
        asset_filename_raw = f"asset_{hash(asset_url)}.bin" # Basic fallback
        logging.warning(f"Could not derive filename from asset URL path: {asset_url}. Using fallback: {asset_filename_raw}")

    base_filename, ext = os.path.splitext(asset_filename_raw)
    safe_base_filename = sanitize_filename(base_filename)
    # Keep original extension if present, otherwise it might be added by sanitize_filename
    filename = f"{safe_base_filename}{ext}"
    if not filename:
         filename = "downloaded_asset" # Final fallback

    full_path = os.path.join(asset_save_dir, filename)

    # Handle filename collisions (simple counter method)
    counter = 1
    original_full_path = full_path
    while os.path.exists(full_path):
        base, ext = os.path.splitext(filename)
        # Remove previous counter if exists (e.g., asset-1.css -> asset-2.css)
        base = re.sub(r'-\d+$', '', base)
        new_filename = f"{base}-{counter}{ext}"
        full_path = os.path.join(asset_save_dir, new_filename)
        counter += 1
        if counter > 100: # Safety break
            logging.error(f"Could not find unique filename for asset {asset_url} after 100 attempts. Base path: {original_full_path}")
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

# --- Content Processing & Link Rewriting ---
def extract_and_convert_content(html_content, original_url, config, saved_assets_map):
    """
    Extracts title, main content, optionally rewrites asset links in the content
    to point to local copies, and converts the (potentially modified) content to Markdown.
    """
    if not html_content:
        return None, None, None # Return title, markdown_content, content_area_soup

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Extract Title
        title_tag = soup.find('title')
        title = title_tag.string.strip() if title_tag else None
        if not title:
            h1_tag = soup.find('h1')
            title = h1_tag.string.strip() if h1_tag else None
        if not title:
            # Fallback to generating title from URL path
            parsed_url = urlparse(original_url)
            path_part = parsed_url.path.strip('/')
            if path_part:
                title = path_part.split('/')[-1].replace('-', ' ').replace('_', ' ').capitalize()
            else:
                title = "Homepage" # Default for root
            logging.warning(f"No <title> or <h1> found for {original_url}, using fallback title: '{title}'")
        
        # 2. Extract Main Content
        main_content_html = None
        for selector in config['content_selectors']:
            content_area = soup.select_one(selector)
            if content_area:
                # Optional: Remove known unwanted elements within the content area (e.g., nav, footers, ads)
                # Example: 
                # for unwanted in content_area.select('nav, footer, .ads'):
                #     unwanted.decompose()
                main_content_html = str(content_area) 
                logging.debug(f"Found content using selector '{selector}' for {original_url}")
                break # Stop after finding the first matching selector
        
        if not main_content_html:
            logging.warning(f"Could not find main content using selectors {config['content_selectors']} for {original_url}. Skipping content extraction.")
            # Decide if you want to save *something* (e.g., full body) or skip
            # For now, we return None for markdown if no selector matches.
            # Return title but None for markdown if no selector matches.
            return title, None, None

        # Keep the BeautifulSoup object for the selected content area
        content_area_soup = content_area

        # 3. Optionally Rewrite Links in a *copy* of the content area
        html_to_convert = main_content_html # Default to original HTML string
        if config.get('rewrite_asset_links', True) and saved_assets_map:
            logging.debug(f"Rewriting asset links for {original_url}...")
            # Work on a copy of the soup object to avoid modifying the original
            content_copy_soup = BeautifulSoup(main_content_html, 'html.parser')
            
            # Calculate the directory where the markdown file will be saved
            # (This duplicates some logic from save_markdown/save_html, consider refactoring later)
            output_dir = config['output_dir']
            parsed_page_url = urlparse(original_url)
            page_path_parts = [part for part in unquote(parsed_page_url.path).strip('/').split('/') if part]
            page_save_dir = output_dir
            for part in page_path_parts:
                safe_part = sanitize_filename(part)
                if safe_part:
                    page_save_dir = os.path.join(page_save_dir, safe_part)
            # The markdown file will be directly in page_save_dir

            tags_to_rewrite = content_copy_soup.find_all(['script', 'link', 'img'])
            rewrite_count = 0
            for tag in tags_to_rewrite:
                attr = None
                if tag.name == 'script' and tag.has_attr('src'):
                    attr = 'src'
                elif tag.name == 'link' and tag.has_attr('href'):
                    attr = 'href'
                elif tag.name == 'img' and tag.has_attr('src'):
                    attr = 'src'
                # TODO: Add img srcset handling if needed

                if attr and tag[attr]:
                    original_asset_src = tag[attr]
                    # Resolve original src/href relative to the page URL to get absolute
                    abs_asset_url = urljoin(original_url, original_asset_src)

                    # Check if this absolute URL was successfully downloaded
                    if abs_asset_url in saved_assets_map:
                        local_asset_path_abs = saved_assets_map[abs_asset_url]
                        try:
                            # Calculate relative path from the MD file's dir to the asset file
                            relative_path = os.path.relpath(local_asset_path_abs, start=page_save_dir)
                            # Ensure POSIX-style separators for web/markdown compatibility
                            relative_path = relative_path.replace(os.sep, '/')
                            tag[attr] = relative_path
                            rewrite_count += 1
                            logging.debug(f"Rewrote {original_asset_src} -> {relative_path}")
                        except ValueError as e:
                             logging.warning(f"Could not calculate relative path for {abs_asset_url} from {page_save_dir} to {local_asset_path_abs}: {e}")
                    # else: Asset not found in map, leave original link

            if rewrite_count > 0:
                 logging.info(f"Rewrote {rewrite_count} asset links in content for {original_url}")
                 html_to_convert = str(content_copy_soup) # Use the modified HTML string

        # 4. Convert HTML (original or modified) to Markdown
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0
        markdown_content = h.handle(html_to_convert)

        # Basic validation
        if not markdown_content or markdown_content.isspace():
            logging.warning(f"Markdown conversion resulted in empty content for {original_url}. Original HTML length: {len(html_to_convert)}")
            return title, None, content_area_soup # Return soup object even if conversion fails

        logging.debug(f"Successfully extracted and converted content for {original_url}")
        # Return the original title, the final markdown, and the original content area soup object
        return title, markdown_content, content_area_soup

    except Exception as e:
        logging.error(f"Error processing HTML content for {original_url}: {e}", exc_info=True)
        return None, None, None # Return None for all on error


# --- File Saving --- 
def sanitize_filename(name):
    """Sanitizes a string to be used as a valid filename."""
    # Remove invalid characters
    name = re.sub(r'[\\/*?:"<>|]', '', name) # Escaped backslash for regex
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Limit length (e.g., 100 chars), keeping extension if any (though we add .md later)
    name = name[:100]
    # Remove leading/trailing whitespace/periods
    name = name.strip(' .')
    # Ensure filename is not empty after sanitization
    if not name:
        name = "untitled"
    return name

def save_markdown(title, markdown_content, original_url, timestamp, config):
    """Saves the markdown content to the appropriate file path."""
    if not title or not markdown_content:
        logging.warning(f"Skipping save for {original_url} (timestamp: {timestamp}) due to missing title or content.")
        return False

    output_dir = config['output_dir']
    parsed_url = urlparse(original_url)
    # Decode path components before splitting and sanitizing
    path_parts = [part for part in unquote(parsed_url.path).strip('/').split('/') if part]

    # Create directory structure
    current_path = output_dir
    os.makedirs(current_path, exist_ok=True) # Ensure base output dir exists
    for part in path_parts:
        # Sanitize directory names as well
        safe_part = sanitize_filename(part)
        if safe_part:
             current_path = os.path.join(current_path, safe_part)
             os.makedirs(current_path, exist_ok=True)

    # Handle root path specifically (saving as index.md)
    if not path_parts:
         base_filename = "index"
    else:
         # Sanitize title for filename
         base_filename = sanitize_filename(title)

    filename = f"{base_filename}.md"
    full_path = os.path.join(current_path, filename)

    # Handle filename collisions
    counter = 1
    original_full_path = full_path # Keep track of the original intended path
    while os.path.exists(full_path):
        # Use the original base filename for collision handling
        filename = f"{base_filename}-{counter}.md"
        full_path = os.path.join(current_path, filename)
        counter += 1
        if counter > 100: # Safety break
             logging.error(f"Could not find unique filename for {original_url} after 100 attempts. Base path: {original_full_path}")
             return False

    # Write the file
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\n") # Add title as H1 header
            f.write(f"_Source URL: {original_url}_\n") # Add source URL
            f.write(f"_Archived Timestamp: {datetime.strptime(timestamp, '%Y%m%d%H%M%S').strftime('%Y-%m-%d %H:%M:%S')}_\n\n") # Add timestamp
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

    output_dir = config['output_dir']
    parsed_url = urlparse(original_url)
    path_parts = [part for part in unquote(parsed_url.path).strip('/').split('/') if part]

    # Determine save directory (same logic as save_markdown)
    current_path = output_dir
    os.makedirs(current_path, exist_ok=True)
    for part in path_parts:
        safe_part = sanitize_filename(part)
        if safe_part:
            current_path = os.path.join(current_path, safe_part)
            os.makedirs(current_path, exist_ok=True) # Ensure page directory exists

    # Determine filename
    if not path_parts: # Handle root path
        base_filename = "index"
    else:
        base_filename = sanitize_filename(title)

    filename = f"{base_filename}.html" # Use .html extension
    full_path = os.path.join(current_path, filename)

    # Handle filename collisions
    counter = 1
    original_full_path = full_path
    while os.path.exists(full_path):
        filename = f"{base_filename}-{counter}.html"
        full_path = os.path.join(current_path, filename)
        counter += 1
        if counter > 100:
            logging.error(f"Could not find unique HTML filename for {original_url} after 100 attempts. Base path: {original_full_path}")
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




# --- Main Execution ---
def main():
    """Main function to orchestrate the scraping process."""
    config = load_config()
    setup_logging(config['log_file'])
    logging.info("--- Starting Archive Fetcher ---")
    logging.info(f"Configuration loaded for domain: {config['target_domain']}")

    # 1. Fetch CDX Index
    cdx_data = fetch_cdx_index(config)
    if cdx_data is None:
        logging.error("Failed to fetch CDX index. Exiting.")
        sys.exit(1)
    if not cdx_data:
        logging.info("CDX index is empty. No pages to process. Exiting.")
        sys.exit(0)

    # 2. Process CDX Data to find latest snapshots
    latest_snapshots = process_cdx_data(cdx_data)
    if latest_snapshots is None:
        logging.error("Failed to process CDX data. Exiting.")
        sys.exit(1)
    if not latest_snapshots:
        logging.info("No valid latest snapshots found after processing CDX data. Exiting.")
        sys.exit(0)
        
    # 3. Load Checkpoint
    processed_urls = load_checkpoint(config['checkpoint_file'])
    
    # 4. Iterate and Process Pages
    total_urls = len(latest_snapshots)
    processed_count = 0
    success_count = 0
    fail_count = 0
    skipped_count = len(processed_urls) # Count previously processed URLs as skipped initially

    logging.info(f"Starting processing for {total_urls} unique URLs. ({skipped_count} already processed).")

    for original_url, timestamp in latest_snapshots.items():
        processed_count += 1
        progress_percent = (processed_count / total_urls) * 100
        
        if original_url in processed_urls:
            logging.debug(f"Skipping already processed URL: {original_url}")
            continue # Already processed

        logging.info(f"Processing URL {processed_count}/{total_urls} ({progress_percent:.1f}%): {original_url} @ {timestamp}")

        # Fetch content
        html_content = fetch_page_content(original_url, timestamp, config)
        if not html_content:
            logging.warning(f"Failed to fetch content for {original_url}. Skipping.")
            fail_count += 1
            continue

        # --- Start Asset/HTML Processing ---

        # 5. Save Original HTML (Optional)
        # Need title first for filename, extract it preliminarily
        prelim_title = None
        try:
            temp_soup = BeautifulSoup(html_content, 'html.parser')
            title_tag = temp_soup.find('title')
            prelim_title = title_tag.string.strip() if title_tag else None
            if not prelim_title:
                 h1_tag = temp_soup.find('h1')
                 prelim_title = h1_tag.string.strip() if h1_tag else None
            # Use fallback title logic if still no title (copied from extract_and_convert)
            if not prelim_title:
                parsed_url = urlparse(original_url)
                path_part = parsed_url.path.strip('/')
                if path_part:
                    prelim_title = path_part.split('/')[-1].replace('-', ' ').replace('_', ' ').capitalize()
                else:
                    prelim_title = "Homepage"
        except Exception as e:
            logging.error(f"Error extracting preliminary title for HTML save {original_url}: {e}")
            prelim_title = "untitled" # Fallback filename title

        if config.get('save_original_html', False):
            # Ensure the page directory exists before saving HTML
            # (Copied logic from save_markdown/save_html - consider refactor)
            output_dir = config['output_dir']
            parsed_page_url = urlparse(original_url)
            page_path_parts = [part for part in unquote(parsed_page_url.path).strip('/').split('/') if part]
            page_save_dir = output_dir
            os.makedirs(page_save_dir, exist_ok=True)
            for part in page_path_parts:
                safe_part = sanitize_filename(part)
                if safe_part:
                    page_save_dir = os.path.join(page_save_dir, safe_part)
                    os.makedirs(page_save_dir, exist_ok=True) # Create page dir now

            save_html(html_content, prelim_title, original_url, config)
            # Continue processing even if HTML save fails

        # 2. Asset Discovery
        assets_to_download = find_assets(html_content, original_url, config)
        saved_assets_map = {} # {original_asset_url: local_absolute_path}

        # 3. & 4. Fetch and Save Assets (Optional)
        asset_types_to_process = []
        if config.get('download_js', False): asset_types_to_process.append('js')
        if config.get('download_css', False): asset_types_to_process.append('css')
        if config.get('download_images', False): asset_types_to_process.append('img')

        if asset_types_to_process:
            logging.info(f"Processing assets ({', '.join(asset_types_to_process)}) for {original_url}...")
            total_assets_found = sum(len(assets_to_download.get(t, [])) for t in asset_types_to_process)
            asset_processed_count = 0
            asset_success_count = 0
            asset_fail_count = 0

            for asset_type in asset_types_to_process:
                urls_to_fetch = assets_to_download.get(asset_type, [])
                if not urls_to_fetch:
                    continue
                
                logging.debug(f"Found {len(urls_to_fetch)} '{asset_type}' assets to potentially download.")
                for asset_url in urls_to_fetch:
                    asset_processed_count += 1
                    logging.debug(f"Processing asset {asset_processed_count}/{total_assets_found}: {asset_url}")
                    
                    # Fetch asset content
                    asset_content = fetch_asset(asset_url, timestamp, config)
                    if asset_content:
                        # Save asset content
                        # Ensure page directory exists before saving asset (needed by save_asset)
                        # (Copied logic - consider refactor)
                        output_dir = config['output_dir']
                        parsed_page_url = urlparse(original_url)
                        page_path_parts = [part for part in unquote(parsed_page_url.path).strip('/').split('/') if part]
                        page_save_dir = output_dir
                        os.makedirs(page_save_dir, exist_ok=True)
                        for part in page_path_parts:
                            safe_part = sanitize_filename(part)
                            if safe_part:
                                page_save_dir = os.path.join(page_save_dir, safe_part)
                                os.makedirs(page_save_dir, exist_ok=True) # Create page dir now

                        local_path = save_asset(asset_content, asset_url, original_url, config, asset_type)
                        if local_path:
                            saved_assets_map[asset_url] = local_path # Store mapping on success
                            asset_success_count += 1
                        else:
                            asset_fail_count += 1
                            logging.error(f"Failed to save asset: {asset_url}")
                    else:
                        asset_fail_count += 1
                        logging.warning(f"Failed to fetch asset: {asset_url}")
            
            logging.info(f"Asset processing summary for {original_url}: Found={total_assets_found}, Attempted={asset_processed_count}, Saved={asset_success_count}, Failed={asset_fail_count}")

        # --- End Asset/HTML Processing ---


        # 6. Extract Content, Optionally Rewrite Links, Convert to Markdown
        # Pass the map of successfully saved assets
        title, markdown_content, _ = extract_and_convert_content(html_content, original_url, config, saved_assets_map)
        # We get the title again here, potentially overriding prelim_title if extraction logic differs slightly
        
        if not title or not markdown_content:
            logging.warning(f"Failed to extract/convert content for {original_url}. Skipping Markdown save.")
            # Still count as failure if content couldn't be processed
            fail_count += 1
            continue

        # Save markdown
        save_success = save_markdown(title, markdown_content, original_url, timestamp, config)
        if save_success:
            success_count += 1
            # Update checkpoint only on successful save
            save_checkpoint(original_url, processed_urls, config['checkpoint_file'])
        else:
            fail_count += 1
            logging.error(f"Failed to save markdown for {original_url}.")
            # Do not update checkpoint if save failed

    logging.info("--- Processing Summary ---")
    logging.info(f"Total unique URLs found: {total_urls}")
    logging.info(f"URLs skipped (already processed): {skipped_count}")
    logging.info(f"URLs processed in this run: {processed_count - skipped_count}")
    logging.info(f"Successfully saved: {success_count}")
    logging.info(f"Failed/Skipped during processing: {fail_count}")
    logging.info("--- Archive Fetcher Finished ---")


if __name__ == "__main__":
    main()