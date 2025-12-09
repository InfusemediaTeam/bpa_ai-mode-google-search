# comments: English only
"""DOM selectors and content extraction"""
import re
import json
from typing import Dict
from selenium.webdriver.remote.webdriver import WebDriver


def is_valid_json(json_str: str) -> bool:
    """Validate JSON string for required structure and content.
    
    Checks:
    1. Valid JSON syntax
    2. No 'example' strings in the content (case-insensitive)
    3. Required field: 'domain' OR 'patterns'
    
    Args:
        json_str: JSON string to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not json_str:
        return False
    
    try:
        # Parse JSON
        data = json.loads(json_str)
        
        # Check for placeholder domains in the entire JSON string (case-insensitive)
        json_lower = json_str.lower()
        if 'example' in json_lower or 'domain.com' in json_lower:
            print(f"[VALIDATOR] Rejected: contains placeholder domain ('example' or 'domain.com')")
            return False
        
        # Check for required fields: 'domain' OR 'patterns'
        # Handle both dict and list responses
        if isinstance(data, dict):
            has_domain = 'domain' in data
            has_patterns = 'patterns' in data
            if not (has_domain or has_patterns):
                print("[VALIDATOR] Rejected: missing required field 'domain' or 'patterns'")
                return False
        elif isinstance(data, list):
            # For arrays, check if at least one item has the required fields
            if not data:
                print("[VALIDATOR] Rejected: empty array")
                return False
            # Check first item (assuming homogeneous structure)
            first_item = data[0]
            if isinstance(first_item, dict):
                has_domain = 'domain' in first_item
                has_patterns = 'patterns' in first_item
                if not (has_domain or has_patterns):
                    print("[VALIDATOR] Rejected: array items missing 'domain' or 'patterns'")
                    return False
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"[VALIDATOR] Invalid JSON syntax: {e}")
        return False


def extract_clean_json(text: str) -> str:
    """Extract clean JSON from text that may contain markdown or HTML.
    
    Finds JSON starting with { or [ and captures until matching closing brace,
    accounting for nested braces/brackets.
    Validates that extracted JSON is parseable.
    
    Args:
        text: Raw text from AI response
        
    Returns:
        Clean JSON string or empty string if no valid JSON found
    """
    if not text:
        return ""
    
    # Keep only valid JSON characters: letters, digits, JSON syntax, whitespace
    # This removes markdown, control characters, and other garbage
    import re
    # Allow: a-z A-Z 0-9 {} [] : , " ' . - _ @ space tab
    cleaned = re.sub(r'[^a-zA-Z0-9{}\[\]:,"\'.@\-_ \t]', '', text)
    
    # Find first { or [
    json_start = -1
    start_char = None
    for i, char in enumerate(cleaned):
        if char in ('{', '['):
            json_start = i
            start_char = char
            break
    
    if json_start == -1:
        return ""  # No JSON found
    
    # Find matching closing brace/bracket by counting balance
    open_char = start_char
    close_char = '}' if start_char == '{' else ']'
    balance = 0
    json_end = -1
    
    for i in range(json_start, len(cleaned)):
        char = cleaned[i]
        if char == open_char:
            balance += 1
        elif char == close_char:
            balance -= 1
            if balance == 0:
                json_end = i
                break
    
    if json_end == -1 or json_end <= json_start:
        return ""  # No matching closing brace - let fallback handle it
    
    # Extract JSON substring
    json_str = cleaned[json_start:json_end + 1].strip()
    
    # Validate using comprehensive validator
    if is_valid_json(json_str):
        return json_str
    else:
        return ""  # Not valid JSON or failed validation

# Textarea selectors
AI_TEXTAREA_SEL = "textarea.ITIRGe"
AI_TEXTAREA_ALT = "textarea[aria-label='Ask anything']"

# AI response selectors
AI_RESPONSE_SEL_PRIMARY = "[data-subtree='aimfl']"
AI_RESPONSE_FALLBACKS = [
    ".Y3BBE",
    "[data-attrid='AIOverview']",
    ".ai-overview",
    "[jsname*='ai']",
    "[data-hveid*='AI']",
    ".kp-wholepage",
]

# No search fallbacks - we only work with AI mode selectors
# Regular search selectors like #search, #rcnt, #main are not reliable for AI responses

# Button selectors
NEW_SEARCH_BUTTON_SELECTORS = [
    "button[aria-label='Start new search']",
    "button[title='Start new search']",
    "button.UTNPFf",
    "//button[@aria-label='Start new search']",
]


def extract_ai_response(session_manager) -> Dict[str, str]:
    """Extract AI response from Google search page.
    
    Mirrors the logic from tools/chromium-worker/search/selectors.js
    
    Args:
        session_manager: Session manager (single source of truth for driver)
        
    Returns:
        Dict with 'text' and 'html' keys
    """
    try:
        driver, _ = session_manager.get_driver()
    except Exception:
        return {"text": "", "html": ""}
    
    if not driver:
        return {"text": "", "html": ""}
    
    # Try direct Selenium access first (more reliable than execute_script)
    from selenium.webdriver.common.by import By
    try:
        # Primary selector: aimfl (MUST check this first, it's the most reliable)
        # IMPORTANT: Take the LAST element (most recent response)
        aimfl_elements = driver.find_elements(By.CSS_SELECTOR, AI_RESPONSE_SEL_PRIMARY)
        if aimfl_elements:
            element = aimfl_elements[-1]
            
            # Google AI splits JSON across multiple sibling elements!
            # {"domain":"<!--Sv6Kpe[]-->} is in one div, and the rest is in siblings
            # Solution: get textContent of PARENT element to capture all siblings
            try:
                parent = driver.execute_script("return arguments[0].parentElement;", element)
                if parent:
                    text = driver.execute_script("return arguments[0].textContent;", parent).strip()
                    html = parent.get_attribute("outerHTML") or ""
                else:
                    # Fallback to element itself if no parent
                    text = driver.execute_script("return arguments[0].textContent;", element).strip()
                    html = element.get_attribute("outerHTML") or ""
            except Exception:
                text = element.text.strip()
                html = element.get_attribute("outerHTML") or ""
            # Only log substantial responses to reduce noise (disabled to reduce spam)
            # if len(aimfl_elements) > 1:
            #     print(f"[SELECTORS] Found {len(aimfl_elements)} aimfl elements, using last one")
            # if text and len(text) > 20:
            #     print(f"[SELECTORS] Found aimfl via Selenium, size={len(text)}")
            if text:
                return {"text": text, "html": html}
    except Exception as e:
        print(f"[SELECTORS] Selenium aimfl failed: {e}")
    
    # Try AI-specific selectors (NOT search fallbacks yet)
    for sel in AI_RESPONSE_FALLBACKS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            if elements:
                text = elements[0].text.strip()
                if len(text) > 10:
                    html = elements[0].get_attribute("innerHTML") or ""
                    print(f"[SELECTORS] Found {sel} via Selenium, size={len(text)}")
                    return {"text": text, "html": html}
        except Exception:
            pass
    
    # If no AI selectors found via Selenium, try JS script as last resort
    try:
        script = f"""
        (() => {{
          // Primary selector: AI response container with data-subtree="aimfl"
          const aimflElement = document.querySelector({repr(AI_RESPONSE_SEL_PRIMARY)});
          if (aimflElement) {{
            const text = (aimflElement.textContent || '').trim();
            console.log('[SELECTORS] Found aimfl, size=' + text.length);
            // Return even if empty, let caller decide
            return {{ text, html: aimflElement.outerHTML || aimflElement.innerHTML || '', source: 'aimfl' }};
          }}
          
          // Try other AI-specific selectors
          const aiSelectors = {AI_RESPONSE_FALLBACKS};
          for (const selector of aiSelectors) {{
            const element = document.querySelector(selector);
            if (element && element.textContent && element.textContent.trim().length > 10) {{
              console.log('[SELECTORS] Found ' + selector + ', size=' + element.textContent.trim().length);
              return {{ text: element.textContent.trim(), html: element.innerHTML || '', source: selector }};
            }}
          }}
          
          // No AI selectors found - return empty
          console.log('[SELECTORS] No valid selectors found');
          return {{ text: '', html: '', source: 'none' }};
        }})()
        """
        res = driver.execute_script(script)
        if isinstance(res, dict) and "text" in res:
            source = res.get("source", "unknown")
            text = str(res.get("text") or "")
            text_len = len(text)
            print(f"[SELECTORS] Extracted from {source}, size={text_len}, preview={text[:100]}")
            return {"text": text, "html": str(res.get("html") or "")}
    except Exception as e:
        print(f"[SELECTORS] Script execution failed: {e}")
    
    # Fallback: try to find assistant message bubbles
    try:
        from selenium.webdriver.common.by import By
        bubbles = driver.find_elements(By.CSS_SELECTOR, "div[data-message-author-role='assistant']")
        if bubbles:
            txt = bubbles[-1].text.strip()
            return {"text": txt, "html": bubbles[-1].get_attribute("outerHTML") or ""}
    except Exception:
        pass
    
    return {"text": "", "html": ""}
