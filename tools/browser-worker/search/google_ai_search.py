# comments: English only
"""Google AI Mode search implementation"""
import re
import time
import json
from typing import Dict, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, InvalidSessionIdException, WebDriverException

from browser.config import ANSWER_TIMEOUT
from browser.selectors import (
    AI_TEXTAREA_SEL,
    AI_TEXTAREA_ALT,
    extract_ai_response,
    extract_clean_json,
    is_valid_json,
)
from browser.page_actions import (
    try_click_new_search_button,
    open_fresh_search_page,
)


def send_followup_prompt(prompt: str, session_manager) -> Dict[str, str]:
    """Send a follow-up prompt in the same dialog without refreshing the page.
    
    Args:
        prompt: Follow-up prompt to send
        session_manager: Session manager
        
    Returns:
        Dict with 'text' and 'html' keys
        
    Raises:
        TimeoutException: If follow-up times out
    """
    driver, wait = session_manager.get_driver()
    
    print(f"[FOLLOWUP] Sending follow-up prompt: {prompt}")
    
    # Find ALL textareas and pick the visible one (second dialog)
    el = None
    try:
        # Find all textareas matching our selector
        textareas = driver.find_elements(By.CSS_SELECTOR, AI_TEXTAREA_SEL)
        
        # Find the one that is displayed and enabled
        for ta in textareas:
            if ta.is_displayed() and ta.is_enabled():
                el = ta
                break
        
        if not el:
            textareas = driver.find_elements(By.CSS_SELECTOR, AI_TEXTAREA_ALT)
            for ta in textareas:
                if ta.is_displayed() and ta.is_enabled():
                    el = ta
                    break
    except Exception as e:
        print(f"[FOLLOWUP] Error finding textareas: {e}")
    
    if not el:
        raise TimeoutException("Textarea not found for follow-up prompt")
    
    # Click to focus and enable the textarea
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    
    # Clean prompt
    clean = re.sub(r"\s+", " ", (prompt or "").strip())
    
    # Input via JS and submit (same as main search)
    try:
        # Click to focus (use JS if regular click fails)
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        
        try:
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.BACKSPACE)
        except Exception:
            try:
                el.clear()
            except Exception:
                pass
        
        driver.execute_script(
            "arguments[0].value = arguments[1];\n"
            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));\n"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            el,
            clean,
        )
        
        # Wait for Send button to become enabled (same as main search)
        try:
            WebDriverWait(driver, 8).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "button[aria-label='Send']:not([disabled])") or
                         d.find_elements(By.CSS_SELECTOR, "button[data-xid='input-plate-send-button']:not([disabled])")
            )
        except Exception:
            raise TimeoutException("Send button disabled for follow-up")
        
        time.sleep(0.2)
        # Click Send button (same as main search)
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label='Send']:not([disabled])") or \
                   driver.find_elements(By.CSS_SELECTOR, "button[data-xid='input-plate-send-button']:not([disabled])")
            if btns:
                btns[0].click()
            else:
                el.send_keys(Keys.ENTER)
        except Exception:
            el.send_keys(Keys.ENTER)
    except Exception as e:
        raise RuntimeError(f"Failed to submit follow-up: {e}")
    
    # Wait for response (similar to main search logic but simpler)
    t_end = time.time() + ANSWER_TIMEOUT
    
    # Capture initial HTML before followup to detect when DOM actually changes
    initial_res = extract_ai_response(session_manager)
    initial_text = (initial_res.get("text") or "").strip()
    initial_html = (initial_res.get("html") or "").strip()
    print(f"[FOLLOWUP] Initial text before followup: {repr(initial_text[:100])}")
    print(f"[FOLLOWUP] Initial HTML size: {len(initial_html)}")
    
    # Wait a bit for the request to be sent
    time.sleep(0.5)
    
    text_changed = False  # Track if text changed from initial
    html_changed = False  # Track if HTML changed (more reliable than text)
    last_text = ""
    last_html = ""
    stable_start = None  # When did the HTML become stable
    stable_threshold = 2.0  # Wait 2 seconds after HTML stabilizes
    
    while time.time() < t_end:
        try:
            res = extract_ai_response(session_manager)
            text = (res.get("text") or "").strip()
            html = (res.get("html") or "").strip()
            
            # Check if HTML changed from initial (more reliable than text comparison)
            if html and html != initial_html:
                html_changed = True
                if html != last_html:
                    print(f"[FOLLOWUP] HTML changed, new size={len(html)}, text size={len(text)}")
                    last_html = html
                    stable_start = None  # Reset stability timer
            
            # Check if text changed from initial (AI responded)
            if text and text != initial_text:
                text_changed = True
            
            if text and html_changed:
                # Try to extract JSON immediately
                cleaned = extract_clean_json(text)
                if cleaned:
                    # Valid JSON found - return immediately
                    print(f"[FOLLOWUP] Valid JSON found, size={len(cleaned)} - returning immediately")
                    return {"text": cleaned, "html": html}
                
                # No valid JSON yet - check if HTML is stable
                if html == last_html:
                    if stable_start is None:
                        stable_start = time.time()
                        print(f"[FOLLOWUP] HTML stable, starting stability timer")
                    else:
                        stable_duration = time.time() - stable_start
                        if stable_duration >= stable_threshold:
                            # HTML has been stable for threshold - return what we have
                            print(f"[FOLLOWUP] HTML stable for {stable_duration:.1f}s, no JSON found - returning text")
                            return {"text": text, "html": html}
                
                # Log progress
                if text != last_text:
                    last_text = text
                    print(f"[FOLLOWUP] Text changed, size={len(text)}, no valid JSON yet - continuing to wait")
        except Exception as e:
            print(f"[FOLLOWUP] Extraction failed: {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(0.1)
    
    # Timeout - return what we have
    final_res = extract_ai_response(session_manager)
    final_text = (final_res.get("text") or "").strip()
    print(f"[FOLLOWUP] Timeout - returning final text, size={len(final_text)}")
    return {"text": final_text, "html": final_res.get("html", "")}


def search_google_ai(prompt: str, session_manager, _retry_count: int = 0, _force_fresh_page: bool = False) -> Dict[str, str]:
    """Perform Google AI mode search.
    
    Mirrors the logic from tools/chromium-worker/search/google-ai-search.js
    
    Args:
        prompt: Search query
        session_manager: Session manager (required - single source of truth for driver)
        _retry_count: Internal retry counter to prevent infinite recursion
        _force_fresh_page: Force opening fresh page (used after session rotation)
        
    Returns:
        Dict with 'text' and 'html' keys
        
    Raises:
        TimeoutException: If search times out
        RuntimeError: If driver is not initialized or max retries exceeded
    """
    if not session_manager:
        raise RuntimeError("Session manager is required")
    
    # Prevent infinite recursion - max 2 retries
    if _retry_count > 2:
        print(f"\n{'='*80}")
        print(f"[SEARCH] CRITICAL: Max retries exceeded ({_retry_count} attempts)")
        print(f"[SEARCH] This may cause request failure but should NOT restart container")
        print(f"{'='*80}\n")
        raise RuntimeError(f"Max retries exceeded ({_retry_count} attempts)")
    
    # Get driver from session_manager - single source of truth
    # Always get fresh reference to ensure we have the current driver
    driver, wait = session_manager.get_driver()
    
    # After session rotation, always open fresh page to ensure clean state
    # This prevents race condition where old error messages are still visible
    if _force_fresh_page:
        print("[SEARCH] Opening fresh page after session rotation")
        if not open_fresh_search_page(session_manager, timeout=12):
            raise TimeoutException("AI Mode not reachable after session rotation")
        clicked = False
        was_disabled = False
    else:
        # Try to click "Start new search" button first (faster), fallback to fresh page
        # Wait up to 5 seconds for button to become clickable (it may be disabled initially)
        clicked, was_disabled = try_click_new_search_button(session_manager, max_wait=5)
    
    if not clicked:
        # If button was disabled for entire wait period, force session rotation
        # This prevents getting stuck with disabled button while prompts keep switching
        if was_disabled:
            print("[SEARCH] Start new search button remained disabled - forcing session rotation")
            if session_manager:
                print(f"[SEARCH] Retry attempt {_retry_count + 1}/3")
                session_manager.rotate_identity("button disabled")
                # Retry entire search with new driver and force fresh page
                return search_google_ai(prompt, session_manager, _retry_count + 1, _force_fresh_page=True)
            else:
                raise TimeoutException("AI Mode button disabled, no session manager")
        else:
            # Button not found - try fresh page first
            print("[SEARCH] Start new search button not found")
            if not open_fresh_search_page(session_manager, timeout=12):
                # If fresh page also fails, rotate session and try again
                print("[SEARCH] Fresh page failed, rotating session...")
                if session_manager:
                    print(f"[SEARCH] Retry attempt {_retry_count + 1}/3")
                    session_manager.rotate_identity("button not found, fresh page failed")
                    # Retry entire search with new driver and force fresh page
                    return search_google_ai(prompt, session_manager, _retry_count + 1, _force_fresh_page=True)
                else:
                    raise TimeoutException("AI Mode not reachable (fresh page)")
    
    # Find textarea - if not available after button click, open fresh page
    el = None
    try:
        el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, AI_TEXTAREA_SEL)))
    except Exception:
        try:
            el = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, AI_TEXTAREA_ALT)))
        except Exception:
            # Textarea not available - try fresh page
            if not open_fresh_search_page(session_manager, timeout=12):
                raise TimeoutException("AI Mode textarea not reachable")
            # Try again after fresh page
            try:
                el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, AI_TEXTAREA_SEL)))
            except Exception:
                el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, AI_TEXTAREA_ALT)))
    
    # Clean prompt - replace newlines with spaces
    clean = re.sub(r"\s+", " ", (prompt or "").strip())
    
    # Input via JS and submit
    try:
        # Use JavaScript to avoid stale element issues
        driver.execute_script("arguments[0].click();", el)
        
        try:
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.BACKSPACE)
        except Exception:
            try:
                el.clear()
            except Exception:
                pass
        
        # Set value via JS - this is more reliable than send_keys
        driver.execute_script(
            "arguments[0].value = arguments[1];\n"
            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));\n"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            el,
            clean,
        )
        
        # Wait for Send button to become enabled (disabled=false)
        # Button selector: button[aria-label='Send'] or button with data-xid='input-plate-send-button'
        send_button_enabled = False
        try:
            WebDriverWait(driver, 8).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "button[aria-label='Send']:not([disabled])") or
                         d.find_elements(By.CSS_SELECTOR, "button[data-xid='input-plate-send-button']:not([disabled])")
            )
            print("[SEARCH] Send button is enabled")
            send_button_enabled = True
        except Exception:
            print("[SEARCH] WARNING: Send button still disabled after text input")
        
        # If button didn't become enabled, rotate session and retry
        if not send_button_enabled:
            print("[SEARCH] Send button disabled - forcing session rotation")
            if session_manager:
                print(f"[SEARCH] Retry attempt {_retry_count + 1}/3")
                session_manager.rotate_identity("send button disabled")
                # Retry search with new driver and force fresh page
                return search_google_ai(prompt, session_manager, _retry_count + 1, _force_fresh_page=True)
            else:
                raise TimeoutException("Send button disabled, no session manager")
        
        time.sleep(0.2)
        # Prefer clicking the Send button to avoid any interaction with newline handling
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label='Send']:not([disabled])") or \
                   driver.find_elements(By.CSS_SELECTOR, "button[data-xid='input-plate-send-button']:not([disabled])")
            if btns:
                btns[0].click()
                print("[SEARCH] Clicked Send button")
            else:
                # Fallback: press Enter if button not found
                # Re-find textarea to avoid stale element reference
                try:
                    fresh_el = driver.find_element(By.CSS_SELECTOR, AI_TEXTAREA_SEL)
                    fresh_el.send_keys(Keys.ENTER)
                except Exception:
                    el.send_keys(Keys.ENTER)
                print("[SEARCH] Send button not found, pressed Enter")
        except Exception as e:
            # Last resort fallback - re-find textarea to avoid stale element
            print(f"[SEARCH] Failed to click Send button ({e}), trying Enter fallback")
            try:
                fresh_el = driver.find_element(By.CSS_SELECTOR, AI_TEXTAREA_SEL)
                fresh_el.send_keys(Keys.ENTER)
            except Exception:
                try:
                    el.send_keys(Keys.ENTER)
                except Exception as e2:
                    print(f"[SEARCH] Enter fallback also failed: {e2}")
    except Exception as e:
        raise RuntimeError(f"Failed to submit search: {e}")
    
    # Wait for primary AI selectors (aimfl is most reliable)
    try:
        WebDriverWait(driver, 8).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "[data-subtree='aimfl']")
        )
        print("[SEARCH] aimfl selector found")
    except Exception:
        print("[SEARCH] Primary selectors not found, checking what's on page...")
        # Debug: log what elements are present
        try:
            debug_info = driver.execute_script("""
                return {
                    aimfl: !!document.querySelector('[data-subtree="aimfl"]'),
                    Y3BBE: !!document.querySelector('.Y3BBE'),
                    aiOverview: !!document.querySelector('[data-attrid="AIOverview"]'),
                    search: !!document.querySelector('#search'),
                    main: !!document.querySelector('#main'),
                    bodyLength: document.body?.textContent?.length || 0,
                    firstDivText: document.querySelector('div')?.textContent?.substring(0, 100) || ''
                };
            """)
            print(f"[SEARCH] Page elements: {debug_info}")
        except Exception as e:
            print(f"[SEARCH] Debug failed: {e}")
    
    # Wait for AI response using selectors only (no body growth heuristic)
    t_end = time.time() + ANSWER_TIMEOUT
    nudge_at = time.time() + 2.5
    last_text = ""
    last_text_time = None
    text_stable_threshold = 2.0  # Text must be stable for 2 seconds before returning (increased to reduce false positives)
    
    # Track Google errors separately - these trigger rotation
    google_error_type = None  # Will be set to error type if detected
    google_error_first_seen = None
    google_error_threshold = 3.0  # If same Google error persists 3 seconds → rotate
    
    def is_valid_response(text: str) -> bool:
        """Check if text looks like a valid complete response (not intermediate state)."""
        if not text:
            return False
        
        # Reject obvious intermediate states that Google shows while generating
        text_lower = text.lower().strip()
        
        # Pattern 1: "N sites" (e.g., "10 sites", "2 sites") - intermediate loading state
        if re.match(r'^\d+\s+sites?$', text_lower):
            return False  # Silent rejection - too noisy in logs
        
        # Pattern 2: Just the word "json" or "{content: }" - incomplete response
        if text_lower in ('json', '{content: }') or (text_lower.startswith('json') and len(text_lower) < 10):
            return False
        
        # Pattern 3: Google AI refusal messages
        if 'no response available' in text_lower or 'try asking something else' in text_lower:
            return False
        
        # Pattern 4: Very short responses (< 10 chars) - likely incomplete
        if len(text) < 10:
            return False
        
        # Text is already cleaned by selectors - no need to clean markdown here
        # If text looks like JSON, try to parse it
        if text.startswith('{') or text.startswith('['):
            # Must have closing brace/bracket
            if text.startswith('{') and not text.endswith('}'):
                return False
            if text.startswith('[') and not text.endswith(']'):
                return False
            
            # Try to parse as JSON - this is the real validation
            try:
                import json
                parsed = json.loads(text)
                
                # For domain search, must contain "domain" key; for patterns, must contain "patterns" key
                if isinstance(parsed, dict):
                    if 'domain' not in parsed and 'patterns' not in parsed:
                        print(f"[SEARCH] Valid JSON but missing required keys (domain/patterns)")
                        return False
                
                return True
            except json.JSONDecodeError as e:
                print(f"[SEARCH] Invalid JSON: {e}")
                return False
        
        # Non-JSON text - always invalid (we need JSON only)
        return False
    
    while time.time() < t_end:
        
        # Selector-based extraction
        try:
            res = extract_ai_response(session_manager)
            text = (res.get("text") or "").strip()
            text_lower = text.lower()  # Define text_lower early for all checks
            
            # Detect Google error messages - DO NOT rotate inside while loop!
            # Just remember the error type and continue checking
            detected_error = None
            norm = " ".join(text.split()).strip().lower()
            
            # Check ONLY for proxy block error (either part is enough)
            if "something went wrong" in text_lower or "ai response wasn't generated" in text_lower:
                detected_error = "proxy_blocked"
            
            # Track Google errors - only rotate if error persists
            if detected_error:
                if google_error_type == detected_error:
                    # Same error - check duration
                    error_duration = time.time() - google_error_first_seen
                    if error_duration < google_error_threshold:
                        print(f"[SEARCH] Google error '{detected_error}' seen, waiting ({error_duration:.1f}s/{google_error_threshold}s)")
                        # Continue loop - maybe error will clear
                    else:
                        # Error persisted too long - break loop and rotate outside
                        print(f"[SEARCH] Google error '{detected_error}' persisted {error_duration:.1f}s - will rotate")
                        break  # Exit while loop - handle rotation after
                else:
                    # New/different error
                    print(f"[SEARCH] Google error detected: {detected_error}")
                    google_error_type = detected_error
                    google_error_first_seen = time.time()
            else:
                # No error - reset tracking
                google_error_type = None
                google_error_first_seen = None
                
                # Check if we have valid text
                if text:
                    # Try to extract valid JSON immediately
                    cleaned = extract_clean_json(text)
                    if cleaned and is_valid_response(text):
                        # Valid JSON found - return immediately
                        print(f"[SEARCH] Valid JSON found, size={len(cleaned)} - returning immediately")
                        return {"text": cleaned, "html": res.get('html', ''), "raw_text": text}
                    
                    # No valid JSON yet - check if text is changing
                    if text != last_text:
                        # Text is still growing
                        if last_text:
                            print(f"[SEARCH] Text changed from {len(last_text)} to {len(text)} chars")
                        last_text = text
                        last_text_time = time.time()
                        print(f"[SEARCH] Text growing, size={len(text)}, no valid JSON yet")
                    elif last_text_time is not None:
                        # Text is the same - check if it's been stable long enough
                        stable_duration = time.time() - last_text_time
                        if stable_duration >= text_stable_threshold:
                            # Text stable but no valid JSON - try fallback
                            print(f"[SEARCH] Text stable for {stable_duration:.1f}s but no valid JSON (size={len(text)})")
                            print(f"[SEARCH] Invalid text preview: {repr(text[:200])}")
                            print(f"[SEARCH] Trying fallback prompt 'json' in same dialog (attempt 1)")
                            try:
                                fallback_res = send_followup_prompt("return json", session_manager)
                                fallback_text = fallback_res.get('text', '').strip()
                                print(f"[SEARCH] Fallback attempt 1 response received, size={len(fallback_text)}")
                                
                                # Check if we got valid JSON (not just any text)
                                if fallback_text:
                                    cleaned = extract_clean_json(fallback_text)
                                    if cleaned:
                                        print(f"[SEARCH] Fallback attempt 1 returned valid JSON")
                                        return {"text": cleaned, "html": fallback_res.get('html', ''), "raw_text": fallback_text}
                                
                                # First attempt returned empty or invalid - try one more time
                                print(f"[SEARCH] First fallback returned no valid JSON, trying again (attempt 2)")
                                time.sleep(1.0)  # Brief pause before retry
                                fallback_res = send_followup_prompt("json only", session_manager)
                                fallback_text = fallback_res.get('text', '').strip()
                                print(f"[SEARCH] Fallback attempt 2 response received, size={len(fallback_text)}")
                                
                                # Check second attempt for valid JSON
                                if fallback_text:
                                    cleaned = extract_clean_json(fallback_text)
                                    if cleaned:
                                        print(f"[SEARCH] Fallback attempt 2 returned valid JSON")
                                        return {"text": cleaned, "html": fallback_res.get('html', ''), "raw_text": fallback_text}
                                
                                # Both attempts failed - return what we have
                                print(f"[SEARCH] Both fallback attempts failed to return valid JSON")
                                return fallback_res
                            except Exception as e:
                                print(f"[SEARCH] Fallback failed: {e}, returning empty result")
                                return {"text": "", "html": ""}
                    else:
                        # First time seeing this text - start stability timer
                        last_text = text
                        last_text_time = time.time()
                        print(f"[SEARCH] First text found, size={len(text)}")
            
        except Exception as e:
            print(f"[SEARCH] Selector extraction failed: {e}")
        
        # Periodic nudge
        if time.time() >= nudge_at:
            try:
                el2 = driver.find_element(By.CSS_SELECTOR, AI_TEXTAREA_SEL)
            except Exception:
                try:
                    el2 = driver.find_element(By.CSS_SELECTOR, AI_TEXTAREA_ALT)
                except Exception:
                    el2 = None
            if el2 is not None:
                try:
                    el2.send_keys(Keys.ENTER)
                except Exception:
                    pass
            nudge_at = time.time() + 2.5
        
        time.sleep(0.1)
    
    # Exited while loop - either timeout or Google error persisted
    print(f"[SEARCH] Exited wait loop. google_error={google_error_type}, last_text={bool(last_text)}")
    
    # PRIORITY 1: Check if we exited due to persistent Google error → rotate and retry
    if google_error_type and session_manager and _retry_count < 2:
        print(f"[SEARCH] Google error '{google_error_type}' persisted - rotating and retrying (attempt {_retry_count + 1}/3)")
        
        # Notify coordinator about proxy block ONLY for proxy-level errors
        # ONLY: "something went wrong and an ai response wasn't generated"
        if google_error_type == "proxy_blocked":
            try:
                import httpx
                import os
                coordinator_url = os.environ.get("COORDINATOR_URL", "http://proxy-coordinator:4200")
                # Get current proxy index to report
                current_proxy_idx = session_manager.driver_proxy_idx if hasattr(session_manager, 'driver_proxy_idx') else 0
                with httpx.Client(timeout=2.0) as client:
                    client.post(f"{coordinator_url}/block-proxy", json={
                        "proxy_idx": current_proxy_idx,
                        "reason": google_error_type
                    })
                print(f"[SEARCH] Notified coordinator about proxy block (idx={current_proxy_idx})")
            except Exception as e:
                print(f"[SEARCH] Failed to notify coordinator: {e}")
        else:
            print(f"[SEARCH] Error '{google_error_type}' is content-level, not proxy block - no coordinator notification")
        
        session_manager.rotate_identity(f"google error: {google_error_type}")
        # Recursive retry with fresh page
        return search_google_ai(prompt, session_manager, _retry_count + 1, _force_fresh_page=True)
    
    # PRIORITY 2: If max retries reached with Google error → return empty JSON
    if google_error_type:
        print(f"[SEARCH] Google error '{google_error_type}' after {_retry_count} retries - returning empty JSON")
        return {"text": "{}", "html": ""}
    
    # PRIORITY 3: Regular timeout - return last text if any
    if last_text:
        print(f"[SEARCH] Timeout but have last_text from selectors, size={len(last_text)}")
        return {"text": last_text, "html": "", "raw_text": last_text}
    
    # PRIORITY 4: Complete failure - no text, no error
    print("[SEARCH] Timeout with no response and no Google error")
    raise TimeoutException("AI response not found within timeout")


