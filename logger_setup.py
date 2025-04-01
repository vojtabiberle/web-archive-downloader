# Module for setting up logging
import logging
import sys
import os # Potentially needed if log_file path needs manipulation, though unlikely here

def setup_logging(log_file):
    """Sets up logging to console and file."""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # Set root logger level

    # Clear existing handlers (important if this function is called multiple times)
    # Or if running in an interactive environment like Jupyter
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # File handler
    try:
        # Ensure directory exists for log file if it's in a subdirectory
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
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

    logging.info("Logging setup complete.") # Add confirmation message