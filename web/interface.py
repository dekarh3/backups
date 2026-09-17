#!/usr/bin/env python3
"""
Web Interface - Admin web interface for backup system.
FastAPI-based web interface with Jinja2 templates for server-side rendering.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import configparser
import httpx

from fastapi import FastAPI, Request, HTTPException, Depends, Form, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('interface')

app = FastAPI(title="Backup System Web Interface", version="1.0.0")
security = HTTPBearer()

# Configuration
config = None
api_url = "https://localhost:9443"
templates = Jinja2Templates(directory="/opt/backups/web/templates")

# Session storage (use Redis or database in production)
sessions = {}


class Config:
    def __init__(self, config_file: str = '/opt/backups/ini/backups.ini'):
        self.config = configparser.ConfigParser()
        if os.path.exists(config_file):
            self.config.read(config_file)
    
    def get(self, section: str, option: str, fallback=None):
        try:
            return self.config.get(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback


def load_config():
    """Load configuration"""
    global config, api_url
    config = Config()
    api_url = config.get('global', 'api_url', fallback='https://localhost:9443')
    logger.info("Web interface configuration loaded")


async def get_current_user(request: Request):
    """Get current user from session"""
    session_id = request.cookies.get('session_id')
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return sessions[session_id]


async def get_current_user_optional(request: Request):
    """Get current user from session (optional)"""
    session_id = request.cookies.get('session_id')
    if session_id and session_id in sessions:
        return sessions[session_id]
    return None


@app.on_event("startup")
async def startup_event():
    """Startup tasks"""
    load_config()
    # Ensure templates directory exists
    template_dir = Path("/opt/backups/web/templates")
    template_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Web interface started")


@app.get("/")
async def root(request: Request, user: dict = Depends(get_current_user_optional)):
    """Root page - redirect to dashboard or login"""
    if user:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "title": "Login - Backup System"
    })


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    totp_code: str = Form(None)
):
    """Handle login submission"""
    # Validate credentials against API
    # For now, simple demo authentication
    if username and password:
        session_id = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}_{username}"
        sessions[session_id] = {
            "username": username,
            "role": "admin",
            "logged_in_at": datetime.now()
        }
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=3600)
        return response
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "title": "Login - Backup System",
        "error": "Invalid credentials"
    })


@app.get("/logout")
async def logout(request: Request):
    """Handle logout"""
    session_id = request.cookies.get('session_id')
    if session_id and session_id in sessions:
        del sessions[session_id]
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_id")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    """Main dashboard"""
    # Fetch data from API
    clients = []
    alerts = []
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "Dashboard - Backup System",
        "user": user,
        "clients": clients,
        "alerts": alerts,
        "current_time": datetime.now()
    })


@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, user: dict = Depends(get_current_user)):
    """Clients list page"""
    return templates.TemplateResponse("clients.html", {
        "request": request,
        "title": "Clients - Backup System",
        "user": user
    })


@app.get("/clients/{client_name}", response_class=HTMLResponse)
async def client_detail(request: Request, client_name: str, user: dict = Depends(get_current_user)):
    """Client detail page"""
    return templates.TemplateResponse("client_detail.html", {
        "request": request,
        "title": f"Client {client_name} - Backup System",
        "user": user,
        "client_name": client_name
    })


@app.post("/clients/{client_name}/restart")
async def restart_client(
    request: Request,
    client_name: str,
    user: dict = Depends(get_current_user)
):
    """Restart client stack"""
    # Call API to restart client
    logger.info(f"Restarting client stack: {client_name}")
    return RedirectResponse(url=f"/clients/{client_name}", status_code=303)


@app.get("/backups", response_class=HTMLResponse)
async def backups_page(request: Request, user: dict = Depends(get_current_user)):
    """Backups list page"""
    return templates.TemplateResponse("backups.html", {
        "request": request,
        "title": "Backups - Backup System",
        "user": user
    })


@app.get("/backups/{client}/{backup_name}", response_class=HTMLResponse)
async def backup_detail(request: Request, client: str, backup_name: str, user: dict = Depends(get_current_user)):
    """Backup detail page"""
    return templates.TemplateResponse("backup_detail.html", {
        "request": request,
        "title": f"Backup {backup_name} - Backup System",
        "user": user,
        "client": client,
        "backup_name": backup_name
    })


@app.post("/backups/{client}/{backup_name}/start")
async def start_backup(
    request: Request,
    client: str,
    backup_name: str,
    user: dict = Depends(get_current_user)
):
    """Start backup"""
    logger.info(f"Starting backup: {client}/{backup_name}")
    return RedirectResponse(url=f"/backups/{client}/{backup_name}", status_code=303)


@app.post("/backups/{client}/{backup_name}/stop")
async def stop_backup(
    request: Request,
    client: str,
    backup_name: str,
    user: dict = Depends(get_current_user)
):
    """Stop backup"""
    logger.info(f"Stopping backup: {client}/{backup_name}")
    return RedirectResponse(url=f"/backups/{client}/{backup_name}", status_code=303)


@app.post("/backups/{client}/{backup_name}/abort_cleanup")
async def abort_cleanup(
    request: Request,
    client: str,
    backup_name: str,
    user: dict = Depends(get_current_user)
):
    """Abort and cleanup backup"""
    logger.info(f"Aborting cleanup: {client}/{backup_name}")
    return RedirectResponse(url=f"/backups/{client}/{backup_name}", status_code=303)


@app.post("/backups/{client}/{backup_name}/prune")
async def prune_backup(
    request: Request,
    client: str,
    backup_name: str,
    user: dict = Depends(get_current_user)
):
    """Run prune on backup"""
    logger.info(f"Running prune: {client}/{backup_name}")
    return RedirectResponse(url=f"/backups/{client}/{backup_name}", status_code=303)


@app.get("/snapshots", response_class=HTMLResponse)
async def snapshots_page(request: Request, user: dict = Depends(get_current_user)):
    """Snapshots list page"""
    return templates.TemplateResponse("snapshots.html", {
        "request": request,
        "title": "Snapshots - Backup System",
        "user": user
    })


@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, user: dict = Depends(get_current_user)):
    """Alerts page"""
    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "title": "Alerts - Backup System",
        "user": user
    })


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, user: dict = Depends(get_current_user)):
    """Logs page"""
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "title": "Logs - Backup System",
        "user": user
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: dict = Depends(get_current_user)):
    """Settings page"""
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "title": "Settings - Backup System",
        "user": user
    })


@app.post("/secrets/rotate/{client}")
async def rotate_secrets(
    request: Request,
    client: str,
    user: dict = Depends(get_current_user)
):
    """Rotate client secrets"""
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    logger.info(f"Rotating secrets for client: {client}")
    return RedirectResponse(url="/settings", status_code=303)


def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='Backup System Web Interface')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind')
    parser.add_argument('--port', type=int, default=9443, help='Port to bind')
    parser.add_argument('--ssl-cert', help='SSL certificate file')
    parser.add_argument('--ssl-key', help='SSL key file')
    parser.add_argument('--api-url', help='API server URL')
    
    args = parser.parse_args()
    
    if args.api_url:
        global api_url
        api_url = args.api_url
    
    ssl_config = {}
    if args.ssl_cert and args.ssl_key:
        ssl_config['ssl_certfile'] = args.ssl_cert
        ssl_config['ssl_keyfile'] = args.ssl_key
    
    uvicorn.run(app, host=args.host, port=args.port, **ssl_config)


if __name__ == '__main__':
    main()
