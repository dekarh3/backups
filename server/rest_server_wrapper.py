#!/usr/bin/env python3
"""
Rest Server wrapper configuration and management.
Manages rest-server process for receiving restic backups over HTTPS.
"""

import os
import subprocess
import signal
import sys
from pathlib import Path

class RestServerManager:
    def __init__(self, config):
        self.config = config
        self.process = None
        
    def start(self):
        """Start rest-server process"""
        restic_root = self.config.get('global', 'restic_root', fallback='/srv/backups/restic')
        cert_file = self.config.get('rest-server', 'cert_file', fallback='/opt/backups/ssl/server.crt')
        key_file = self.config.get('rest-server', 'key_file', fallback='/opt/backups/ssl/server.key')
        htpasswd_file = self.config.get('rest-server', 'htpasswd_file', fallback='/opt/backups/auth/restic.htpasswd')
        port = self.config.get('rest-server', 'port', fallback='8443')
        
        cmd = [
            'rest-server',
            '--path', restic_root,
            '--tls-cert', cert_file,
            '--tls-key', key_file,
            '--htpasswd-file', htpasswd_file,
            '--listen', f':{port}',
            '--append-only',
            '--private-repos'
        ]
        
        print(f"Starting rest-server: {' '.join(cmd)}")
        self.process = subprocess.Popen(cmd)
        return self.process
    
    def stop(self):
        """Stop rest-server process"""
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.process = None
    
    def restart(self):
        """Restart rest-server process"""
        self.stop()
        return self.start()


def main():
    import configparser
    config = configparser.ConfigParser()
    config_file = '/opt/backups/ini/backups.ini'
    
    if os.path.exists(config_file):
        config.read(config_file)
    
    manager = RestServerManager(config)
    
    def signal_handler(sig, frame):
        print("Shutting down rest-server...")
        manager.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    manager.start()
    manager.process.wait()


if __name__ == '__main__':
    main()
