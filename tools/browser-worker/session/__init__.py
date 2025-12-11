# comments: English only
"""Session management module exports"""
from .manager import SessionManager, kill_zombie_chrome_processes

__all__ = ["SessionManager", "kill_zombie_chrome_processes"]
