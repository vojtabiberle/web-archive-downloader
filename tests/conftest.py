import pytest
import sys
import os
import logging; logging.basicConfig(level=logging.DEBUG) 

# Ensure the project root is in the Python path for imports in tests
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Example of how a shared fixture might look (e.g., for mocking requests)
# We don't need it active yet, but shows the structure.
# from unittest.mock import MagicMock
#
# @pytest.fixture
# def mock_requests_session(mocker):
#     """Mocks the requests.Session used by API clients."""
#     mock_session = MagicMock()
#     # Configure mock responses as needed for specific tests
#     # mock_session.get.return_value.status_code = 200
#     # mock_session.get.return_value.json.return_value = {"data": "mock"}
#     mocker.patch('requests.Session', return_value=mock_session)
#     return mock_session

# Add other shared fixtures here as needed (e.g., mock config objects, temp directories)

print("conftest.py loaded") # Optional: to confirm pytest finds it

@pytest.fixture(autouse=True)
def configure_logging(caplog):
    """Ensure logging is configured to capture DEBUG level messages for all tests."""
    caplog.set_level(logging.DEBUG, logger="root") # Set root logger level
    # You can also set levels for specific loggers if needed:
    # caplog.set_level(logging.DEBUG, logger="api_clients.decorators")