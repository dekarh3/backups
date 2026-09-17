#!/usr/bin/env python3
"""
Manager - Client agent for backup system.
Handles communication with API server, receives commands, manages worker processes.
Uses long-polling for command retrieval.
"""

import os
import sys
import json
import time
import signal
import logging
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import configparser

try:
    import requests
except ImportError:
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('manager')


class BackupManager:
    def __init__(self, config):
        self.config = config
        self.client_name = config.get('client', 'name', fallback='unknown')
        self.api_url = config.get('global', 'api_url', fallback='https://localhost:9443')
        self.agent_token_file = config.get('client', 'client_agent_token_file', fallback='')
        self.running = True
        self.active_backups = {}  # backup_name -> process
        self.executed_commands = set()  # Track executed command_ids for idempotency
        self.last_contact = None
        self.agent_version = "1.0.0"
        
        # Load agent token
        self.agent_token = self._load_token()
    
    def _load_token(self) -> Optional[str]:
        """Load agent authentication token"""
        if self.agent_token_file and os.path.exists(self.agent_token_file):
            with open(self.agent_token_file, 'r') as f:
                return f.read().strip()
        return None
    
    def send_status(self, status_data: Dict[str, Any]):
        """Send status to API server"""
        if not requests:
            logger.error("requests library not available")
            return False
        
        url = f"{self.api_url}/api/v1/clients/{self.client_name}/status"
        headers = {
            'Authorization': f'Bearer {self.agent_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(url, json=status_data, headers=headers, timeout=30)
            if response.status_code == 200:
                self.last_contact = datetime.now()
                return True
            else:
                logger.warning(f"Status upload failed: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error sending status: {e}")
            return False
    
    def get_commands(self, timeout: int = 30) -> List[Dict[str, Any]]:
        """Get commands from API server using long-polling"""
        if not requests:
            logger.error("requests library not available")
            return []
        
        url = f"{self.api_url}/api/v1/clients/{self.client_name}/commands"
        headers = {
            'Authorization': f'Bearer {self.agent_token}'
        }
        params = {'timeout': timeout}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout + 10)
            if response.status_code == 200:
                data = response.json()
                return data.get('commands', [])
            else:
                logger.warning(f"Command fetch failed: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching commands: {e}")
            return []
    
    def execute_command(self, command: Dict[str, Any]):
        """Execute a command"""
        command_id = command.get('command_id')
        command_type = command.get('command_type')
        
        # Idempotency check
        if command_id in self.executed_commands:
            logger.info(f"Command {command_id} already executed, skipping")
            return
        
        logger.info(f"Executing command: {command_type} (id: {command_id})")
        
        try:
            if command_type == 'manager.status':
                self._cmd_status()
            elif command_type == 'manager.config':
                self._cmd_config(command.get('parameters', {}))
            elif command_type.startswith('manager.') and command_type.endswith('.script'):
                backup_name = command_type.split('.')[1]
                self._cmd_script(backup_name, command.get('parameters', {}))
            elif command_type.startswith('manager.') and command_type.endswith('.start'):
                backup_name = command_type.split('.')[1]
                self._cmd_start(backup_name, command.get('parameters', {}), command_id)
            elif command_type.startswith('manager.') and command_type.endswith('.stop'):
                backup_name = command_type.split('.')[1]
                self._cmd_stop(backup_name)
            elif command_type.startswith('manager.') and command_type.endswith('.restart'):
                backup_name = command_type.split('.')[1]
                self._cmd_restart(backup_name, command_id)
            elif command_type.startswith('manager.') and command_type.endswith('.abort_cleanup'):
                backup_name = command_type.split('.')[1]
                self._cmd_abort_cleanup(backup_name)
            elif command_type == 'client.stack.restart':
                self._cmd_stack_restart()
            else:
                logger.warning(f"Unknown command type: {command_type}")
            
            # Mark as executed
            self.executed_commands.add(command_id)
            
            # Send acknowledgment
            self._send_ack(command_id, 'success')
            
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            self._send_ack(command_id, 'failed', str(e))
    
    def _cmd_status(self):
        """Handle status request"""
        status = self.get_full_status()
        self.send_status(status)
    
    def _cmd_config(self, parameters: Dict[str, Any]):
        """Update client configuration"""
        logger.info(f"Updating configuration: {parameters}")
        # Implementation for config update
    
    def _cmd_script(self, backup_name: str, parameters: Dict[str, Any]):
        """Update backup script"""
        logger.info(f"Updating script for {backup_name}")
        # Implementation for script update
    
    def _cmd_start(self, backup_name: str, parameters: Dict[str, Any], command_id: str):
        """Start backup"""
        if backup_name in self.active_backups:
            logger.info(f"Backup {backup_name} already running")
            return
        
        logger.info(f"Starting backup: {backup_name}")
        
        # Start worker process
        script_dir = os.path.dirname(os.path.abspath(__file__))
        worker_path = os.path.join(script_dir, 'worker.py')
        
        cmd = [
            sys.executable, worker_path,
            '--client', self.client_name,
            '--backup', backup_name,
            '--run-id', command_id
        ]
        
        process = subprocess.Popen(cmd)
        self.active_backups[backup_name] = process
        logger.info(f"Backup {backup_name} started with PID {process.pid}")
    
    def _cmd_stop(self, backup_name: str):
        """Stop backup"""
        if backup_name not in self.active_backups:
            logger.info(f"Backup {backup_name} not running")
            return
        
        logger.info(f"Stopping backup: {backup_name}")
        process = self.active_backups[backup_name]
        process.terminate()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
        
        del self.active_backups[backup_name]
    
    def _cmd_restart(self, backup_name: str, command_id: str):
        """Restart backup"""
        self._cmd_stop(backup_name)
        time.sleep(2)
        self._cmd_start(backup_name, {}, command_id)
    
    def _cmd_abort_cleanup(self, backup_name: str):
        """Stop backup and cleanup incomplete data"""
        logger.info(f"Aborting and cleaning up: {backup_name}")
        self._cmd_stop(backup_name)
        # Cleanup incomplete snapshot data
        # Implementation depends on restic repository structure
    
    def _cmd_stack_restart(self):
        """Emergency restart of client stack"""
        logger.info("Restarting client stack...")
        # This will cause cerber to restart all processes
        os._exit(0)
    
    def _send_ack(self, command_id: str, status: str, message: str = ''):
        """Send acknowledgment to API server"""
        if not requests:
            return
        
        url = f"{self.api_url}/api/v1/clients/{self.client_name}/commands/{command_id}/ack"
        headers = {
            'Authorization': f'Bearer {self.agent_token}',
            'Content-Type': 'application/json'
        }
        data = {
            'command_id': command_id,
            'status': status,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            requests.post(url, json=data, headers=headers, timeout=30)
        except Exception as e:
            logger.error(f"Error sending acknowledgment: {e}")
    
    def get_full_status(self) -> Dict[str, Any]:
        """Get full client status"""
        backups = {}
        for backup_name, process in self.active_backups.items():
            backups[backup_name] = {
                'running': True,
                'pid': process.pid,
                'status': 'running' if process.poll() is None else 'stopped'
            }
        
        return {
            'client_name': self.client_name,
            'online': True,
            'last_contact': self.last_contact.isoformat() if self.last_contact else None,
            'agent_version': self.agent_version,
            'active_backups': backups,
            'timestamp': datetime.now().isoformat()
        }
    
    def run(self):
        """Main manager loop"""
        logger.info(f"Manager started for client: {self.client_name}")
        
        # Initial status report
        self.send_status(self.get_full_status())
        
        while self.running:
            # Get commands (long-polling with 30s timeout)
            commands = self.get_commands(timeout=30)
            
            # Execute received commands
            for command in commands:
                self.execute_command(command)
            
            # Periodic status update
            if self.last_contact is None or (datetime.now() - self.last_contact).total_seconds() > 300:
                self.send_status(self.get_full_status())
        
        # Cleanup
        self.stop()
    
    def stop(self):
        """Stop all active backups"""
        logger.info("Stopping manager...")
        self.running = False
        
        for backup_name in list(self.active_backups.keys()):
            self._cmd_stop(backup_name)


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
    parser = argparse.ArgumentParser(description='Backup Manager Agent')
    parser.add_argument('--client', help='Client name')
    parser.add_argument('--config', help='Config file path')
    args = parser.parse_args()
    
    config = load_config(args.config)
    
    if args.client:
        if not config.has_section('client'):
            config.add_section('client')
        config.set('client', 'name', args.client)
    
    manager = BackupManager(config)
    
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        manager.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        manager.run()
    except KeyboardInterrupt:
        manager.stop()
    except Exception as e:
        logger.error(f"Manager error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
