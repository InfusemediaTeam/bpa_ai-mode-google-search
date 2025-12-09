# comments: English only
"""Browser configuration and constants"""
import os
from pathlib import Path

# Timeouts (seconds) - centralized via environment variables
PAGE_TIMEOUT = int(os.environ.get("PY_PAGE_TIMEOUT_SEC", "45"))
ANSWER_TIMEOUT = int(os.environ.get("PY_ANSWER_TIMEOUT_SEC", "20"))
AI_READY_TIMEOUT_SEC = int(os.environ.get("PY_AI_READY_TIMEOUT_SEC", "25"))
AI_READY_TIMEOUT_PER_SEARCH_SEC = int(os.environ.get("PY_AI_READY_TIMEOUT_PER_SEARCH_SEC", "8"))
SEARCH_PAGE_OPEN_TIMEOUT_SEC = int(os.environ.get("PY_SEARCH_PAGE_OPEN_TIMEOUT_SEC", "12"))
NEW_SEARCH_BUTTON_WAIT_SEC = int(os.environ.get("PY_NEW_SEARCH_BUTTON_WAIT_SEC", "3"))
QUIT_TIMEOUT_SEC = int(os.environ.get("PY_QUIT_TIMEOUT_SEC", "5"))

# Chrome profiles
_profiles_env = os.environ.get("PY_WORKER_PROFILES")
if _profiles_env:
    PROFILES = [Path(p.strip()) for p in _profiles_env.split(",") if p.strip()]
else:
    PROFILES = [Path.home() / ".ai_mode_chrome_c", Path.home() / ".ai_mode_chrome_d"]

# Chrome binary paths
CHROME_BINARY = os.environ.get("CHROME_BINARY")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER")

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
]

# Window sizes for rotation
WINDOW_SIZES = [(1366, 768), (1440, 900), (1536, 864), (1600, 900), (1920, 1080)]

# Google AI Mode URL
GOOGLE_HOME = "https://www.google.com/?udm=50&hl=en&gl=US"

# Feature flags
USE_UC = os.environ.get("USE_UC", "0") == "1"
SESSION_PER_SEARCH = os.environ.get("SESSION_PER_SEARCH", "1") == "1"

# Proxy configuration
# Format: USER:PASS@HOST:PORT,USER:PASS@HOST:PORT
# Example: cust-us-s1:pass@us.proxy.net:12345,cust-de-s2:pass@de.proxy.net:12345
_proxy_list_env = os.environ.get("PROXY_LIST", "")
PROXY_LIST = []
if _proxy_list_env:
    for entry in _proxy_list_env.split(","):
        entry = entry.strip()
        if not entry:
            continue
        # If no scheme specified, default to http://
        if "://" not in entry:
            entry = f"http://{entry}"
        PROXY_LIST.append(entry)

# Single proxy fallback (if PROXY_LIST is empty)
PROXY_URL = os.environ.get("PROXY_URL")
if PROXY_URL and "://" not in PROXY_URL:
    PROXY_URL = f"http://{PROXY_URL}"

# Proxy rotation policies
PROXY_BINDING_MODE = os.environ.get("PROXY_BINDING_MODE", "independent")  # 'independent' or 'by_profile'
PROXY_ROTATION_REQUESTS = int(os.environ.get("PROXY_ROTATION_REQUESTS", "0"))  # Rotate proxy every N requests (0 = disabled)
PROXY_BLOCK_TIMEOUT_SEC = int(os.environ.get("PROXY_BLOCK_TIMEOUT_SEC", "300"))  # Time to keep proxy blocked (5 minutes default)
