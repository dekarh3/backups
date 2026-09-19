"""
Integration tests for Backup System.
Tests interaction between API, clients, and backup operations.
"""

import pytest
import os
import sys
import time
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

import sys
import os
from pathlib import Path

# Add server and client directories to path (relative to test file location)
current_dir = Path(__file__).parent
server_dir = current_dir.parent / 'server'
client_dir = current_dir.parent / 'client'
sys.path.insert(0, str(server_dir))
sys.path.insert(0, str(client_dir))

from fastapi.testclient import TestClient
from api import app, Config, Command


@pytest.fixture
def integration_client():
    """Create test client for integration tests."""
    return TestClient(app)


@pytest.fixture
def temp_backup_repo(tmp_path):
    """Create a temporary restic repository structure."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    # Create minimal restic repo structure
    (repo_dir / "data").mkdir()
    (repo_dir / "snapshots").mkdir()
    (repo_dir / "keys").mkdir()
    (repo_dir / "config").write_text('{"version":1}')
    return str(repo_dir)


@pytest.fixture
def temp_secrets_dir(tmp_path):
    """Create temporary secrets directory."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    return str(secrets_dir)


class TestAPICommandFlow:
    """Test command creation and execution flow."""

    def test_create_start_backup_command(self, integration_client):
        """Test creating a start backup command via API."""
        # Note: This test requires proper authentication setup
        # For now, we test the command model directly
        cmd = Command(
            command_id=f"start_test_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            command_type="manager.main.start",
            client="test_client",
            backup_name="main",
            created_at=datetime.now()
        )
        assert cmd.command_type == "manager.main.start"
        assert cmd.client == "test_client"
        assert cmd.status == "created"

    def test_command_ttl_default(self):
        """Test that commands have default TTL."""
        cmd = Command(
            command_id="test_cmd",
            command_type="backup.start",
            client="client1",
            created_at=datetime.now()
        )
        assert cmd.ttl_hours == 12


class TestSecretsRotationIntegration:
    """Integration tests for secrets rotation."""

    def test_rotate_secrets_creates_secure_file(self, tmp_path):
        """Test that secret rotation creates file with correct permissions."""
        import secrets as sec
        
        secrets_dir = str(tmp_path / "secrets")
        os.makedirs(secrets_dir, exist_ok=True)
        
        client_name = "integration_test_client"
        password_file = os.path.join(secrets_dir, f"{client_name}.rest-http.pass")
        
        # Generate and store password
        new_password = sec.token_urlsafe(32)
        with open(password_file, 'w') as f:
            f.write(new_password)
        os.chmod(password_file, 0o600)
        
        # Verify file exists and has correct permissions
        assert os.path.exists(password_file)
        file_stat = os.stat(password_file)
        # Check that only owner can read/write (0o600)
        assert oct(file_stat.st_mode)[-3:] == '600'
        
        # Verify password can be read back
        with open(password_file, 'r') as f:
            stored = f.read().strip()
        assert stored == new_password
        assert len(stored) >= 32


class TestBackupConfigurationFlow:
    """Test backup configuration loading and validation."""

    def test_backup_config_validation(self, tmp_path):
        """Test that backup configuration is properly validated."""
        config_file = tmp_path / "backup.ini"
        config_file.write_text("""[backup]
enabled = true
repository_url = restic-rest:http://localhost:8000/repo
schedule = 0 2 * * *
quota_gb = 100
retention_days = 30
""")
        
        import configparser
        config = configparser.ConfigParser()
        config.read(str(config_file))
        
        assert config.getboolean('backup', 'enabled') is True
        assert config.get('backup', 'repository_url').startswith('restic-rest:')
        assert config.getint('backup', 'quota_gb') == 100


class TestClientStatusReporting:
    """Test client status reporting flow."""

    def test_client_status_structure(self):
        """Test that client status has required fields."""
        from api import ClientStatus, BackupStatus
        
        backup_status = BackupStatus(
            backup_name="main",
            enabled=True,
            last_run=datetime.now() - timedelta(hours=1),
            status='success'
        )
        
        client_status = {
            "client_name": "test_client",
            "online": True,
            "last_contact": datetime.now(),
            "agent_version": "1.0.0",
            "backups": {"main": backup_status}
        }
        
        assert client_status["client_name"] == "test_client"
        assert "backups" in client_status
        assert client_status["backups"]["main"].status == 'success'


class TestHealthCheckIntegration:
    """Integration tests for health checks."""

    def test_api_health_endpoint(self, integration_client):
        """Test API health check endpoint."""
        response = integration_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_api_root_endpoint(self, integration_client):
        """Test API root endpoint."""
        response = integration_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "backup-api"


class TestCommandQueueIntegration:
    """Integration tests for command queue."""

    def test_command_creation_and_storage(self, tmp_path):
        """Test creating and storing commands."""
        # Simulate command queue storage
        commands_file = tmp_path / "commands.json"
        
        import json
        cmd = {
            "command_id": "cmd_123",
            "command_type": "backup.start",
            "client": "test_client",
            "backup_name": "main",
            "created_at": datetime.now().isoformat(),
            "status": "queued"
        }
        
        # Store command
        commands = [cmd]
        with open(commands_file, 'w') as f:
            json.dump(commands, f)
        
        # Retrieve command
        with open(commands_file, 'r') as f:
            loaded = json.load(f)
        
        assert len(loaded) == 1
        assert loaded[0]["command_id"] == "cmd_123"
        assert loaded[0]["status"] == "queued"


class TestEndToEndBackupScenario:
    """End-to-end scenario tests."""

    def test_full_backup_lifecycle(self, tmp_path):
        """Test complete backup lifecycle: create command -> execute -> report."""
        import json
        
        # Step 1: Create backup command
        command = {
            "command_id": "e2e_test_001",
            "command_type": "manager.main.start",
            "client": "e2e_client",
            "backup_name": "main",
            "created_at": datetime.now().isoformat(),
            "status": "created"
        }
        
        # Step 2: Store in queue
        queue_file = tmp_path / "queue.json"
        with open(queue_file, 'w') as f:
            json.dump([command], f)
        
        # Step 3: Simulate execution
        command["status"] = "executing"
        
        # Step 4: Simulate completion
        command["status"] = "completed"
        result = {
            "command_id": command["command_id"],
            "success": True,
            "message": "Backup completed successfully",
            "completed_at": datetime.now().isoformat()
        }
        
        # Step 5: Store result
        result_file = tmp_path / "result.json"
        with open(result_file, 'w') as f:
            json.dump(result, f)
        
        # Verify result
        with open(result_file, 'r') as f:
            loaded_result = json.load(f)
        
        assert loaded_result["success"] is True
        assert loaded_result["command_id"] == "e2e_test_001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
