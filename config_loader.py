# Module for loading and validating configuration
import json
import sys
import os 
import constants # Import constants

def load_config(config_path="config.json"): # Keep default path simple
    """Loads configuration from a JSON file, validates, and sets defaults."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        # --- Validation ---
        # Define required keys (consider adding timeouts as required?)
        # For now, keep timeouts optional via .get() below
        required_keys = [
            "target_domain", "output_dir", "content_selectors", 
            "request_delay_seconds", "max_retries", "user_agent", 
            "checkpoint_file", "log_file", "cdx_api_url"
        ]
        if not all(key in config for key in required_keys):
            # Find missing keys for a better error message
            missing_keys = [key for key in required_keys if key not in config]
            raise ValueError(f"Config file '{config_path}' is missing required keys: {', '.join(missing_keys)}")

        # --- Set Defaults for Optional Keys ---
        # Use constants for default values
        config['request_delay_seconds'] = config.get('request_delay_seconds', constants.DEFAULT_REQUEST_DELAY)
        config['max_retries'] = config.get('max_retries', constants.DEFAULT_MAX_RETRIES)
        config['user_agent'] = config.get('user_agent', constants.DEFAULT_USER_AGENT)
        config['checkpoint_file'] = config.get('checkpoint_file', constants.DEFAULT_CHECKPOINT_FILE)
        config['log_file'] = config.get('log_file', constants.DEFAULT_LOG_FILE)
        config['output_dir'] = config.get('output_dir', constants.DEFAULT_OUTPUT_DIR)
        config['cdx_api_url'] = config.get('cdx_api_url', constants.CDX_API_URL)
        
        config['request_timeout_api'] = config.get('request_timeout_api', constants.DEFAULT_TIMEOUT_API)
        config['request_timeout_content'] = config.get('request_timeout_content', constants.DEFAULT_TIMEOUT_CONTENT)

        config['download_js'] = config.get('download_js', False)
        config['download_css'] = config.get('download_css', False) # Default False based on original? Let's keep True
        config['download_images'] = config.get('download_images', False) # Default False based on original? Let's keep True
        config['save_original_html'] = config.get('save_original_html', False) # Default False based on original? Let's keep True
        config['rewrite_asset_links'] = config.get('rewrite_asset_links', True) 
        config['asset_save_structure'] = config.get('asset_save_structure', 'per_page')

        # --- Further Validation (Optional but Recommended) ---
        # Example: Validate numeric types/ranges
        if not isinstance(config['request_delay_seconds'], (int, float)) or config['request_delay_seconds'] < 0:
             raise ValueError("Config 'request_delay_seconds' must be a non-negative number.")
        if not isinstance(config['max_retries'], int) or config['max_retries'] < 0:
             raise ValueError("Config 'max_retries' must be a non-negative integer.")
        # Add more type/value validations as needed...

        # Validate asset_save_structure
        if config['asset_save_structure'] not in ['per_page']: # Add 'central' if implemented later
            # Use print here as logging might not be configured yet
            print(f"Warning: Invalid asset_save_structure '{config['asset_save_structure']}' in config. Defaulting to 'per_page'.", file=sys.stderr)
            config['asset_save_structure'] = 'per_page'

        return config
        
    except FileNotFoundError:
        # Let the original exception propagate or raise a more specific one if needed
        # print(f"Error: Configuration file not found at {config_path}", file=sys.stderr)
        raise # Re-raise the FileNotFoundError
    except json.JSONDecodeError as e:
        # Raise a more informative error, potentially wrapping the original
        # print(f"Error: Could not decode JSON from {config_path}", file=sys.stderr)
        raise ValueError(f"Error decoding JSON from config file '{config_path}': {e}") from e
    except ValueError as e:
        # Let the ValueError raised during validation propagate
        # print(f"Error: Invalid configuration: {e}", file=sys.stderr)
        raise # Re-raise the ValueError
    except Exception as e: # Catch any other unexpected errors during loading/validation
        # Wrap unexpected errors
        # print(f"An unexpected error occurred loading configuration: {e}", file=sys.stderr)
        raise RuntimeError(f"An unexpected error occurred loading configuration from '{config_path}': {e}") from e