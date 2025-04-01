# constants.py - Define constants used throughout the application

# --- API Endpoints ---
CDX_API_URL = "http://web.archive.org/cdx/search/cdx"
WAYBACK_BASE_URL = "https://web.archive.org/web/"
MEMENTO_API_BASE_URL = "http://timetravel.mementoweb.org/api/json/"

# --- File/Directory Names ---
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_CHECKPOINT_FILE = "processed_urls.json"
DEFAULT_LOG_FILE = "scraping.log"
INDEX_FILENAME_BASE = "index" # Base name for root path files (.md, .html)
UNTITLED_FILENAME = "untitled" # Fallback for sanitized filenames
ASSET_FALLBACK_FILENAME_BASE = "asset" # Base for assets with unparsable URLs
ASSETS_DIR_NAME = "_assets" # Subdirectory for assets relative to page dir
JS_DIR_NAME = "js"
HOMEPAGE_TITLE = "Homepage" # Default title for root path

CSS_DIR_NAME = "css"
IMG_DIR_NAME = "img"
UNKNOWN_ASSET_DIR_NAME = "_unknown"

# --- Limits ---
FILENAME_MAX_LENGTH = 100 # Max length for sanitized filenames (excluding extension)
DEFAULT_ASSET_FILENAME = "downloaded_asset" # Final fallback if sanitization results in empty name

FILENAME_COLLISION_LIMIT = 100 # Max attempts for finding unique filename with counter

# --- Request Defaults ---
DEFAULT_USER_AGENT = "StromFetcher/1.0 (+https://github.com/your-repo/)" # TODO: Update repo URL
DEFAULT_REQUEST_DELAY = 1.0 # Default seconds between requests
DEFAULT_MAX_RETRIES = 3 # Default max retries for requests
DEFAULT_TIMEOUT_API = 30 # Default timeout for API calls (CDX, Memento lookup)
DEFAULT_TIMEOUT_CONTENT = 60 # Default timeout for content/asset downloads

# --- CDX Parameters ---
CDX_FIELDS = "original,timestamp,mimetype"
CDX_FILTER_STATUS = "statuscode:200"
CDX_FILTER_MIMETYPE = "mimetype:text/html"
CDX_JSON_HEADER_ROW = ['original', 'timestamp', 'mimetype']

# --- Other ---
WAYBACK_RAW_PREFIX = "id_" # Prefix for fetching raw content from Wayback