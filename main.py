# Main script to orchestrate the archive fetching process
import sys
import logging
# Removed unused: os, unquote, BeautifulSoup, sanitize_filename
from urllib.parse import urlparse # Still needed for prelim title fallback in html_processor

# Import functions from refactored modules
from config_loader import load_config
from logger_setup import setup_logging
from api_clients.cdx_client import fetch_cdx_index, process_cdx_data
from api_clients.wayback_client import fetch_page_content, fetch_asset
from api_clients.memento_client import fetch_memento_snapshot, fetch_and_process_memento_content
from html_processor import find_assets, extract_and_convert_content
from file_handler import (
    load_checkpoint, save_checkpoint, save_html, 
    save_markdown, save_asset 
    # sanitize_filename is used internally by file_handler and html_processor
)

# --- Main Execution ---
def main():
    """Main function to orchestrate the scraping process."""
    config = load_config()
    setup_logging(config['log_file']) 
    logging.info("--- Starting Archive Fetcher ---")
    logging.info(f"Configuration loaded for domain: {config['target_domain']}")

    # 1. Fetch CDX Index
    cdx_data = fetch_cdx_index(config=config)
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
    skipped_count = len(processed_urls) 

    logging.info(f"Starting processing for {total_urls} unique URLs. ({skipped_count} already processed).")

    for original_url, timestamp in latest_snapshots.items():
        processed_count += 1
        progress_percent = (processed_count / total_urls) * 100
        
        if original_url in processed_urls:
            logging.debug(f"Skipping already processed URL: {original_url}")
            continue 

        logging.info(f"Processing URL {processed_count}/{total_urls} ({progress_percent:.1f}%): {original_url} @ {timestamp}")

        # Fetch content from Wayback Machine
        html_content = fetch_page_content(original_url, timestamp, config=config)
        
        memento_success = False 
        if not html_content:
            logging.warning(f"Failed to fetch content for {original_url} from Wayback Machine. Attempting Memento fallback...")
            
            # --- Memento Fallback ---
            memento_uri = fetch_memento_snapshot(original_url, config=config, wayback_timestamp=timestamp)
            if memento_uri:
                # Pass the processed_urls set for checkpointing within the function
                memento_success = fetch_and_process_memento_content(memento_uri, original_url, config=config, processed_urls_set=processed_urls)
                if memento_success:
                    success_count += 1 
                    logging.info(f"Successfully processed {original_url} via Memento fallback.")
                    continue 
                else:
                    logging.warning(f"Memento fallback failed to fetch/process content from {memento_uri} for {original_url}.")
            else:
                logging.warning(f"No suitable Memento snapshot found for {original_url}.")
            # --- End Memento Fallback ---
            
            if not memento_success:
                logging.error(f"Failed to fetch content for {original_url} from both Wayback Machine and Memento.")
                fail_count += 1
                continue

        # --- Start Asset/HTML Processing (Only for Wayback Machine content) ---
        
        # Initialize map for saved assets for this page
        saved_assets_map = {} 

        # 2. Asset Discovery (Run before extraction to know what might be downloadable)
        assets_to_download = find_assets(html_content, original_url, config)

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
                    
                    asset_content = fetch_asset(asset_url, timestamp, config=config)
                    if asset_content:
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

        # --- End Asset Fetch/Save ---

        # 6. Extract Content, Optionally Rewrite Links, Convert to Markdown
        # Pass the populated map of successfully saved assets
        title, markdown_content = extract_and_convert_content(html_content, original_url, config, saved_assets_map)
        
        # 5. Save Original HTML (Optional) - Use title extracted above
        if config.get('save_original_html', False):
            if title: # Only save if we have a title (even a fallback one)
                 save_html(html_content, title, original_url, config)
            else:
                 logging.warning(f"Skipping HTML save for {original_url} due to missing title from extraction.")
                 
        # Check if content extraction/conversion was successful before saving markdown
        if not title or not markdown_content:
            logging.warning(f"Failed to extract/convert content for {original_url}. Skipping Markdown save.")
            fail_count += 1
            continue

        # Save markdown
        save_success = save_markdown(title, markdown_content, original_url, timestamp, config)
        if save_success:
            success_count += 1
            save_checkpoint(original_url, processed_urls, config['checkpoint_file'])
        else:
            fail_count += 1
            logging.error(f"Failed to save markdown for {original_url}.")

    logging.info("--- Processing Summary ---")
    logging.info(f"Total unique URLs found: {total_urls}")
    logging.info(f"URLs skipped (already processed): {skipped_count}")
    logging.info(f"URLs processed in this run: {processed_count - skipped_count}")
    logging.info(f"Successfully saved: {success_count}")
    logging.info(f"Failed/Skipped during processing: {fail_count}")
    logging.info("--- Archive Fetcher Finished ---")


if __name__ == "__main__":
    main()