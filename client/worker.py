#!/usr/bin/env python3
"""
Worker - Backup execution process.
Runs restic backup command for a specific backup configuration.
"""

import os
import sys
import json
import time
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import configparser

try:
    import requests
except ImportError:
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('worker')


class BackupWorker:
    def __init__(self, config, client_name: str, backup_name: str, run_id: str):
        self.config = config
        self.client_name = client_name
        self.backup_name = backup_name
        self.run_id = run_id
        self.running = True
        self.process = None
        
        # Load backup-specific configuration
        self.backup_config = self._load_backup_config()
        
        # API settings
        self.api_url = config.get('global', 'api_url', fallback='https://localhost:9443')
        self.agent_token = self._load_agent_token()
    
    def _load_backup_config(self) -> Dict[str, Any]:
        """Load backup-specific configuration"""
        backup_config_file = f'/opt/backups/ini/backups/{self.client_name}.{self.backup_name}.ini'
        config = configparser.ConfigParser()
        
        if os.path.exists(backup_config_file):
            config.read(backup_config_file)
            
            return {
                'enabled': config.getboolean('backup', 'enabled', fallback=True),
                'repository_url': config.get('backup', 'repository_url', fallback=''),
                'schedule': config.get('backup', 'schedule', fallback=''),
                'quota_gb': config.getint('backup', 'quota_gb', fallback=0),
                'script': config.get('backup', 'script', fallback=''),
                'script_mode': config.get('backup', 'script_mode', fallback='file'),
                'retention_days': config.getint('backup', 'retention_days', fallback=31),
                'restic_extra_args': config.get('backup', 'restic_extra_args', fallback=''),
                'max_network_kbit_per_sec': config.getint('backup', 'max_network_kbit_per_sec', fallback=0),
                'respect_calendar': config.getboolean('backup', 'respect_calendar', fallback=False)
            }
        
        return {}
    
    def _load_agent_token(self) -> Optional[str]:
        """Load agent authentication token"""
        token_file = self.config.get('client', 'client_agent_token_file', fallback='')
        if token_file and os.path.exists(token_file):
            with open(token_file, 'r') as f:
                return f.read().strip()
        return None
    
    def _get_rest_server_credentials(self) -> tuple:
        """Get rest-server credentials"""
        client_config_file = f'/opt/backups/ini/clients/{self.client_name}.ini'
        config = configparser.ConfigParser()
        
        if os.path.exists(client_config_file):
            config.read(client_config_file)
            
            username = config.get('client', 'rest_http_user', fallback=self.client_name)
            password_file = config.get('client', 'rest_http_password_file', fallback='')
            
            password = ''
            if password_file and os.path.exists(password_file):
                with open(password_file, 'r') as f:
                    password = f.read().strip()
            
            return username, password
        
        return self.client_name, ''
    
    def run_prepare_script(self) -> bool:
        """Run prepare script if configured"""
        script = self.backup_config.get('script', '')
        if not script:
            return True
        
        timeout = self.backup_config.get('backup_prepare_timeout_sec', 600)
        
        logger.info(f"Running prepare script: {script}")
        
        try:
            result = subprocess.run(
                [sys.executable, script, '--prepare'],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode != 0:
                logger.error(f"Prepare script failed: {result.stderr}")
                return False
            
            logger.info("Prepare script completed successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"Prepare script timed out after {timeout}s")
            return False
        except Exception as e:
            logger.error(f"Prepare script error: {e}")
            return False
    
    def run_backup(self) -> bool:
        """Execute restic backup command"""
        repository_url = self.backup_config.get('repository_url', '')
        if not repository_url:
            logger.error("No repository URL configured")
            return False
        
        username, password = self._get_rest_server_credentials()
        
        # Build restic command
        cmd = ['restic', 'backup']
        
        # Add repository
        cmd.extend(['-r', repository_url])
        
        # Add credentials via environment
        env = os.environ.copy()
        env['RESTIC_PASSWORD'] = password
        env['RESTIC_REPOSITORY'] = repository_url
        
        # Add authentication headers for rest-server
        # Note: restic supports --option restic-server.username for HTTP auth
        
        # Add extra arguments
        extra_args = self.backup_config.get('restic_extra_args', '')
        if extra_args:
            cmd.extend(extra_args.split())
        
        # Add bandwidth limit
        max_kbit = self.backup_config.get('max_network_kbit_per_sec', 0)
        if max_kbit > 0:
            cmd.extend(['--limit-upload', str(max_kbit)])
        
        # Add tags for identification
        cmd.extend(['--tag', f'run-id={self.run_id}'])
        cmd.extend(['--tag', f'client={self.client_name}'])
        cmd.extend(['--tag', f'backup={self.backup_name}'])
        
        # Get paths to backup from prepare script output or config
        # For now, use default paths
        paths_to_backup = self._get_paths_to_backup()
        cmd.extend(paths_to_backup)
        
        logger.info(f"Running restic: {' '.join(cmd)}")
        
        try:
            self.process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Stream output
            for line in self.process.stderr:
                if self.running:
                    logger.info(line.strip())
            
            self.process.wait()
            
            if self.process.returncode == 0:
                logger.info("Backup completed successfully")
                return True
            else:
                logger.error(f"Backup failed with code {self.process.returncode}")
                return False
                
        except Exception as e:
            logger.error(f"Backup error: {e}")
            return False
    
    def _get_paths_to_backup(self) -> list:
        """Get paths to backup (from config or prepare script output)"""
        # Default paths - should be configured per backup
        # This is a placeholder implementation
        return ['/home']  # Example path
    
    def send_progress(self, progress_data: Dict[str, Any]):
        """Send progress update to API server"""
        if not requests:
            return
        
        url = f"{self.api_url}/api/v1/clients/{self.client_name}/backups/{self.backup_name}/progress"
        headers = {
            'Authorization': f'Bearer {self.agent_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            requests.post(url, json=progress_data, headers=headers, timeout=30)
        except Exception as e:
            logger.error(f"Error sending progress: {e}")
    
    def send_result(self, success: bool, message: str = ''):
        """Send backup result to API server"""
        if not requests:
            return
        
        url = f"{self.api_url}/api/v1/clients/{self.client_name}/backups/{self.backup_name}/result"
        headers = {
            'Authorization': f'Bearer {self.agent_token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'run_id': self.run_id,
            'success': success,
            'message': message,
            'completed_at': datetime.now().isoformat()
        }
        
        try:
            requests.post(url, json=data, headers=headers, timeout=30)
        except Exception as e:
            logger.error(f"Error sending result: {e}")
    
    def run(self):
        """Main worker loop"""
        logger.info(f"Worker started for {self.client_name}/{self.backup_name} (run_id: {self.run_id})")
        
        start_time = datetime.now()
        
        # Run prepare script
        if not self.run_prepare_script():
            self.send_result(False, "Prepare script failed")
            return
        
        # Run backup
        success = self.run_backup()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Send result
        if success:
            self.send_result(True, f"Backup completed in {duration:.0f}s")
        else:
            self.send_result(False, "Backup failed")
    
    def stop(self):
        """Stop the backup process"""
        logger.info("Stopping backup...")
        self.running = False
        
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.process.kill()


def load_config(config_file: str = ''):
    """Load client configuration"""
    config = configparser.ConfigParser()
    
    config_files = [
        config_file,
        '/opt/backups/ini/client.ini',
        '/opt/backups/ini/backups.ini'
    ] if config_file else [
        '/opt/backups/ini/client.ini',
        '/opt/backups/ini/backups.ini'
    ]
    
    for cf in config_files:
        if cf and os.path.exists(cf):
            config.read(cf)
            break
    
    return config


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Backup Worker')
    parser.add_argument('--client', required=True, help='Client name')
    parser.add_argument('--backup', required=True, help='Backup name')
    parser.add_argument('--run-id', required=True, help='Unique run identifier')
    parser.add_argument('--config', help='Config file path')
    args = parser.parse_args()
    
    config = load_config(args.config)
    
    worker = BackupWorker(config, args.client, args.backup, args.run_id)
    
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        worker.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()
    except Exception as e:
        logger.error(f"Worker error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
