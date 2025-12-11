#!/usr/bin/env python3
# comments: English only
"""Python worker for Google AI search - refactored version.

Structured similarly to tools/chromium-worker/search for maintainability.
"""
import os
import time
import asyncio
import threading
import random

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from selenium.common.exceptions import TimeoutException, WebDriverException

from session import SessionManager
from session.manager import clean_old_session_dirs
from search import search_google_ai
from browser.config import PROFILES
from browser.selectors import extract_clean_json
from healthcheck_server import start_health_server

# ---------- CONFIG ----------
PORT = int(os.environ.get("WORKER_PORT", "4101"))

# ---------- STATE ----------
session_manager = SessionManager()
busy_lock = asyncio.Lock()
deferred_rotation_lock = threading.Lock()  # Protect deferred rotation flag
STARTUP_READY = False
REQUEST_COUNT_TOTAL = 0
DEFERRED_ROTATION_REASON = None  # Set when rotation is deferred due to busy worker

# ---------- API ----------
app = FastAPI()


class SearchRequest(BaseModel):
    prompt: str

# ---------- NOISE PROMPTS ----------
def _maybe_apply_noise(prompt: str, req_index: int):
    """Optionally add noise to the prompt on every 10th request.
    Uses zero-width characters to avoid semantic impact.
    Returns (new_prompt, applied: bool).
    """
    try:
        if req_index % 10 != 0:
            return prompt, False
        noise_chars = ["\u200b", "\u200c", "\u200d", "\ufeff"]  # ZWSP, ZWNJ, ZWJ, BOM
        suffix = "".join(random.choice(noise_chars) for _ in range(5))
        noisy = f"{prompt}{suffix}"
        print(f"[NOISE] Applied noise to request #{req_index}")
        return noisy, True
    except Exception as e:
        print(f"[NOISE] Failed to apply noise: {e}")
        return prompt, False


@app.get("/health")
async def health():
    """Health check endpoint - ALWAYS responds immediately.
    
    This endpoint MUST respond instantly regardless of worker state.
    It should NEVER block on Selenium operations or driver access.
    
    Linear logic:
    1. Startup -> warming up -> ok=True (warmup in progress)
    2. Ready -> idle/busy -> ok=True (can accept work)
    3. Chrome dead -> ok=False (real problem)
    """
    # Check 1: If busy, worker is healthy (actively processing)
    is_busy = busy_lock.locked()
    
    # Check 2: Chrome processes exist AND are not zombies (via psutil, non-blocking)
    chrome_alive = False
    try:
        import psutil
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
    except Exception:
        pass
    
    # Worker is OK if:
    # - Warming up (Chrome may not be alive yet), OR
    # - Busy (actively working), OR  
    # - Chrome alive (ready for work)
    warmup_in_progress = not STARTUP_READY
    ok = warmup_in_progress or is_busy or chrome_alive
    
    # ready should be false if chrome is dead (even if warmup completed before)
    actually_ready = STARTUP_READY and chrome_alive
    
    # Get browser info
    browser_name = "chromium" if os.environ.get("CHROME_BINARY", "").endswith("chromium") else "chrome"
    browser_version = None
    try:
        import subprocess
        chrome_bin = os.environ.get("CHROME_BINARY", "/usr/bin/chromium")
        result = subprocess.run([chrome_bin, "--version"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            # Output like: "Chromium 131.0.6778.85"
            version_str = result.stdout.strip()
            parts = version_str.split()
            if len(parts) >= 2:
                browser_version = parts[-1]  # Get last part (version number)
    except Exception:
        pass
    
    return {
        "ok": ok,
        "busy": is_busy,
        "chrome_alive": chrome_alive,
        "ready": actually_ready,
        "warmup": warmup_in_progress,
        "browser": browser_name,
        "version": browser_version,
    }


@app.post("/browser/restart")
async def browser_restart():
    """Restart browser session."""
    try:
        print("[API] Browser restart requested")
        session_manager.rotate_identity("manual restart")
        print("[API] Browser restarted successfully")
        return {"ok": True, "message": "browser restarted"}
    except Exception as e:
        print(f"[API] Browser restart failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/session/refresh")
async def session_refresh():
    """Refresh browser session (rotate identity)."""
    try:
        print("[API] Session refresh requested")
        session_manager.rotate_identity("session refresh")
        print("[API] Session refreshed successfully")
        return {"ok": True, "message": "session refreshed"}
    except Exception as e:
        print(f"[API] Session refresh failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search")
async def search(req: SearchRequest, request: Request):
    """Perform Google AI search."""
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Invalid prompt")
    
    # CRITICAL: Block search until warmup complete
    if not STARTUP_READY:
        return JSONResponse(status_code=503, content={
            "ok": False, 
            "error": "warming_up", 
            "message": "Worker is warming up, retry in a few seconds"
        })
    
    if busy_lock.locked():
        return JSONResponse(status_code=423, content={"ok": False, "busy": True, "message": "busy"})
    
    started = time.time()
    try:
        _san = prompt[:60].replace("\n", " ").replace("\r", " ")
    except Exception:
        _san = prompt[:60]
    
    print(f"\n{'='*80}")
    print(f"[API] /search REQUEST")
    print(f"[API] Prompt: {prompt}")
    print(f"[API] Client: {request.client.host if request.client else 'unknown'}")
    print(f"{'='*80}\n")
    
    # Use async with to guarantee lock release even with early returns
    async with busy_lock:
        # Check if there's a deferred rotation from coordinator
        # Do this INSIDE busy_lock to prevent race conditions
        global DEFERRED_ROTATION_REASON
        deferred_reason = None
        with deferred_rotation_lock:
            if DEFERRED_ROTATION_REASON:
                deferred_reason = DEFERRED_ROTATION_REASON
                DEFERRED_ROTATION_REASON = None  # Clear flag
        
        if deferred_reason:
            print(f"[API] Executing DEFERRED rotation: {deferred_reason}")
            try:
                session_manager.rotate_proxy_only(deferred_reason)
                print(f"[API] Deferred rotation completed successfully")
            except Exception as e:
                print(f"[API] Deferred rotation failed: {e}")
        
        try:
            # Run blocking Selenium operations in thread pool to not block event loop
            # This allows /health endpoint to respond even when search is in progress
            def _blocking_search():
                global REQUEST_COUNT_TOTAL
                REQUEST_COUNT_TOTAL += 1
                req_index = REQUEST_COUNT_TOTAL
                modified_prompt, noise_applied = _maybe_apply_noise(prompt, req_index)
                if noise_applied:
                    print(f"[API] Noise applied on request #{req_index}")
                session_manager.maybe_rotate_for_search()
                return search_google_ai(modified_prompt, session_manager)
            
            loop = asyncio.get_event_loop()
            raw_result = await loop.run_in_executor(None, _blocking_search)
            
            # Notify coordinator about request completion (for auto-rotation)
            # Do this BEFORE validation - count all requests regardless of result
            try:
                import httpx
                coordinator_url = os.environ.get("COORDINATOR_URL", "http://proxy-coordinator:4200")
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.post(f"{coordinator_url}/increment-request", json={})
            except Exception as e:
                print(f"[API] Failed to notify coordinator: {e}")
            
            # Validate and clean result - ALWAYS return valid JSON or empty string
            # Get raw text from result (preserve original AI output)
            raw_text_from_ai = raw_result.get("raw_text") or raw_result.get("text") or ""
            cleaned_json = raw_result.get("text") or ""
            
            # Check for Google AI blocking error
            if raw_text_from_ai and "this request is not supported" in raw_text_from_ai.lower():
                duration_ms = int((time.time() - started) * 1000)
                print(f"\n{'='*80}")
                print(f"[API] /search RESPONSE - BLOCKED BY GOOGLE AI")
                print(f"[API] Duration: {duration_ms}ms")
                print(f"[API] Error: 'This request is not supported'")
                print(f"[API] Raw response: {raw_text_from_ai[:200]}")
                print(f"[API] This worker is blocked, should retry with another worker")
                print(f"{'='*80}\n")
                return JSONResponse(
                    status_code=503, 
                    content={
                        "ok": False, 
                        "error": "blocked_by_google", 
                        "message": "This request is not supported",
                        "retry_other_worker": True,
                        "durationMs": duration_ms
                    }
                )
            
            # If text is not already cleaned, try to extract JSON
            if cleaned_json and not cleaned_json.strip().startswith('{'):
                cleaned_json = extract_clean_json(cleaned_json) if cleaned_json else ""
            
            # If no valid JSON found, return error with empty result
            # Worker already did 2 retry attempts to get JSON from AI
            if not cleaned_json:
                duration_ms = int((time.time() - started) * 1000)
                print(f"\n{'='*80}")
                print(f"[API] /search RESPONSE - EMPTY RESULT")
                print(f"[API] Duration: {duration_ms}ms")
                print(f"[API] No valid JSON after 2 fallback attempts")
                if raw_text_from_ai:
                    print(f"[API] Raw text preview: {repr(raw_text_from_ai[:200])}")
                print(f"{'='*80}\n")
                return JSONResponse(
                    status_code=422,
                    content={
                        "ok": False,
                        "error": "empty_result",
                        "message": "No valid JSON extracted after retries",
                        "raw_text": raw_text_from_ai[:500] if raw_text_from_ai else None,
                        "html": raw_result.get("html") or "",
                        "durationMs": duration_ms
                    }
                )
            
            # Valid JSON found
            result = {
                "json": cleaned_json,
                "html": raw_result.get("html") or "",
                "raw_text": raw_text_from_ai  # Include raw for debugging
            }
            
            # Increment search counter and check if rotation needed
            session_manager.search_count += 1
            if session_manager.search_count >= session_manager.max_searches_per_session:
                print(f"[API] Proactive rotation after {session_manager.search_count} searches to prevent memory leaks")
                session_manager.rotate_identity("proactive rotation - max searches reached")
                session_manager.search_count = 0
            
            duration_ms = int((time.time() - started) * 1000)
            json_result = result.get('json') or ''
            raw_text = result.get('raw_text') or ''
            
            print(f"\n{'='*80}")
            print(f"[API] /search RESPONSE - SUCCESS")
            print(f"[API] Duration: {duration_ms}ms")
            print(f"[API] Valid JSON: {bool(json_result)}")
            print(f"[API] JSON size: {len(json_result)} chars")
            if raw_text and raw_text != json_result:
                print(f"[API] Raw text size: {len(raw_text)} chars")
                print(f"[API] Raw text preview: {repr(raw_text[:200])}")
            if json_result:
                print(f"[API] JSON preview: {json_result[:200]}")
            else:
                print(f"[API] Empty response (will trigger fallback in API)")
            print(f"{'='*80}\n")
            
            return {"ok": True, "result": result, "durationMs": duration_ms}
        
        except TimeoutException as e:
            duration_ms = int((time.time() - started) * 1000)
            print(f"\n{'='*80}")
            print(f"[API] /search RESPONSE - TIMEOUT")
            print(f"[API] Duration: {duration_ms}ms")
            print(f"[API] Error: {str(e)}")
            print(f"{'='*80}\n")
            return JSONResponse(status_code=504, content={"ok": False, "error": "timeout", "durationMs": duration_ms})
        
        except WebDriverException as e:
            duration_ms = int((time.time() - started) * 1000)
            print(f"\n{'='*80}")
            print(f"[API] /search RESPONSE - WEBDRIVER ERROR")
            print(f"[API] Duration: {duration_ms}ms")
            print(f"[API] Error: {str(e)[:200]}")
            print(f"[API] Prompt: {prompt[:100]}")
            print(f"[API] Request count: {REQUEST_COUNT_TOTAL}")
            import traceback
            print(f"[API] Traceback:")
            traceback.print_exc()
            print(f"{'='*80}\n")
            # Rotate identity on WebDriver errors
            try:
                session_manager.rotate_identity("WebDriverException")
            except Exception:
                pass
            return JSONResponse(status_code=500, content={"ok": False, "error": str(e), "durationMs": duration_ms})
        
        except Exception as e:
            duration_ms = int((time.time() - started) * 1000)
            print(f"\n{'='*80}")
            print(f"[API] /search RESPONSE - UNEXPECTED ERROR")
            print(f"[API] Duration: {duration_ms}ms")
            print(f"[API] Error type: {type(e).__name__}")
            print(f"[API] Error: {str(e)}")
            print(f"[API] Prompt: {prompt[:100]}")
            print(f"[API] Request count: {REQUEST_COUNT_TOTAL}")
            import traceback
            print(f"[API] Full traceback:")
            traceback.print_exc()
            print(f"{'='*80}\n")
            return JSONResponse(status_code=500, content={"ok": False, "error": str(e), "durationMs": duration_ms})


@app.post("/rotate-proxy")
async def rotate_proxy(request: Request):
    """Rotate proxy - called by coordinator when proxy rotation needed.
    
    This endpoint is called by the proxy coordinator to trigger proxy rotation
    on this worker when threshold is reached or proxy is blocked.
    """
    try:
        body = await request.json()
        reason = body.get("reason", "coordinator request")
    except Exception:
        reason = "coordinator request"
    
    print(f"\n{'='*80}")
    print(f"[API] /rotate-proxy REQUEST from coordinator")
    print(f"[API] Reason: {reason}")
    
    # Check if worker is busy - skip rotation to avoid killing active request
    if busy_lock.locked():
        global DEFERRED_ROTATION_REASON
        with deferred_rotation_lock:
            DEFERRED_ROTATION_REASON = reason
        print(f"[API] Worker is BUSY - deferring rotation until next request")
        print(f"[API] Rotation will happen automatically when current request completes")
        print(f"{'='*80}\n")
        return {
            "ok": True,
            "rotated": False,
            "deferred": True,
            "reason": "worker busy - will rotate on next request"
        }
    
    print(f"{'='*80}\n")
    
    try:
        # Rotate proxy only (keep same profile)
        session_manager.rotate_proxy_only(reason)
        print(f"[API] Proxy rotation successful")
        return {"ok": True, "rotated": True, "reason": reason}
    except Exception as e:
        print(f"[API] Proxy rotation failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e), "reason": reason}
        )


# ---------- STARTUP WARMUP & WATCHDOG ----------
def _warmup_sync() -> None:
    """Warmup browser session on startup - BLOCKS /search until done.
    
    Checks ACTUAL state, not timeouts!
    """
    global STARTUP_READY
    print("[WARMUP] Starting - /search blocked until textarea is ready")
    
    for attempt in range(3):
        try:
            print(f"[WARMUP] Attempt {attempt + 1}/3: initializing browser")
            session_manager.rotate_identity("startup warmup")
            
            from browser.page_actions import ensure_aimode_ready
            # Check actual state: is textarea clickable?
            if ensure_aimode_ready(session_manager):
                STARTUP_READY = True
                print("[WARMUP] ✓ READY - textarea clickable, /search accepting requests")
                return
            else:
                print(f"[WARMUP] ✗ Attempt {attempt + 1}: textarea not ready")
                
        except Exception as e:
            print(f"[WARMUP] ✗ Attempt {attempt + 1} error: {e}")
    
    STARTUP_READY = False
    print("[WARMUP] ✗ FAILED - textarea not ready after 3 attempts, rejecting /search")


@app.on_event("startup")
def on_startup() -> None:
    """Start background warmup and watchdog threads."""
    import signal
    import sys
    
    # Register signal handlers to log shutdown reasons
    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        print(f"\n{'='*80}")
        print(f"[SHUTDOWN] Received signal: {sig_name} ({signum})")
        print(f"[SHUTDOWN] Frame: {frame}")
        print(f"[SHUTDOWN] Initiating graceful shutdown...")
        print(f"{'='*80}\n")
        # Let uvicorn handle the actual shutdown
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    print(f"[STARTUP] Signal handlers registered (SIGTERM, SIGINT)")
    print(f"[STARTUP] Process PID: {os.getpid()}")
    
    # Clean old session directories on startup to prevent disk bloat
    print("[STARTUP] Cleaning old session directories...")
    for profile in PROFILES:
        try:
            clean_old_session_dirs(str(profile), keep_recent=2)
        except Exception as e:
            print(f"[STARTUP] Failed to clean sessions in {profile}: {e}")
    
    threading.Thread(target=_warmup_sync, name="warmup", daemon=True).start()
    # Watchdog disabled - causes race conditions and kills active searches
    print("[STARTUP] Watchdog disabled - browser health checked on-demand during /search")


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Log shutdown event."""
    print(f"\n{'='*80}")
    print(f"[SHUTDOWN] FastAPI shutdown event triggered")
    print(f"[SHUTDOWN] Process PID: {os.getpid()}")
    print(f"[SHUTDOWN] Total requests processed: {REQUEST_COUNT_TOTAL}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    import uvicorn
    
    # Start separate health check server FIRST (always responsive)
    health_server = start_health_server(port=4102)
    
    print(f"[MAIN] Starting uvicorn server on port {PORT}")
    print(f"[MAIN] Process PID: {os.getpid()}")
    print(f"[MAIN] Blocking operations will run in thread pool to keep event loop responsive")
    try:
        # Single worker with async event loop
        # Blocking Selenium operations run in thread pool via run_in_executor
        uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
    except KeyboardInterrupt:
        print(f"\n[MAIN] KeyboardInterrupt received, exiting...")
    except Exception as e:
        print(f"\n[MAIN] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"[MAIN] Shutting down health server...")
        health_server.shutdown()
        print(f"[MAIN] Uvicorn server stopped")
