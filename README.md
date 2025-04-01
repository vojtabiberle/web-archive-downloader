# Wayback Machine Content Fetcher

This tool fetches the latest available archived content for a specified domain from the Internet Archive's Wayback Machine using its CDX API. It includes a fallback mechanism using the Memento Time Travel API if direct Wayback Machine snapshots are unavailable or fail. The fetched HTML content is converted to Markdown, and associated assets (CSS, images) are downloaded and saved locally.

## Features

*   **Wayback Machine Integration:** Uses the CDX API to find all archived URLs for a target domain.
*   **Memento Fallback:** If a direct Wayback Machine snapshot fetch fails, it attempts to find a suitable snapshot via the Memento Time Travel API.
*   **HTML to Markdown Conversion:** Extracts the main content from fetched HTML pages (based on configurable CSS selectors) and converts it to Markdown format.
*   **Asset Handling:** Downloads linked CSS and image files (optionally JavaScript).
*   **Link Rewriting:** Rewrites links to downloaded assets within the Markdown files to point to the local copies.
*   **Original HTML Saving:** Option to save the original fetched HTML file alongside the Markdown version.
*   **Checkpointing:** Keeps track of processed URLs in a JSON file (`processed_urls.json` by default) to allow resuming interrupted fetch operations.
*   **Configurable:** Behavior is controlled through a `config.json` file.
*   **Logging:** Logs activity and errors to a file (`scraping.log` by default).

## Installation

1.  **Prerequisites:**
    *   Python 3.8 or higher is recommended.
2.  **Clone the Repository:**
    ```bash
    git clone https://github.com/vojtabiberle/web-archive-downloader
    cd web-archive-downloader
    ```
3.  **Install Dependencies:**
    Create a virtual environment (recommended):
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
    Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```


## Testing

This project uses `pytest` for running unit and integration tests. The necessary testing dependencies are included in `requirements.txt` and should be installed during the setup process described in the Installation section.

To run the tests, navigate to the project's root directory in your terminal (the directory containing `requirements.txt` and `main.py`) and execute the following command:

```bash
pytest
```

This command will automatically discover and run all tests located in the `tests/` directory.

## Configuration

The script's behavior is configured via the `config.json` file in the project root.

```json
{
  "target_domain": "example.org", // The domain to fetch content for.
  "output_dir": "output",             // Directory where fetched content will be saved.
  "content_selectors": [              // List of CSS selectors to find the main content area.
    "#content",                       // The script uses the first selector that matches.
    "main",
    ".main-content",
    ".entry-content",
    "article",
    "body"                            // Fallback to the whole body if others fail.
  ],
  "request_delay_seconds": 1.5,       // Delay (in seconds) between requests to APIs/servers.
  "max_retries": 3,                   // Max number of retries for failed network requests.
  "user_agent": "WebArchiveDownloader/1.0 (+https://github.com/vojtabiberle/web-archive-downloader)", // User-Agent for requests. **Update the URL!**
  "checkpoint_file": "processed_urls.json", // File to store progress for resuming.
  "log_file": "scraping.log",         // File to log script activity.
  "cdx_api_url": "http://web.archive.org/cdx/search/cdx", // Wayback Machine CDX API endpoint.
  "request_timeout_api": 30,          // Timeout (seconds) for API calls (CDX, Memento).
  "request_timeout_content": 60,      // Timeout (seconds) for fetching page content/assets.
  "download_js": false,               // Set to true to download linked JavaScript files.
  "download_css": true,               // Set to true to download linked CSS files.
  "download_images": true,            // Set to true to download linked image files.
  "save_original_html": true,         // Set to true to save the original HTML alongside Markdown.
  "rewrite_asset_links": true,        // Set to true to rewrite asset links in Markdown to local paths.
  "asset_save_structure": "per_page"  // How to organize assets ('per_page' saves assets in an _assets folder next to the page).
}
```

**Important:** Remember to update the `user_agent` string with your actual project repository URL if you make it public.

## Usage

1.  Ensure the `config.json` file is present and configured correctly for your target domain and preferences.
2.  Run the main script from the project's root directory:
    ```bash
    python main.py
    ```
3.  The script will start fetching URLs from the CDX API, process each page, and save the content and assets to the specified `output_dir`.
4.  Progress and any errors will be logged to the console and the file specified by `log_file` (default: `scraping.log`).
5.  If the script is interrupted (e.g., by pressing `Ctrl+C` or due to an error), you can simply run `python main.py` again. It will read the `checkpoint_file` (default: `processed_urls.json`) and skip URLs that have already been successfully processed.

## Output Structure

The fetched content is organized within the `output_dir` (default: `output/`) as follows:

*   A directory structure mirroring the URL paths of the website is created.
*   For each processed page, a Markdown file is created, named using the page's title (e.g., `output/path/to/page/Page_Title.md`). Special characters in titles are sanitized.
*   If `save_original_html` is `true`, the original HTML is saved alongside the Markdown (e.g., `output/path/to/page/Page_Title.html`).
*   If assets are downloaded (`download_css`, `download_images`, `download_js` are `true`) and `asset_save_structure` is `"per_page"`, they are stored in an `_assets` subdirectory within the page's directory (e.g., `output/path/to/page/_assets/style.css`).

Example:
```
output/
└── about/
    ├── _assets/
    │   ├── logo.png
    │   └── main.css
    ├── About_Us.md
    └── About_Us.html  (if save_original_html is true)
└── contact/
    ├── _assets/
    │   └── contact_style.css
    ├── Contact_Information.md
    └── Contact_Information.html (if save_original_html is true)
```

## Limitations

*   **API Dependency:** The tool relies on the availability and performance of the Internet Archive's Wayback Machine (CDX API, snapshots) and the Memento Time Travel API. Rate limits or downtime can affect operation.
*   **Network Issues:** Standard network connectivity problems can interrupt the fetching process. The checkpointing feature helps mitigate data loss from interruptions.
*   **HTML Parsing Variability:** The accuracy of content extraction depends heavily on the consistency of the target website's HTML structure across different archived versions and the effectiveness of the configured `content_selectors`. Websites with highly dynamic structures or significant layout changes over time may yield inconsistent results.
*   **Dynamic Content:** Content loaded via JavaScript after the initial page load might not be captured or processed correctly. Asset fetching might miss dynamically loaded resources.

## License

This project is licensed under the MIT License. See the `LICENSE` file for more details.