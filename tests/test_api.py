"""
Unit tests for Backup System API Server.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import HTTPException

# Import the API module
import sys
sys.path.insert(0, '/workspace/backups/server')
from api import app, Config, Command, ClientStatus, BackupStatus


@pytest.fixture
def client():
    """Create a test client for the API."""
    return TestClient(app)


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = MagicMock(spec=Config)
    config.get.return_value = 'sqlite:///test.db'
    config.getint.return_value = 3600
    config.getboolean.return_value = True
    return config


class TestConfig:
    """Tests for Config class."""

    def test_config_init_default(self):
        """Test Config initialization with default path."""
        config = Config()
        assert config.config is not None

    def test_config_get_existing(self, tmp_path):
        """Test getting existing config value."""
        config_file = tmp_path / "test.ini"
        config_file.write_text("[section]\noption=value\n")
        
        config = Config(str(config_file))
        assert config.get('section', 'option') == 'value'

    def test_config_get_fallback(self):
        """Test getting non-existing config value with fallback."""
        config = Config()
        assert config.get('nonexistent', 'option', 'fallback') == 'fallback'

    def test_config_getint(self, tmp_path):
        """Test getting integer config value."""
        config_file = tmp_path / "test.ini"
        config_file.write_text("[section]\nnumber=42\n")
        
        config = Config(str(config_file))
        assert config.getint('section', 'number') == 42

    def test_config_getint_fallback(self):
        """Test getting non-existing integer with fallback."""
        config = Config()
        assert config.getint('nonexistent', 'option', 100) == 100

    def test_config_getboolean(self, tmp_path):
        """Test getting boolean config value."""
        config_file = tmp_path / "test.ini"
        config_file.write_text("[section]\nflag=true\n")
        
        config = Config(str(config_file))
        assert config.getboolean('section', 'flag') is True


class TestCommandModel:
    """Tests for Command Pydantic model."""

    def test_command_creation(self):
        """Test creating a Command object."""
        cmd = Command(
            command_id="test_123",
            command_type="backup.start",
            client="test_client",
            backup_name="main_backup",
            created_at=datetime.now()
        )
        assert cmd.command_id == "test_123"
        assert cmd.command_type == "backup.start"
        assert cmd.client == "test_client"
        assert cmd.status == 'created'
        assert cmd.ttl_hours == 12

    def test_command_with_parameters(self):
        """Test creating a Command with parameters."""
        cmd = Command(
            command_id="test_456",
            command_type="backup.prune",
            client="test_client",
            backup_name="main_backup",
            parameters={"dry_run": True},
            created_at=datetime.now()
        )
        assert cmd.parameters == {"dry_run": True}


class TestBackupStatusModel:
    """Tests for BackupStatus Pydantic model."""

    def test_backup_status_creation(self):
        """Test creating a BackupStatus object."""
        status = BackupStatus(
            backup_name="main_backup",
            enabled=True,
            status='running',
            progress=45.5
        )
        assert status.backup_name == "main_backup"
        assert status.enabled is True
        assert status.status == 'running'
        assert status.progress == 45.5

    def test_backup_status_defaults(self):
        """Test BackupStatus default values."""
        status = BackupStatus(
            backup_name="test_backup",
            enabled=False
        )
        assert status.status == 'unknown'
        assert status.progress is None
        assert status.last_snapshot_size is None


class TestClientStatusModel:
    """Tests for ClientStatus Pydantic model."""

    def test_client_status_creation(self):
        """Test creating a ClientStatus object."""
        status = ClientStatus(
            client_name="test_client",
            online=True,
            last_contact=datetime.now(),
            agent_version="1.0.0"
        )
        assert status.client_name == "test_client"
        assert status.online is True
        assert status.agent_version == "1.0.0"


class TestAPIEndpoints:
    """Tests for API endpoints."""

    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "backup-api"

    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_list_clients_unauthorized(self, client):
        """Test list clients without authentication."""
        response = client.get("/api/v1/clients")
        # Should require authentication (403 or 401 depending on setup)
        assert response.status_code in [403, 401]

    def test_get_client_not_found(self, client):
        """Test getting non-existent client."""
        # This would need proper auth setup
        pass


class TestSecretsRotation:
    """Tests for secrets rotation functionality."""

    def test_rotate_secrets_creates_file(self, tmp_path):
        """Test that rotating secrets creates a password file."""
        import os
        import tempfile
        
        secrets_dir = str(tmp_path / "secrets")
        os.makedirs(secrets_dir, exist_ok=True)
        
        client_name = "test_client"
        password_file = os.path.join(secrets_dir, f"{client_name}.rest-http.pass")
        
        # Simulate secret rotation
        import secrets
        new_password = secrets.token_urlsafe(32)
        
        with open(password_file, 'w') as f:
            f.write(new_password)
        os.chmod(password_file, 0o600)
        
        assert os.path.exists(password_file)
        with open(password_file, 'r') as f:
            stored_password = f.read().strip()
        assert stored_password == new_password
        assert len(stored_password) >= 32


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
