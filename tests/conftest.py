"""
Pytest configuration and fixtures for Backup System tests.
"""

import pytest
import os
import sys
from pathlib import Path

# Add project paths
sys.path.insert(0, '/workspace/backups/server')
sys.path.insert(0, '/workspace/backups/client')
sys.path.insert(0, '/workspace/backups/web')


@pytest.fixture(scope="session")
def test_config():
    """Session-wide test configuration."""
    return {
        'api_url': 'https://localhost:9443',
        'rest_server_url': 'http://localhost:8000',
        'db_dsn': 'sqlite:///test_backups.db',
        'secrets_dir': '/tmp/test_secrets',
        'clients_dir': '/tmp/test_clients',
        'backups_dir': '/tmp/test_backups',
    }


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directory structure for testing."""
    dirs = {
        'secrets': tmp_path / 'secrets',
        'clients': tmp_path / 'clients',
        'backups': tmp_path / 'backups',
        'logs': tmp_path / 'logs',
    }
    
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
    
    return dirs


@pytest.fixture
def sample_client_config(tmp_path):
    """Create a sample client configuration file."""
    config_file = tmp_path / "test_client.ini"
    config_file.write_text("""[client]
name = test_client
rest_http_user = test_client
rest_http_password_file = /tmp/test_pass.txt
client_agent_token_file = /tmp/test_token.txt

[backup.main]
enabled = true
repository_url = restic-rest:http://localhost:8000/repo
schedule = 0 2 * * *
quota_gb = 100
retention_days = 30
""")
    return str(config_file)


@pytest.fixture
def sample_backup_config(tmp_path):
    """Create a sample backup configuration file."""
    config_file = tmp_path / "client.backup.ini"
    config_file.write_text("""[backup]
enabled = true
repository_url = restic-rest:http://localhost:8000/repo
schedule = 0 2 * * *
quota_gb = 100
script = 
script_mode = file
retention_days = 30
restic_extra_args = --compression max
max_network_kbit_per_sec = 1000
respect_calendar = false
""")
    return str(config_file)


@pytest.fixture
def mock_api_credentials():
    """Mock API credentials for testing."""
    return {
        'username': 'test_admin',
        'token': 'test_token_12345',
        'bearer': 'Bearer test_token_12345'
    }


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path):
    """Setup test environment before each test."""
    # Create necessary directories
    os.makedirs(tmp_path / 'secrets', exist_ok=True)
    os.makedirs(tmp_path / 'config', exist_ok=True)
    os.makedirs(tmp_path / 'logs', exist_ok=True)
    
    yield
    
    # Cleanup after test (if needed)
    pass


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (deselect with '-m \"not integration\"')"
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "requires_restic: marks tests that require restic to be installed"
    )
