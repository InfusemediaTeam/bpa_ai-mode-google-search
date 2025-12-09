# comments: English only
"""Chrome driver management and stealth configuration"""
import time
import random
import zipfile
import tempfile
import re
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

# Try to import selenium-wire for proxy authentication
try:
    from seleniumwire import webdriver as wire_webdriver
    SELENIUM_WIRE_AVAILABLE = True
except ImportError:
    SELENIUM_WIRE_AVAILABLE = False

from .config import (
    CHROME_BINARY,
    CHROMEDRIVER,
    USER_AGENTS,
    WINDOW_SIZES,
    USE_UC,
    PAGE_TIMEOUT,
    PROXY_URL,
)

try:
    import undetected_chromedriver as uc
except Exception:
    uc = None


def _create_proxy_auth_extension(proxy_host: str, proxy_port: str, proxy_user: str, proxy_pass: str) -> Path:
    """Create a Chrome extension for proxy authentication.
    
    Args:
        proxy_host: Proxy hostname
        proxy_port: Proxy port
        proxy_user: Proxy username
        proxy_pass: Proxy password
        
    Returns:
        Path to the created extension ZIP file
    """
    # Manifest V2 is required for blocking webRequest (V3 doesn't support it)
    manifest_json = """{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Proxy Auth",
    "permissions": [
        "webRequest",
        "webRequestBlocking",
        "<all_urls>"
    ],
    "background": {
        "scripts": ["background.js"]
    }
}"""
    
    background_js = f"""chrome.webRequest.onAuthRequired.addListener(
    function(details) {{
        return {{
            authCredentials: {{
                username: "{proxy_user}",
                password: "{proxy_pass}"
            }}
        }};
    }},
    {{urls: ["<all_urls>"]}},
    ["blocking"]
);"""
    
    # Create extension in temp directory
    plugin_file = Path(tempfile.gettempdir()) / f"proxy_auth_{proxy_host}_{proxy_port}.zip"
    
    with zipfile.ZipFile(plugin_file, 'w') as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)
    
    return plugin_file


def prepare_profile_dir(profile_path: Path) -> None:
    """Clean Chrome profile lock files.
    
    Args:
        profile_path: Path to Chrome profile directory
    """
    profile_path.mkdir(parents=True, exist_ok=True)
    
    # Known Chromium lock artifacts
    lock_names = ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile", "LOCK"]
    
    # Top-level known files
    for name in lock_names:
        f = profile_path / name
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass
    
    # Recursive: remove any 'LOCK' and 'Singleton*' files within subdirs
    try:
        for pattern in ("LOCK", "Singleton*"):
            for lf in profile_path.rglob(pattern):
                try:
                    if lf.is_file():
                        lf.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def apply_stealth_options(opts: Options) -> None:
    """Apply stealth and locale options to Chrome.
    
    Args:
        opts: Chrome options instance
    """
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-features=Translate,ChromeWhatsNewUI")
    
    # Container stability flags - minimal set that works
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    
    # Avoid keychain dialogs/prompts in containers
    opts.add_argument("--password-store=basic")
    opts.add_argument("--use-mock-keychain")


def apply_random_ua_and_size(opts: Options) -> None:
    """Apply random user agent and window size.
    
    Args:
        opts: Chrome options instance
    """
    ua = random.choice(USER_AGENTS)
    w, h = random.choice(WINDOW_SIZES)
    opts.add_argument(f"--user-agent={ua}")
    opts.add_argument(f"--window-size={w},{h}")
    opts.add_argument("--start-maximized")


def apply_cdp_stealth(driver: webdriver.Chrome) -> None:
    """Apply CDP-level stealth modifications.
    
    Args:
        driver: Chrome driver instance
    """
    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": random.choice(USER_AGENTS)})
    except Exception:
        pass
    
    try:
        driver.execute_script(
            """
            try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch (e) {}
            try { Object.defineProperty(navigator, 'language', { get: () => 'en-US' }); } catch (e) {}
            try { Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] }); } catch (e) {}
            try {
              const orig = navigator.plugins;
              Object.defineProperty(navigator, 'plugins', { get: () => orig || [1,2,3] });
            } catch (e) {}
            """
        )
    except Exception:
        pass


def create_driver(profile_path: Path, proxy_url: Optional[str] = None) -> webdriver.Chrome:
    """Create Chrome driver with stealth configuration.
    
    On profile lock error, retries by cleaning locks, then falls back to ephemeral session.
    
    Args:
        profile_path: Path to Chrome profile directory
        proxy_url: Proxy URL in format http://user:pass@host:port or http://host:port
        
    Returns:
        Chrome driver instance
        
    Raises:
        WebDriverException: If driver creation fails after retries
    """
    base_ud = profile_path
    prepare_profile_dir(base_ud)
    current_ud = base_ud
    
    # Parse proxy credentials if provided
    eff_proxy = proxy_url or PROXY_URL
    proxy_host = None
    proxy_port = None
    proxy_user = None
    proxy_pass = None
    proxy_host_port = None
    
    if eff_proxy:
        # Parse proxy URL: http://user:pass@host:port or http://host:port
        match = re.match(r'(?:https?://)?(?:([^:]+):([^@]+)@)?([^:]+):(\d+)', eff_proxy)
        if match:
            proxy_user, proxy_pass, proxy_host, proxy_port = match.groups()
            proxy_host_port = f"{proxy_host}:{proxy_port}"
            print(f"[DRIVER] Using proxy: {proxy_host_port}" + (f" (authenticated)" if proxy_user else ""))
        else:
            print(f"[DRIVER] Invalid proxy format: {eff_proxy}")
            eff_proxy = None
    
    last_err: Optional[Exception] = None
    for attempt in range(3):
        # Build fresh options on each attempt
        if USE_UC and uc is not None:
            options = uc.ChromeOptions()
        else:
            options = Options()
        
        options.add_argument(f"--user-data-dir={current_ud}")
        apply_stealth_options(options)
        apply_random_ua_and_size(options)
        
        # Determine if we'll use Selenium Wire for proxy auth
        use_selenium_wire = SELENIUM_WIRE_AVAILABLE and proxy_user and proxy_pass
        
        # Apply proxy configuration
        if eff_proxy and proxy_host_port:
            if not use_selenium_wire:
                # Use Chrome extension for proxy auth (fallback)
                if proxy_user and proxy_pass:
                    try:
                        plugin_path = _create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass)
                        options.add_extension(str(plugin_path))
                        print(f"[DRIVER] Proxy auth extension added: {plugin_path.name}")
                    except Exception as e:
                        print(f"[DRIVER] Failed to create proxy auth extension: {e}")
                
                # Set proxy server via Chrome argument (only if NOT using Selenium Wire)
                options.add_argument(f"--proxy-server=http://{proxy_host_port}")
        
        if CHROME_BINARY:
            if USE_UC and uc is not None:
                try:
                    options.browser_executable_path = CHROME_BINARY
                except Exception:
                    pass
            else:
                options.binary_location = CHROME_BINARY
        
        try:
            # Use Selenium Wire if proxy authentication is needed and available
            if use_selenium_wire:
                seleniumwire_options = {
                    'proxy': {
                        'http': f'http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}',
                        'https': f'http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}',
                        'no_proxy': 'localhost,127.0.0.1'
                    },
                    # Suppress BrokenPipeError and connection errors from mitmproxy
                    'suppress_connection_errors': True,
                }
                service = Service(executable_path=CHROMEDRIVER) if CHROMEDRIVER else Service()
                driver = wire_webdriver.Chrome(service=service, options=options, seleniumwire_options=seleniumwire_options)
                print(f"[DRIVER] Using Selenium Wire for proxy authentication")
            elif USE_UC and uc is not None:
                driver = uc.Chrome(options=options)
            else:
                service = Service(executable_path=CHROMEDRIVER) if CHROMEDRIVER else Service()
                driver = webdriver.Chrome(service=service, options=options)
            
            break
        except WebDriverException as e:
            last_err = e
            msg = str(e).lower()
            if "user data directory is already in use" in msg:
                if attempt == 0:
                    # Clean locks on base dir and retry
                    prepare_profile_dir(base_ud)
                    time.sleep(0.8)
                    current_ud = base_ud
                    continue
                elif attempt == 1:
                    # Fallback: use unique ephemeral session dir
                    ts = int(time.time() * 1000)
                    rnd = random.randint(1000, 9999)
                    ephemeral = base_ud / f"session_{ts}_{rnd}"
                    try:
                        ephemeral.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                    current_ud = ephemeral
                    print(f"[DRIVER] falling back to ephemeral user-data-dir: {current_ud}")
                    continue
            # Other errors or final attempt: re-raise
            raise
    else:
        if last_err:
            raise last_err
    
    try:
        driver.set_page_load_timeout(PAGE_TIMEOUT)
    except Exception:
        pass
    
    apply_cdp_stealth(driver)
    return driver
