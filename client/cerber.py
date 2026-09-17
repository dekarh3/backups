#!/usr/bin/env python3
"""
Cerber - Watchdog process for backup client.
Monitors manager.py and worker.py processes, restarts them if they fail.
"""

import os
import sys
import time
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('cerber')

class Cerber:
    def __init__(self, config):
        self.config = config
        self.manager_process = None
        self.worker_process = None
        self.running = True
        self.client_name = config.get('client', 'name', fallback='unknown')
        
    def start_manager(self):
        """Start manager.py process"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        manager_path = os.path.join(script_dir, 'manager.py')
        
        cmd = [sys.executable, manager_path, '--client', self.client_name]
        logger.info(f"Starting manager: {' '.join(cmd)}")
        
        self.manager_process = subprocess.Popen(cmd)
        return self.manager_process
    
    def start_worker(self):
        """Start worker.py process (if needed)"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        worker_path = os.path.join(script_dir, 'worker.py')
        
        if os.path.exists(worker_path):
            cmd = [sys.executable, worker_path, '--client', self.client_name]
            logger.info(f"Starting worker: {' '.join(cmd)}")
            self.worker_process = subprocess.Popen(cmd)
            return self.worker_process
        return None
    
    def check_process(self, process):
        """Check if process is alive"""
        if process is None:
            return False
        return process.poll() is None
    
    def restart_manager(self):
        """Restart manager process"""
        logger.warning("Restarting manager process...")
        if self.manager_process:
            try:
                self.manager_process.terminate()
                self.manager_process.wait(timeout=10)
            except Exception as e:
                logger.error(f"Error terminating manager: {e}")
                try:
                    self.manager_process.kill()
                except:
                    pass
        
        time.sleep(2)
        return self.start_manager()
    
    def restart_worker(self):
        """Restart worker process"""
        logger.warning("Restarting worker process...")
        if self.worker_process:
            try:
                self.worker_process.terminate()
                self.worker_process.wait(timeout=10)
            except Exception as e:
                logger.error(f"Error terminating worker: {e}")
                try:
                    self.worker_process.kill()
                except:
                    pass
        
        time.sleep(2)
        if self.worker_process:
            return self.start_worker()
        return None
    
    def run(self):
        """Main watchdog loop"""
        logger.info(f"Cerber started for client: {self.client_name}")
        
        # Start initial processes
        self.start_manager()
        time.sleep(2)
        self.start_worker()
        
        while self.running:
            time.sleep(5)
            
            # Check manager
            if not self.check_process(self.manager_process):
                logger.error("Manager process died!")
                self.restart_manager()
            
            # Check worker (if it exists)
            if self.worker_process and not self.check_process(self.worker_process):
                logger.error("Worker process died!")
                self.restart_worker()
        
        # Cleanup
        self.stop()
    
    def stop(self):
        """Stop all processes"""
        logger.info("Stopping all processes...")
        self.running = False
        
        if self.manager_process:
            self.manager_process.terminate()
            try:
                self.manager_process.wait(timeout=10)
            except:
                self.manager_process.kill()
        
        if self.worker_process:
            self.worker_process.terminate()
            try:
                self.worker_process.wait(timeout=10)
            except:
                self.worker_process.kill()


def load_config():
    """Load client configuration"""
    import configparser
    config = configparser.ConfigParser()
    
    config_files = [
        '/opt/backups/ini/backups.ini',
        '/opt/backups/ini/client.ini'
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            config.read(config_file)
            break
    
    return config


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Cerber - Backup Client Watchdog')
    parser.add_argument('--client', help='Client name')
    parser.add_argument('--config', help='Config file path')
    args = parser.parse_args()
    
    config = load_config()
    
    if args.client:
        if not config.has_section('client'):
            config.add_section('client')
        config.set('client', 'name', args.client)
    
    cerber = Cerber(config)
    
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        cerber.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        cerber.run()
    except KeyboardInterrupt:
        cerber.stop()
    except Exception as e:
        logger.error(f"Cerber error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
