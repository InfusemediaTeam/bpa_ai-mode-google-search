# comments: English only
"""Browser session management"""
import threading
import time
import shutil
import os
from typing import Optional
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

from browser.config import (
    PROFILES,
    PAGE_TIMEOUT,
    SESSION_PER_SEARCH,
    AI_READY_TIMEOUT_SEC,
    AI_READY_TIMEOUT_PER_SEARCH_SEC,
    QUIT_TIMEOUT_SEC,
    PROXY_LIST,
    PROXY_URL,
    PROXY_BINDING_MODE,
    PROXY_BLOCK_TIMEOUT_SEC,
)
from browser.driver import create_driver
from browser.page_actions import ensure_aimode_ready

# Redis client for shared proxy index
try:
    import redis
    REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    REDIS_AVAILABLE = True
    print(f"[REDIS] Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    REDIS_AVAILABLE = False
    print(f"[REDIS] Not available: {e}")

# Proxy health check timeout
PROXY_CHECK_TIMEOUT = int(os.environ.get("PROXY_CHECK_TIMEOUT_SEC", "5"))

# Coordinator URL for proxy block notifications
COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "http://proxy-coordinator:4200")


def check_proxy_connectivity(proxy_url: str, timeout: int = PROXY_CHECK_TIMEOUT) -> bool:
    """Check if proxy is reachable by making a test connection.
    
    Args:
        proxy_url: Proxy URL (with or without http:// prefix)
        timeout: Connection timeout in seconds
        
    Returns:
        True if proxy is reachable, False otherwise
    """
    try:
        import httpx
        
        # Normalize proxy URL
        if not proxy_url.startswith("http"):
            proxy_url = f"http://{proxy_url}"
        
        # Try to connect through proxy to a reliable endpoint
        with httpx.Client(proxy=proxy_url, timeout=timeout) as client:
            response = client.get("https://www.google.com/generate_204")
            # Google returns 204 No Content for this endpoint
            return response.status_code in [200, 204]
    except Exception as e:
        print(f"[PROXY_CHECK] Proxy {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url} failed: {e}")
        return False


def notify_proxy_blocked(proxy_idx: int, reason: str) -> None:
    """Notify proxy coordinator that a proxy should be blocked.
    
    Args:
        proxy_idx: Index of the proxy to block
        reason: Reason for blocking
    """
    if proxy_idx < 0:
        return
    
    try:
        import httpx
        with httpx.Client(timeout=5) as client:
            response = client.post(
                f"{COORDINATOR_URL}/block-proxy",
                json={"proxy_idx": proxy_idx, "reason": reason}
            )
            if response.status_code == 200:
                print(f"[PROXY_BLOCK] Notified coordinator: proxy {proxy_idx} blocked ({reason})")
            else:
                print(f"[PROXY_BLOCK] Coordinator returned {response.status_code}")
    except Exception as e:
        print(f"[PROXY_BLOCK] Failed to notify coordinator: {e}")


def is_driver_valid(driver: webdriver.Chrome) -> bool:
    """Check if driver session is still valid AND browser process is alive.
    
    Args:
        driver: Chrome driver instance to check
        
    Returns:
        True if driver is valid and can be used, False otherwise
    """
    if not driver:
        return False
    
    try:
        # Check 1: Driver session must respond
        _ = driver.current_url
        
        # Check 2: Browser process must be alive (not zombie)
        # This catches cases where chromedriver is alive but chromium crashed
        import psutil
        chrome_alive = False
        for proc in psutil.process_iter(['name', 'status']):
            try:
                name = proc.info['name'].lower()
                status = proc.info.get('status', '')
                # Check for actual chromium browser process (not chromedriver)
                is_browser = ('chromium' in name or 'chrome' in name) and 'driver' not in name
                if is_browser:
                    # Skip zombie/defunct processes
                    if status in ['zombie', 'dead'] or status == psutil.STATUS_ZOMBIE:
                        continue
                    chrome_alive = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        if not chrome_alive:
            print("[SESSION] Browser process is dead or zombie - driver invalid")
            return False
        
        return True
    except Exception as e:
        print(f"[SESSION] Driver validation failed: {e}")
        return False


def kill_zombie_chrome_processes() -> int:
    """Kill zombie/defunct Chrome processes and their parent chromedrivers.
    
    Zombie processes occur when chromium crashes but chromedriver doesn't reap it.
    We need to kill the parent chromedriver to clean up properly.
    
    Returns:
        Number of processes killed
    """
    import psutil
    import os
    import signal
    
    killed = 0
    zombie_pids = []
    chromedriver_pids_to_kill = set()
    
    # First pass: find zombie chrome processes and their parents
    for proc in psutil.process_iter(['pid', 'ppid', 'name', 'status']):
        try:
            name = proc.info['name'].lower()
            status = proc.info.get('status', '')
            is_browser = ('chromium' in name or 'chrome' in name) and 'driver' not in name
            
            if is_browser and (status in ['zombie', 'dead'] or status == psutil.STATUS_ZOMBIE):
                zombie_pids.append(proc.info['pid'])
                # Mark parent chromedriver for killing
                ppid = proc.info.get('ppid')
                if ppid and ppid > 1:
                    chromedriver_pids_to_kill.add(ppid)
                    
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if not zombie_pids:
        return 0
    
    print(f"[ZOMBIE_CLEANUP] Found {len(zombie_pids)} zombie Chrome processes: {zombie_pids}")
    print(f"[ZOMBIE_CLEANUP] Parent chromedrivers to kill: {list(chromedriver_pids_to_kill)}")
    
    # Kill parent chromedrivers first (this will also reap zombies)
    for pid in chromedriver_pids_to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
            print(f"[ZOMBIE_CLEANUP] Killed chromedriver PID {pid}")
        except (ProcessLookupError, PermissionError) as e:
            print(f"[ZOMBIE_CLEANUP] Failed to kill PID {pid}: {e}")
    
    # Wait a moment for zombies to be reaped by tini
    import time
    time.sleep(0.5)
    
    return killed


def safe_quit_driver(driver: webdriver.Chrome, timeout: int = QUIT_TIMEOUT_SEC) -> bool:
    """Quit driver with timeout protection.
    
    Args:
        driver: Chrome driver instance to quit
        timeout: Maximum time to wait for quit in seconds
        
    Returns:
        True if quit succeeded, False if timed out
    """
    if not driver:
        return True
    
    def quit_with_timeout():
        try:
            driver.quit()
        except Exception as e:
            print(f"[QUIT] driver.quit() failed: {e}")
    
    quit_thread = threading.Thread(target=quit_with_timeout, daemon=True)
    quit_thread.start()
    quit_thread.join(timeout=timeout)
    
    if quit_thread.is_alive():
        print(f"[QUIT] driver.quit() timed out after {timeout}s - killing zombie processes")
        # Kill any zombie chrome processes and their parents
        kill_zombie_chrome_processes()
        return False
    
    # Even on successful quit, check for zombies (chromedriver may not reap properly)
    kill_zombie_chrome_processes()
    return True


def clean_profile_cache(profile_path: str) -> None:
    """Clean Chrome cache directories to prevent disk bloat.
    
    Args:
        profile_path: Path to Chrome profile directory
    """
    profile = Path(profile_path)
    if not profile.exists():
        return
    
    cache_dirs = [
        profile / "Default" / "Cache",
        profile / "Default" / "Code Cache",
        profile / "Default" / "GPUCache",
        profile / "Default" / "Service Worker" / "CacheStorage",
        profile / "ShaderCache",
        profile / "Default" / "DawnCache",
    ]
    
    total_freed = 0
    for cache_dir in cache_dirs:
        if cache_dir.exists():
            try:
                size_before = sum(f.stat().st_size for f in cache_dir.rglob('*') if f.is_file())
                shutil.rmtree(cache_dir, ignore_errors=True)
                total_freed += size_before
            except Exception as e:
                print(f"[CACHE_CLEAN] Failed to clean {cache_dir.name}: {e}")
    
    if total_freed > 0:
        print(f"[CACHE_CLEAN] Freed {total_freed / (1024*1024):.1f} MB from {profile.name}")


def clean_old_session_dirs(profile_path: str, keep_recent: int = 2) -> None:
    """Clean old ephemeral session directories to prevent disk bloat.
    
    Ephemeral session dirs are created as fallback when profile is locked.
    They accumulate over time (~135MB each) and need periodic cleanup.
    
    Args:
        profile_path: Path to Chrome profile directory
        keep_recent: Number of most recent session dirs to keep
    """
    profile = Path(profile_path)
    if not profile.exists():
        return
    
    try:
        # Find all session_* directories
        session_dirs = [d for d in profile.iterdir() if d.is_dir() and d.name.startswith("session_")]
        
        if len(session_dirs) <= keep_recent:
            return
        
        # Sort by modification time (oldest first)
        session_dirs.sort(key=lambda d: d.stat().st_mtime)
        
        # Remove old sessions, keep only recent ones
        dirs_to_remove = session_dirs[:-keep_recent] if keep_recent > 0 else session_dirs
        
        total_freed = 0
        for session_dir in dirs_to_remove:
            try:
                # Calculate size before removal
                size = sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())
                shutil.rmtree(session_dir, ignore_errors=True)
                total_freed += size
                print(f"[SESSION_CLEAN] Removed old session: {session_dir.name}")
            except Exception as e:
                print(f"[SESSION_CLEAN] Failed to remove {session_dir.name}: {e}")
        
        if total_freed > 0:
            print(f"[SESSION_CLEAN] Freed {total_freed / (1024*1024):.1f} MB from {len(dirs_to_remove)} old sessions")
    
    except Exception as e:
        print(f"[SESSION_CLEAN] Failed to clean sessions: {e}")


class SessionManager:
    """Manages browser session lifecycle and profile rotation."""
    
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        self.profile_idx: int = -1
        self.proxy_idx: int = -1  # Local proxy index (fallback if Redis unavailable)
        self.lock = threading.Lock()
        self.search_count: int = 0  # Track searches to prevent memory leaks
        self.max_searches_per_session: int = 50  # Rotate after 50 searches
        self.redis_proxy_key = "browser_worker:shared_proxy_idx"  # Redis key for shared proxy index
        self.driver_proxy_idx: int = -1  # Proxy index that was used to create current driver
        # NOTE: request_count and proxy_rotation_enabled removed - managed by Proxy Coordinator
    
    def get_driver(self) -> tuple[webdriver.Chrome, WebDriverWait]:
        """Get current driver instance, creating if needed.
        
        Returns:
            Tuple of (driver, wait)
            
        Raises:
            RuntimeError: If driver initialization fails or session is invalid
        """
        if not self.driver or not self.wait:
            raise RuntimeError("Driver not initialized")
        
        # Check if driver session is still valid
        if not is_driver_valid(self.driver):
            print("[SESSION] Driver session invalid - forcing rotation")
            # Clear invalid driver
            self.driver = None
            self.wait = None
            raise RuntimeError("Driver session invalid (closed or crashed)")
        
        return self.driver, self.wait
    
    def rotate_identity(self, reason: str = "", _recursion_depth: int = 0) -> None:
        """Rotate to next profile and create fresh browser session.
        
        Args:
            reason: Reason for rotation (for logging)
            _recursion_depth: Internal counter to prevent infinite recursion
        """
        # Prevent infinite recursion - max depth = number of profiles
        if _recursion_depth >= len(PROFILES):
            print(f"\n{'='*80}")
            print(f"[IDENTITY] CRITICAL ERROR: All {len(PROFILES)} profiles failed to initialize")
            print(f"[IDENTITY] This may cause container restart if not handled")
            print(f"{'='*80}\n")
            raise RuntimeError("All browser profiles failed to initialize")
        
        with self.lock:
            # Close existing driver with timeout protection
            if self.driver:
                safe_quit_driver(self.driver, timeout=5)
            self.driver = None
            self.wait = None
            
            # Reset search counter on rotation
            self.search_count = 0
            
            # Rotate to next profile
            self.profile_idx = (self.profile_idx + 1) % len(PROFILES)
            profile = PROFILES[self.profile_idx]
            
            # Clean cache and old sessions from current profile after rotation to prevent disk bloat
            # This ensures we clean the profile we're about to use
            clean_profile_cache(str(profile))
            clean_old_session_dirs(str(profile), keep_recent=2)
            print(f"\n[IDENTITY] rotating -> profile={profile} reason={reason} (depth={_recursion_depth})")
            
            # Determine timeout based on session mode (centralized via config)
            ready_timeout = (
                AI_READY_TIMEOUT_PER_SEARCH_SEC if SESSION_PER_SEARCH else AI_READY_TIMEOUT_SEC
            )
            
            # Select proxy for this session
            proxy_url = self._select_proxy()
            
            # Try to create driver and ensure AI Mode ready
            for attempt in range(2):
                try:
                    temp_driver = create_driver(profile, proxy_url=proxy_url)
                    temp_wait = WebDriverWait(temp_driver, PAGE_TIMEOUT)
                    # Temporarily assign to self so ensure_aimode_ready can access it
                    self.driver = temp_driver
                    self.wait = temp_wait
                    if ensure_aimode_ready(self, timeout=ready_timeout):
                        # Success - driver already assigned
                        print("[IDENTITY] ready ✓")
                        return
                    else:
                        print("[IDENTITY] AI Mode not ready; retrying…")
                except Exception as e:
                    error_msg = str(e)
                    print(f"[IDENTITY] launch failed: {e}")
                    
                    # If Chrome crashed, clean the entire profile to fix corruption
                    if "Chrome instance exited" in error_msg or "session not created" in error_msg:
                        print(f"[IDENTITY] Chrome crashed - cleaning corrupted profile: {profile}")
                        import shutil
                        try:
                            if profile.exists():
                                shutil.rmtree(profile, ignore_errors=True)
                            # Create fresh empty profile directory
                            profile.mkdir(parents=True, exist_ok=True)
                            print(f"[IDENTITY] Profile cleaned and recreated: {profile}")
                        except Exception as clean_err:
                            print(f"[IDENTITY] Failed to clean profile: {clean_err}")
                            
                import time
                time.sleep(0.5 + attempt * 0.5)
            
            print("[IDENTITY] moving on to next profile…")
            # Tail recursion is protected by the same lock; depth is bounded by number of profiles
            self.rotate_identity("previous profile not ready", _recursion_depth + 1)
    
    def ensure_ready(self) -> None:
        """Ensure driver is initialized and ready."""
        if not self.driver or not self.wait:
            self.rotate_identity("no driver")
            if not self.driver:
                raise RuntimeError("Driver not initialized")
    
    def _get_shared_proxy_idx(self) -> int:
        """Get shared proxy index from Redis (synchronized across all workers).
        
        Returns:
            Current shared proxy index, or local fallback if Redis unavailable
        """
        if not REDIS_AVAILABLE or not redis_client:
            # Fallback to local index
            if self.proxy_idx < 0:
                self.proxy_idx = 0
            return self.proxy_idx
        
        try:
            # Get current shared index from Redis
            idx_str = redis_client.get(self.redis_proxy_key)
            if idx_str is None:
                # Initialize if not exists
                redis_client.set(self.redis_proxy_key, "0")
                return 0
            return int(idx_str)
        except Exception as e:
            print(f"[REDIS] Failed to get shared proxy index: {e}, using local fallback")
            if self.proxy_idx < 0:
                self.proxy_idx = 0
            return self.proxy_idx
    
    def _increment_shared_proxy_idx(self) -> int:
        """Increment shared proxy index in Redis (synchronized across all workers).
        
        Returns:
            New proxy index after increment
        """
        if not REDIS_AVAILABLE or not redis_client:
            # Fallback to local increment
            self.proxy_idx = (self.proxy_idx + 1) % len(PROXY_LIST) if PROXY_LIST else 0
            return self.proxy_idx
        
        try:
            # Atomic increment in Redis
            new_idx = redis_client.incr(self.redis_proxy_key)
            print(f"[REDIS] Incremented shared proxy index to {new_idx}")
            return new_idx
        except Exception as e:
            print(f"[REDIS] Failed to increment shared proxy index: {e}, using local fallback")
            self.proxy_idx = (self.proxy_idx + 1) % len(PROXY_LIST) if PROXY_LIST else 0
            return self.proxy_idx
    
    def _mark_proxy_blocked(self, proxy_idx: int) -> None:
        """Mark proxy as blocked in Redis with TTL.
        
        Args:
            proxy_idx: Index of proxy to block
        """
        if not REDIS_AVAILABLE or not redis_client or not PROXY_LIST:
            return
        
        try:
            key = f"browser_worker:proxy_blocked:{proxy_idx}"
            # Set with TTL (expires after PROXY_BLOCK_TIMEOUT_SEC)
            redis_client.setex(key, PROXY_BLOCK_TIMEOUT_SEC, "1")
            print(f"[PROXY_BLOCK] Marked proxy {proxy_idx} as blocked for {PROXY_BLOCK_TIMEOUT_SEC}s")
        except Exception as e:
            print(f"[PROXY_BLOCK] Failed to mark proxy as blocked: {e}")
    
    def _is_proxy_blocked(self, proxy_idx: int) -> bool:
        """Check if proxy is currently blocked.
        
        Args:
            proxy_idx: Index of proxy to check
            
        Returns:
            True if proxy is blocked, False otherwise
        """
        if not REDIS_AVAILABLE or not redis_client or not PROXY_LIST:
            return False
        
        try:
            key = f"browser_worker:proxy_blocked:{proxy_idx}"
            blocked = redis_client.exists(key)
            if blocked:
                ttl = redis_client.ttl(key)
                print(f"[PROXY_BLOCK] Proxy {proxy_idx} is blocked (TTL: {ttl}s)")
            return bool(blocked)
        except Exception as e:
            print(f"[PROXY_BLOCK] Failed to check if proxy blocked: {e}")
            return False
    
    def _get_next_available_proxy_idx(self, start_idx: int, allow_none: bool = False) -> Optional[int]:
        """Get next available (non-blocked) proxy index.
        
        Args:
            start_idx: Starting index to search from
            allow_none: If True, return None when all proxies blocked; if False, return start_idx anyway
            
        Returns:
            Next available proxy index, None if all blocked and allow_none=True, or start_idx if all blocked and allow_none=False
        """
        if not PROXY_LIST:
            return 0
        
        # Try all proxies starting from start_idx
        for offset in range(len(PROXY_LIST)):
            idx = (start_idx + offset) % len(PROXY_LIST)
            if not self._is_proxy_blocked(idx):
                if offset > 0:
                    print(f"[PROXY_BLOCK] Skipped {offset} blocked proxies, using proxy {idx}")
                return idx
        
        # All proxies are blocked
        if allow_none:
            print(f"[PROXY_BLOCK] ERROR: All {len(PROXY_LIST)} proxies are blocked!")
            return None
        else:
            print(f"[PROXY_BLOCK] WARNING: All {len(PROXY_LIST)} proxies are blocked! Using proxy {start_idx} anyway")
            return start_idx
    
    def has_available_proxy(self) -> bool:
        """Check if there is at least one available (non-blocked) proxy.
        
        Returns:
            True if at least one proxy is available, False if all are blocked
        """
        if not PROXY_LIST:
            return True  # No proxy list means no proxy requirement
        
        # Check all proxies
        for idx in range(len(PROXY_LIST)):
            if not self._is_proxy_blocked(idx):
                return True
        
        return False
    
    def _select_proxy(self) -> Optional[str]:
        """Select proxy based on PROXY_BINDING_MODE and shared/local indices.
        
        Skips blocked proxies automatically.
        Checks proxy connectivity before returning and blocks unreachable proxies.
        """
        if not PROXY_LIST and not PROXY_URL:
            return None
        
        if PROXY_LIST:
            # Try each proxy until we find a working one
            tried_proxies = set()
            
            while len(tried_proxies) < len(PROXY_LIST):
                if PROXY_BINDING_MODE == "by_profile":
                    # Bind proxy to profile
                    if self.profile_idx >= 0:
                        base_idx = self.profile_idx % len(PROXY_LIST)
                    else:
                        base_idx = 0
                    # Find next available (non-blocked) proxy
                    idx = self._get_next_available_proxy_idx(base_idx)
                    # For by_profile mode, driver_proxy_idx is not used (no shared rotation)
                    self.driver_proxy_idx = -1
                else:  # independent - use shared index from Redis
                    shared_idx = self._get_shared_proxy_idx()
                    base_idx = shared_idx % len(PROXY_LIST)
                    # Find next available (non-blocked) proxy
                    idx = self._get_next_available_proxy_idx(base_idx)
                    # Remember which proxy index was used for current driver
                    self.driver_proxy_idx = shared_idx
                
                if idx is None:
                    print(f"[PROXY] No available proxies!")
                    return None
                
                # Skip if we already tried this proxy
                if idx in tried_proxies:
                    break
                tried_proxies.add(idx)
                
                proxy = PROXY_LIST[idx]
                proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                
                if PROXY_BINDING_MODE == "independent":
                    print(f"[PROXY] Testing proxy {idx}/{len(PROXY_LIST)} (shared_idx={self.driver_proxy_idx}): {proxy_display}")
                else:
                    print(f"[PROXY] Testing proxy {idx}/{len(PROXY_LIST)} (by_profile): {proxy_display}")
                
                # Check proxy connectivity before using
                if check_proxy_connectivity(proxy):
                    print(f"[PROXY] ✓ Proxy {proxy_display} is reachable")
                    return proxy
                else:
                    print(f"[PROXY] ✗ Proxy {proxy_display} is NOT reachable - blocking and notifying coordinator")
                    # Block this proxy and notify coordinator
                    self._mark_proxy_blocked(idx)
                    notify_proxy_blocked(idx, "connectivity_check_failed")
            
            # All proxies failed
            print(f"[PROXY] ERROR: All {len(PROXY_LIST)} proxies failed connectivity check!")
            return None
        else:
            return PROXY_URL
    
    def rotate_profile_only(self, reason: str = "") -> None:
        """Rotate to next profile without changing proxy."""
        with self.lock:
            if self.driver:
                safe_quit_driver(self.driver, timeout=5)
            self.driver = None
            self.wait = None
            self.search_count = 0
            
            # Rotate profile
            self.profile_idx = (self.profile_idx + 1) % len(PROFILES)
            profile = PROFILES[self.profile_idx]
            clean_profile_cache(str(profile))
            clean_old_session_dirs(str(profile), keep_recent=2)
            print(f"\n[IDENTITY] rotating PROFILE only -> profile={profile.name} reason={reason}")
            
            # Keep same proxy - _select_proxy() will update driver_proxy_idx if shared index changed
            # This is correct: if another worker rotated proxy, we should use the new proxy
            proxy_url = self._select_proxy()
            
            ready_timeout = (
                AI_READY_TIMEOUT_PER_SEARCH_SEC if SESSION_PER_SEARCH else AI_READY_TIMEOUT_SEC
            )
            
            for attempt in range(2):
                try:
                    temp_driver = create_driver(profile, proxy_url=proxy_url)
                    temp_wait = WebDriverWait(temp_driver, PAGE_TIMEOUT)
                    self.driver = temp_driver
                    self.wait = temp_wait
                    if ensure_aimode_ready(self, timeout=ready_timeout):
                        print("[IDENTITY] ready ✓")
                        return
                    else:
                        print("[IDENTITY] AI Mode not ready; retrying…")
                except Exception as e:
                    error_msg = str(e)
                    print(f"[IDENTITY] launch failed: {e}")
                    
                    # If Chrome crashed, clean the entire profile to fix corruption
                    if "Chrome instance exited" in error_msg or "session not created" in error_msg:
                        print(f"[IDENTITY] Chrome crashed - cleaning corrupted profile: {profile}")
                        import shutil
                        try:
                            if profile.exists():
                                shutil.rmtree(profile, ignore_errors=True)
                            profile.mkdir(parents=True, exist_ok=True)
                            print(f"[IDENTITY] Profile cleaned and recreated: {profile}")
                        except Exception as clean_err:
                            print(f"[IDENTITY] Failed to clean profile: {clean_err}")
                            
                import time
                time.sleep(0.5 + attempt * 0.5)
            
            raise RuntimeError("Failed to initialize after profile rotation")
    
    def rotate_proxy_only(self, reason: str = "", mark_as_blocked: bool = False) -> None:
        """Rotate to next proxy without changing profile.
        
        Uses shared proxy index in Redis to synchronize rotation across all workers.
        Prevents cascade rotation when multiple workers detect same proxy block.
        
        Args:
            reason: Reason for rotation (for logging)
            mark_as_blocked: Whether to mark old proxy as blocked in Redis (default: False)
        """
        with self.lock:
            if self.driver:
                safe_quit_driver(self.driver, timeout=5)
            self.driver = None
            self.wait = None
            self.search_count = 0
            
            # Keep same profile
            if self.profile_idx < 0:
                self.profile_idx = 0
            profile = PROFILES[self.profile_idx]
            
            # Rotate proxy (synchronized across all workers via Redis)
            if PROXY_LIST:
                # Mark old proxy as blocked only if explicitly requested
                if mark_as_blocked and self.driver_proxy_idx >= 0:
                    old_proxy_idx = self.driver_proxy_idx % len(PROXY_LIST)
                    self._mark_proxy_blocked(old_proxy_idx)
                
                # Check if shared index already changed (another worker rotated)
                current_shared_idx = self._get_shared_proxy_idx()
                
                if current_shared_idx != self.driver_proxy_idx:
                    # Another worker already rotated proxy
                    print(f"\n[IDENTITY] Proxy already rotated by another worker: {self.driver_proxy_idx} -> {current_shared_idx}")
                    print(f"[IDENTITY] Using new proxy without incrementing (reason={reason})")
                    new_shared_idx = current_shared_idx
                else:
                    # We are first to detect block - increment shared index
                    new_shared_idx = self._increment_shared_proxy_idx()
                    print(f"\n[IDENTITY] rotating PROXY only -> shared_idx={new_shared_idx} proxy={new_shared_idx % len(PROXY_LIST)}/{len(PROXY_LIST)} reason={reason}")
                
                # Get next available (non-blocked) proxy
                base_idx = new_shared_idx % len(PROXY_LIST)
                idx = self._get_next_available_proxy_idx(base_idx)
                proxy_url = PROXY_LIST[idx]
                print(f"[PROXY] Using proxy {idx}/{len(PROXY_LIST)}: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")
            elif PROXY_URL:
                print(f"\n[IDENTITY] rotating PROXY only (single proxy) -> reason={reason}")
                proxy_url = PROXY_URL
                new_shared_idx = None  # Not applicable for single proxy
            else:
                raise RuntimeError("No proxies configured for rotation")
            
            ready_timeout = (
                AI_READY_TIMEOUT_PER_SEARCH_SEC if SESSION_PER_SEARCH else AI_READY_TIMEOUT_SEC
            )
            
            for attempt in range(2):
                try:
                    temp_driver = create_driver(profile, proxy_url=proxy_url)
                    temp_wait = WebDriverWait(temp_driver, PAGE_TIMEOUT)
                    self.driver = temp_driver
                    self.wait = temp_wait
                    if ensure_aimode_ready(self, timeout=ready_timeout):
                        # Success - remember which shared_idx was used for this driver
                        if PROXY_LIST and new_shared_idx is not None:
                            self.driver_proxy_idx = new_shared_idx
                        print("[IDENTITY] ready ✓")
                        return
                    else:
                        print("[IDENTITY] AI Mode not ready; retrying…")
                except Exception as e:
                    error_msg = str(e)
                    print(f"[IDENTITY] launch failed: {e}")
                    
                    # If Chrome crashed, clean the entire profile to fix corruption
                    if "Chrome instance exited" in error_msg or "session not created" in error_msg:
                        print(f"[IDENTITY] Chrome crashed - cleaning corrupted profile: {profile}")
                        import shutil
                        try:
                            if profile.exists():
                                shutil.rmtree(profile, ignore_errors=True)
                            profile.mkdir(parents=True, exist_ok=True)
                            print(f"[IDENTITY] Profile cleaned and recreated: {profile}")
                        except Exception as clean_err:
                            print(f"[IDENTITY] Failed to clean profile: {clean_err}")
                            
                import time
                time.sleep(0.5 + attempt * 0.5)
            
            raise RuntimeError("Failed to initialize after proxy rotation")
    
    def maybe_rotate_for_search(self) -> None:
        """Rotate identity if SESSION_PER_SEARCH is enabled."""
        if SESSION_PER_SEARCH:
            self.rotate_identity("per search")
        else:
            self.ensure_ready()
    
    # NOTE: Request counting is now managed by Proxy Coordinator
    # The following methods are no longer used and kept only for reference:
    # - increment_request_count() - replaced by coordinator's /increment-request
    # - _get_shared_request_count() - coordinator manages counter
    # - _increment_shared_request_count() - coordinator manages counter
    # - _reset_shared_request_count() - coordinator manages counter
