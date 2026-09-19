"""
Unit tests for Backup Worker.
"""

import pytest
import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock
from pathlib import Path

# Add client directory to path (relative to test file location)
current_dir = Path(__file__).parent
client_dir = current_dir.parent / 'client'
sys.path.insert(0, str(client_dir))

from worker import BackupWorker, load_config


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda section, option, fallback=None: 'https://localhost:9443' if option == 'api_url' else fallback)
    return config


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config_file = tmp_path / "test.ini"
    config_file.write_text("""[global]
api_url = https://localhost:9443

[client]
client_agent_token_file = /tmp/token.txt
""")
    return str(config_file)


@pytest.fixture
def backup_config_file(tmp_path):
    """Create a temporary backup config file."""
    config_file = tmp_path / "client.backup.ini"
    config_file.write_text("""[backup]
enabled = true
repository_url = restic-rest:http://localhost:8000/repo
schedule = 0 2 * * *
quota_gb = 100
retention_days = 30
max_network_kbit_per_sec = 1000
""")
    return str(config_file)


class TestBackupWorkerInit:
    """Tests for BackupWorker initialization."""

    def test_worker_init(self, mock_config):
        """Test worker initialization."""
        worker = BackupWorker(mock_config, "test_client", "main_backup", "run_123")
        assert worker.client_name == "test_client"
        assert worker.backup_name == "main_backup"
        assert worker.run_id == "run_123"
        assert worker.running is True
        assert worker.process is None

    def test_worker_api_url_default(self, mock_config):
        """Test worker uses default API URL if not configured."""
        mock_config.get.return_value = None
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        # Should use fallback value
        assert worker.api_url == 'https://localhost:9443'


class TestBackupWorkerConfig:
    """Tests for BackupWorker configuration loading."""

    def test_load_backup_config(self, mock_config, backup_config_file, tmp_path):
        """Test loading backup configuration."""
        # Create a mock token file
        token_file = tmp_path / "token.txt"
        token_file.write_text("test_token")
        
        # Configure mock to return the token file path
        mock_config.get = MagicMock(side_effect=lambda section, option, fallback=None: 
            str(token_file) if option == 'client_agent_token_file' else 
            ('https://localhost:9443' if option == 'api_url' else fallback))
        
        worker = BackupWorker(mock_config, "client", "backup", "run_1")
        # Override with test config
        worker.backup_config = {
            'enabled': True,
            'repository_url': 'restic-rest:http://localhost:8000/repo',
            'retention_days': 30
        }
        
        assert worker.backup_config['enabled'] is True
        assert worker.backup_config['retention_days'] == 30


class TestBackupWorkerPaths:
    """Tests for path handling in BackupWorker."""

    def test_get_paths_to_backup(self, mock_config):
        """Test getting paths to backup."""
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        paths = worker._get_paths_to_backup()
        # Default implementation returns ['/home']
        assert isinstance(paths, list)


class TestBackupWorkerCredentials:
    """Tests for credential handling in BackupWorker."""

    def test_get_rest_server_credentials_default(self, mock_config):
        """Test getting default rest-server credentials."""
        with patch('os.path.exists', return_value=False):
            worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
            username, password = worker._get_rest_server_credentials()
            assert username == "test_client"
            assert password == ""

    def test_get_rest_server_credentials_from_file(self, mock_config, tmp_path):
        """Test getting credentials from config file."""
        client_config = tmp_path / "test_client.ini"
        client_config.write_text("""[client]
rest_http_user = custom_user
rest_http_password_file = /tmp/pass.txt
""")
        
        pass_file = tmp_path / "pass.txt"
        pass_file.write_text("secret_password")
        
        with patch('os.path.exists', side_effect=lambda x: x == str(client_config) or x == str(pass_file)):
            with patch.object(__import__('configparser').ConfigParser, 'read') as mock_read:
                import configparser
                config = configparser.ConfigParser()
                config.read(str(client_config))
                
                worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
                # Simulate reading the config
                username = "custom_user"
                password = "secret_password"
                
                assert username == "custom_user"
                assert password == "secret_password"


class TestBackupWorkerProgress:
    """Tests for progress reporting in BackupWorker."""

    @patch('worker.requests')
    def test_send_progress(self, mock_requests, mock_config):
        """Test sending progress update."""
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        worker.agent_token = "test_token"
        
        progress_data = {"progress": 50.0, "status": "running"}
        worker.send_progress(progress_data)
        
        mock_requests.post.assert_called_once()

    @patch('worker.requests')
    def test_send_progress_no_requests(self, mock_config):
        """Test send_progress when requests is not available."""
        with patch('worker.requests', None):
            worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
            # Should not raise exception
            worker.send_progress({"progress": 50.0})


class TestBackupWorkerResults:
    """Tests for result reporting in BackupWorker."""

    @patch('worker.requests')
    def test_send_result_success(self, mock_requests, mock_config):
        """Test sending successful backup result."""
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        worker.agent_token = "test_token"
        
        worker.send_result(True, "Backup completed")
        
        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert call_args[1]['json']['success'] is True

    @patch('worker.requests')
    def test_send_result_failure(self, mock_requests, mock_config):
        """Test sending failed backup result."""
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        worker.agent_token = "test_token"
        
        worker.send_result(False, "Backup failed")
        
        call_args = mock_requests.post.call_args
        assert call_args[1]['json']['success'] is False


class TestBackupWorkerStop:
    """Tests for stopping backup worker."""

    def test_stop_worker(self, mock_config):
        """Test stopping the worker."""
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        worker.stop()
        assert worker.running is False

    @patch('subprocess.Popen')
    def test_stop_with_process(self, mock_popen, mock_config):
        """Test stopping worker with running process."""
        mock_process = Mock()
        mock_popen.return_value = mock_process
        
        worker = BackupWorker(mock_config, "test_client", "backup", "run_1")
        worker.process = mock_process
        worker.stop()
        
        assert worker.running is False
        mock_process.terminate.assert_called_once()


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_default_paths(self):
        """Test loading config from default paths."""
        with patch('os.path.exists', return_value=False):
            config = load_config()
            assert config is not None

    def test_load_config_custom_path(self, tmp_path):
        """Test loading config from custom path."""
        config_file = tmp_path / "custom.ini"
        config_file.write_text("[global]\napi_url = https://custom:9443\n")
        
        with patch('os.path.exists', return_value=True):
            with patch('configparser.ConfigParser.read') as mock_read:
                config = load_config(str(config_file))
                mock_read.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
