# Module for HTML parsing, content extraction, and conversion

import logging
import os
import re

# Set up a specific logger for this module
logger = logging.getLogger(__name__) # Corrected: use logging.getLogger
from urllib.parse import urljoin, urlparse, unquote

import html2text
from bs4 import BeautifulSoup
import constants # Import constants

# Import the authoritative version from file_handler
# Also import the directory utility function
from file_handler import sanitize_filename, _ensure_page_directory 


# --- Asset Discovery ---
def find_assets(html_content, original_page_url, config):
    """Finds JS, CSS, and Image assets within HTML content from the target domain."""
    found_assets = {'js': set(), 'css': set(), 'img': set()}
    target_domain = config.get('target_domain', urlparse(original_page_url).netloc) # Get domain from config or URL

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
                # Ensure asset is from the target domain
                if parsed_url.netloc == target_domain:
                    found_assets['js'].add(abs_url)

        # Find CSS files
        for link_tag in soup.find_all('link', rel='stylesheet', href=True):
            href = link_tag['href']
            if href:
                abs_url = urljoin(original_page_url, href)
                parsed_url = urlparse(abs_url)
                # Ensure asset is from the target domain
                if parsed_url.netloc == target_domain:
                    found_assets['css'].add(abs_url)

        # Find Image files
        for img_tag in soup.find_all('img', src=True):
            src = img_tag['src']
            # Basic check to ignore inline data URIs
            if src and not src.startswith('data:'):
                abs_url = urljoin(original_page_url, src)
                parsed_url = urlparse(abs_url)
                # Ensure asset is from the target domain
                if parsed_url.netloc == target_domain:
                    found_assets['img'].add(abs_url)
        
        # TODO: Consider adding srcset handling for images if needed

    except Exception as e:
        logger.error(f"Error parsing HTML to find assets for {original_page_url}: {e}", exc_info=True) # Restore exc_info=True
        # Return whatever was found before the error

    # Convert sets to lists before returning
    return {k: list(v) for k, v in found_assets.items()}


# --- Internal Helper Functions ---
def _extract_title(soup, original_url):
    """Extracts the title from the parsed HTML soup."""
    title_tag = soup.find('title')
    # Check if title_tag and its string content exist before stripping
    title = title_tag.string.strip() if title_tag and title_tag.string else None
    if not title:
        h1_tag = soup.find('h1')
        # Check if h1_tag and its string content exist before stripping
        title = h1_tag.string.strip() if h1_tag and h1_tag.string else None
    if not title:
        # Fallback to generating title from URL path
        parsed_url = urlparse(original_url)
        path_part = parsed_url.path.strip('/')
        if path_part:
            # Take the last part of the path
            title = path_part.split('/')[-1]
            # Basic cleaning: replace hyphens/underscores with spaces
            title = title.replace('-', ' ').replace('_', ' ')
            # Capitalize the first letter, leave others as is (more natural)
            if title:
                title = title[0].upper() + title[1:]
            else: # Handle case where path part becomes empty after cleaning
                title = constants.UNTITLED_FILENAME # Or some other suitable fallback
        else:
            title = constants.HOMEPAGE_TITLE # Use constant for default root title
        logger.warning(f"No <title> or <h1> found for {original_url}, using fallback title: '{title}'")
    return title

def _find_main_content_soup(soup, selectors, original_url):
    """Finds the main content area using selectors and returns its soup object."""
    content_area_soup = None
    for selector in selectors:
        content_area = soup.select_one(selector)
        if content_area:
            # Optional: Remove known unwanted elements within the content area
            # Example: 
            # for unwanted in content_area.select('nav, footer, .ads'):
            #     unwanted.decompose()
            content_area_soup = content_area # Store the soup object
            logger.debug(f"Found content using selector '{selector}' for {original_url}")
            break # Stop after finding the first matching selector
    
    if not content_area_soup:
         logger.warning(f"Could not find main content using selectors {selectors} for {original_url}. Skipping content extraction.")
         
    return content_area_soup

def _rewrite_asset_links(content_soup, original_url, page_save_dir, saved_assets_map):
    """
    Rewrites asset links within a *copy* of the content soup to point to local paths.
    Requires the target page save directory to calculate relative paths.
    """
    # Check if rewriting is enabled and if there are assets/directory info
    if not page_save_dir or not saved_assets_map: 
        return content_soup 

    logger.debug(f"Rewriting asset links for {original_url} relative to {page_save_dir}...")
    # Modify the content_soup directly, no need for copy if caller handles it
    # content_copy_soup = BeautifulSoup(str(content_soup), 'html.parser') # REMOVE THIS

    tags_to_rewrite = content_soup.find_all(['script', 'link', 'img']) # Find tags within the original content soup
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

        if attr and tag.get(attr): # Use .get() for safety
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
                    # Revert to direct assignment
                    tag[attr] = relative_path
                    rewrite_count += 1
                    logger.debug(f"Rewrote {original_asset_src} -> {relative_path}")
                except ValueError as e:
                     logger.warning(f"Could not calculate relative path for {abs_asset_url} from {page_save_dir} to {local_asset_path_abs}: {e}")
            # else: Asset not found in map, leave original link

    # The function now modifies content_soup in place.
    # The return value isn't strictly necessary if modified in place,
    # but returning it is fine too. Let's keep returning it for clarity.
    if rewrite_count > 0:
         logger.info(f"Rewrote {rewrite_count} asset links in content for {original_url}")
    # Always return the (potentially modified) original content_soup
    return content_soup

def _convert_html_to_markdown(html_string):
    """Converts an HTML string to Markdown."""
    if not html_string:
        return None
        
    try:
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0 # Prevent line wrapping
        markdown_content = h.handle(html_string)

        # Basic validation
        if not markdown_content or markdown_content.isspace():
            logger.warning(f"Markdown conversion resulted in empty content. Original HTML length: {len(html_string)}")
            return None
        return markdown_content
    except Exception as e:
        logger.error(f"Error during HTML to Markdown conversion: {e}", exc_info=True)
        return None


# --- Main Content Extraction and Conversion ---
def extract_and_convert_content(html_content, original_url, config, saved_assets_map):
    """
    Extracts title, main content, optionally rewrites asset links, 
    and converts the main content to Markdown.
    
    Returns:
        tuple: (title, markdown_content) or (None, None) on error.
    """
    if not html_content:
        return None, None

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Extract Title
        title = _extract_title(soup, original_url)
        
        # 2. Extract Main Content Soup
        content_area_soup = _find_main_content_soup(soup, config.get('content_selectors', []), original_url)
        
        if not content_area_soup:
            # Title might still be valid even if content isn't found
            return title, None 

        # 3. Optionally Rewrite Links (operates on a copy if changes are made)
        processed_content_soup = content_area_soup # Default to original soup
        if config.get('rewrite_asset_links', True) and saved_assets_map:
             # Determine the target save directory first
             output_dir = config.get('output_dir', constants.DEFAULT_OUTPUT_DIR)
             page_save_dir = _ensure_page_directory(original_url, output_dir)
             if page_save_dir:
                 processed_content_soup = _rewrite_asset_links(content_area_soup, original_url, page_save_dir, saved_assets_map)
             else:
                 logger.error(f"Could not determine page save directory for {original_url}. Skipping link rewriting.")


        # 4. Convert the potentially modified HTML string to Markdown
        html_to_convert = str(processed_content_soup)
        markdown_content = _convert_html_to_markdown(html_to_convert)

        logger.debug(f"Successfully extracted and converted content for {original_url}")
        return title, markdown_content

    except Exception as e:
        logger.error(f"Error processing HTML content for {original_url}: {e}", exc_info=True)
        return None, None # Return None for both on error
