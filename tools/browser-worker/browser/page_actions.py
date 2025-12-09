# comments: English only
"""Page interaction helpers"""
import time
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .config import GOOGLE_HOME, AI_READY_TIMEOUT_SEC, SEARCH_PAGE_OPEN_TIMEOUT_SEC, NEW_SEARCH_BUTTON_WAIT_SEC
from .selectors import AI_TEXTAREA_SEL, AI_TEXTAREA_ALT, NEW_SEARCH_BUTTON_SELECTORS


def is_profile_blocked(driver: webdriver.Chrome) -> bool:
    """Detect if profile/cookies are blocked by Google (captcha, unusual traffic).
    
    This indicates profile-level block that can be resolved by rotating profile only.
    For IP/proxy blocks, see is_proxy_blocked() which checks AI response text.
    
    Args:
        driver: Chrome driver instance
        
    Returns:
        True if profile blocked, False otherwise
    """
    if not driver:
        return False
    
    try:
        # Check page title and body text
        title = (driver.title or "").lower()
        
        # Google "unusual traffic" or "sorry" pages
        if "unusual traffic" in title or "sorry" in title:
            print("[BLOCK_DETECT] Google 'unusual traffic' page detected")
            return True
        
        # Check for reCAPTCHA/HCaptcha elements
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "div.g-recaptcha",
            "div.h-captcha",
            "#captcha-form",
        ]
        for sel in captcha_selectors:
            if driver.find_elements(By.CSS_SELECTOR, sel):
                print(f"[BLOCK_DETECT] Captcha detected: {sel}")
                return True
        
        # Check body text for block indicators
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body_text = (body.text or "").lower()
            
            block_phrases = [
                "unusual traffic",
                "automated queries",
                "sorry, you have been blocked",
                "access denied",
                "captcha",
            ]
            
            for phrase in block_phrases:
                if phrase in body_text:
                    print(f"[PROFILE_BLOCK] Block phrase detected: '{phrase}'")
                    return True
        except Exception:
            pass
        
        return False
    except Exception as e:
        print(f"[PROFILE_BLOCK] Error checking block status: {e}")
        return False


def is_proxy_blocked(response_text: str) -> bool:
    """Detect if proxy/IP is blocked based on AI response text.
    
    This indicates IP-level block that requires rotating both profile AND proxy.
    
    NOTE: "something went wrong..." is a GENERIC error that can happen for many reasons
    (server overload, bad prompt, etc.), not just proxy blocks. We should NOT treat it
    as a proxy block unless we see explicit IP-level block indicators.
    
    Args:
        response_text: Text response from Google AI
        
    Returns:
        True if proxy blocked, False otherwise
    """
    if not response_text:
        return False
    
    text_lower = response_text.lower().strip()
    
    # Only check for EXPLICIT IP-level block indicators
    # Generic errors like "something went wrong" should NOT trigger proxy rotation
    proxy_block_indicators = [
        "unusual traffic from your computer network",
        "automated queries",
        "your ip has been blocked",
        "access denied due to suspicious activity",
    ]
    
    for indicator in proxy_block_indicators:
        if indicator in text_lower:
            print(f"[PROXY_BLOCK] IP block detected: '{indicator}'")
            return True
    
    return False


def accept_google_consent(driver: webdriver.Chrome) -> None:
    """Accept Google consent dialogs if present.
    
    Args:
        driver: Chrome driver instance
    """
    if not driver:
        return
    
    for _ in range(4):
        try:
            for sel in [
                "button[aria-label='Accept all']",
                "button[aria-label='I agree']",
                "#introAgreeButton",
                "form[action*='consent'] button[type='submit']",
            ]:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    try:
                        driver.execute_script("arguments[0].click();", els[0])
                        time.sleep(0.2)
                        return
                    except Exception:
                        pass
            
            # Try to find buttons with "accept" or "agree" text
            candidates = driver.find_elements(By.CSS_SELECTOR, "button, div[role='button']")
            for el in candidates:
                try:
                    txt = (el.text or "").strip().lower()
                    if not txt:
                        continue
                    if "accept all" in txt or txt == "i agree" or "agree" in txt:
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.2)
                        return
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.3)


def ensure_aimode_ready(session_manager, timeout: int = AI_READY_TIMEOUT_SEC) -> bool:
    """Ensure Google AI Mode page is ready with textarea available.
    
    Checks ACTUAL state, not arbitrary timeouts!
    
    Args:
        session_manager: Session manager (single source of truth for driver)
        timeout: Maximum time to wait (safety fallback only)
        
    Returns:
        True if AI Mode is ready (textarea clickable), False otherwise
    """
    print(f"[PAGE_ACTIONS] ensure_aimode_ready: checking actual state")
    
    try:
        # Get driver - if fails, not ready
        try:
            driver, _ = session_manager.get_driver()
        except Exception as e:
            print(f"[PAGE_ACTIONS] No driver: {e}")
            return False
        
        if not driver:
            print("[PAGE_ACTIONS] Driver is None")
            return False
        
        # Load page
        print(f"[PAGE_ACTIONS] Loading {GOOGLE_HOME}")
        driver.get(GOOGLE_HOME)
        
        # Accept consent if present (non-blocking)
        print(f"[PAGE_ACTIONS] Accepting consent")
        accept_google_consent(driver)
        
        # Check if textarea is available (ACTUAL state check)
        ta_sel = (By.CSS_SELECTOR, AI_TEXTAREA_SEL)
        alt_sel = (By.CSS_SELECTOR, AI_TEXTAREA_ALT)
        
        print(f"[PAGE_ACTIONS] Checking textarea availability...")
        try:
            # Use reasonable wait (15s max) to let page load
            WebDriverWait(driver, 15).until(EC.element_to_be_clickable(ta_sel))
            print(f"[PAGE_ACTIONS] ✓ Textarea ready (primary selector)")
            return True
        except Exception:
            try:
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(alt_sel))
                print(f"[PAGE_ACTIONS] ✓ Textarea ready (alt selector)")
                return True
            except Exception:
                print(f"[PAGE_ACTIONS] ✗ Textarea not available")
                return False
                
    except Exception as e:
        print(f"[PAGE_ACTIONS] ✗ Error checking state: {e}")
        return False


def open_fresh_search_page(session_manager, timeout: int = SEARCH_PAGE_OPEN_TIMEOUT_SEC) -> bool:
    """Open Google home and ensure the AI textarea is focusable.
    
    Args:
        session_manager: Session manager (single source of truth for driver)
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if textarea is clickable, False otherwise
    """
    try:
        driver, _ = session_manager.get_driver()
    except Exception:
        return False
    
    if not driver:
        return False
    
    try:
        driver.get(GOOGLE_HOME)
        accept_google_consent(driver)
        
        ta_sel = (By.CSS_SELECTOR, AI_TEXTAREA_SEL)
        alt_sel = (By.CSS_SELECTOR, AI_TEXTAREA_ALT)
        
        try:
            WebDriverWait(driver, min(8, timeout)).until(EC.element_to_be_clickable(ta_sel))
            return True
        except Exception:
            try:
                WebDriverWait(driver, max(3, timeout - 8)).until(EC.element_to_be_clickable(alt_sel))
                return True
            except Exception:
                return False
    except Exception:
        return False


def try_click_new_search_button(session_manager, max_wait: int = NEW_SEARCH_BUTTON_WAIT_SEC) -> tuple[bool, bool]:
    """Try to click the 'Start new search' button if it exists.
    
    Args:
        session_manager: Session manager (single source of truth for driver)
        max_wait: Maximum time to wait for button in seconds
        
    Returns:
        Tuple of (clicked: bool, was_disabled: bool)
        - clicked: True if button was successfully clicked
        - was_disabled: True if button was found but remained disabled
    """
    try:
        driver, _ = session_manager.get_driver()
    except Exception:
        return False, False
    
    if not driver:
        return False, False
    
    end = time.time() + max_wait
    attempts = 0
    was_disabled = False
    
    while time.time() < end:
        for sel in NEW_SEARCH_BUTTON_SELECTORS:
            try:
                el = None
                if sel.startswith("//"):
                    el = driver.find_element(By.XPATH, sel)
                else:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                
                if el:
                    # Check if element is displayed and enabled
                    if not el.is_displayed():
                        continue
                    
                    # Try to check if button is disabled via aria-disabled or disabled attribute
                    try:
                        if el.get_attribute("disabled") or el.get_attribute("aria-disabled") == "true":
                            print(f"[PAGE_ACTIONS] Button found but disabled, waiting... (attempt {attempts + 1})")
                            was_disabled = True
                            time.sleep(0.5)
                            attempts += 1
                            continue
                    except Exception:
                        pass
                    
                    # Try to click
                    try:
                        # First try regular click
                        el.click()
                        time.sleep(0.3)
                        print("[PAGE_ACTIONS] Start new search button clicked successfully")
                        return True, False
                    except Exception:
                        # Fallback to JS click
                        try:
                            driver.execute_script("arguments[0].click();", el)
                            time.sleep(0.3)
                            print("[PAGE_ACTIONS] Start new search button clicked via JS")
                            return True, False
                        except Exception as e:
                            print(f"[PAGE_ACTIONS] Failed to click button: {e}")
                            pass
            except Exception:
                pass
        
        time.sleep(0.3)
        attempts += 1
    
    if was_disabled:
        print(f"[PAGE_ACTIONS] Start new search button remained disabled after {max_wait}s")
    else:
        print(f"[PAGE_ACTIONS] Start new search button not found after {max_wait}s")
    return False, was_disabled
