#!/usr/bin/env python3
# comments: English only
"""Proxy Coordinator Server - centralized proxy rotation management.

This server manages proxy rotation for all browser workers:
- Tracks request count across all workers
- Triggers proxy rotation when threshold reached
- Handles proxy blocking events
- Provides API for workers to get current proxy
"""
import os
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import httpx

# ---------- CONFIG ----------
PORT = int(os.environ.get("COORDINATOR_PORT", "4200"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
PROXY_ROTATION_REQUESTS = int(os.environ.get("PROXY_ROTATION_REQUESTS", "0"))
PROXY_BLOCK_TIMEOUT_SEC = int(os.environ.get("PROXY_BLOCK_TIMEOUT_SEC", "300"))

# Parse PROXY_LIST
_proxy_list_env = os.environ.get("PROXY_LIST", "")
PROXY_LIST = []
if _proxy_list_env:
    for entry in _proxy_list_env.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "://" not in entry:
            entry = f"http://{entry}"
        PROXY_LIST.append(entry)

# Parse WORKER_BASE_URLS
_worker_urls_env = os.environ.get("WORKER_BASE_URLS", "")
WORKER_URLS = []
if _worker_urls_env:
    WORKER_URLS = [url.strip() for url in _worker_urls_env.split(",") if url.strip()]

# ---------- REDIS ----------
redis_client = redis.from_url(REDIS_URL, decode_responses=True)
print(f"[COORDINATOR] Connected to Redis: {REDIS_URL}")

# Redis keys
REDIS_PROXY_IDX_KEY = "browser_worker:shared_proxy_idx"
REDIS_REQUEST_COUNT_KEY = "browser_worker:shared_request_count"
REDIS_PROXY_BLOCKED_PREFIX = "browser_worker:proxy_blocked:"

# ---------- STATE ----------
rotation_enabled = PROXY_ROTATION_REQUESTS > 0 and len(PROXY_LIST) > 1

# ---------- API ----------
app = FastAPI()


class IncrementRequest(BaseModel):
    """Request to increment request counter."""
    pass


class BlockProxyRequest(BaseModel):
    """Request to block a proxy."""
    proxy_idx: int
    reason: str = "blocked"


class RotateProxyRequest(BaseModel):
    """Request to force proxy rotation."""
    reason: str = "manual"


# ---------- HELPER FUNCTIONS ----------

def get_current_proxy_idx() -> int:
    """Get current proxy index from Redis."""
    try:
        idx_str = redis_client.get(REDIS_PROXY_IDX_KEY)
        if idx_str is None:
            redis_client.set(REDIS_PROXY_IDX_KEY, "0")
            return 0
        return int(idx_str)
    except Exception as e:
        print(f"[ERROR] Failed to get proxy index: {e}")
        return 0


def get_request_count() -> int:
    """Get current request count from Redis."""
    try:
        count_str = redis_client.get(REDIS_REQUEST_COUNT_KEY)
        if count_str is None:
            redis_client.set(REDIS_REQUEST_COUNT_KEY, "0")
            return 0
        return int(count_str)
    except Exception as e:
        print(f"[ERROR] Failed to get request count: {e}")
        return 0


def is_proxy_blocked(proxy_idx: int) -> bool:
    """Check if proxy is blocked."""
    try:
        key = f"{REDIS_PROXY_BLOCKED_PREFIX}{proxy_idx}"
        return bool(redis_client.exists(key))
    except Exception as e:
        print(f"[ERROR] Failed to check proxy block: {e}")
        return False


def get_next_available_proxy_idx(start_idx: int) -> Optional[int]:
    """Get next available (non-blocked) proxy index."""
    if not PROXY_LIST:
        return None
    
    for offset in range(len(PROXY_LIST)):
        idx = (start_idx + offset) % len(PROXY_LIST)
        if not is_proxy_blocked(idx):
            return idx
    
    # All proxies blocked
    return None


def mark_proxy_blocked(proxy_idx: int, reason: str = "blocked") -> None:
    """Mark proxy as blocked with TTL."""
    try:
        key = f"{REDIS_PROXY_BLOCKED_PREFIX}{proxy_idx}"
        redis_client.setex(key, PROXY_BLOCK_TIMEOUT_SEC, "1")
        print(f"[COORDINATOR] Marked proxy {proxy_idx} as blocked for {PROXY_BLOCK_TIMEOUT_SEC}s (reason: {reason})")
    except Exception as e:
        print(f"[ERROR] Failed to mark proxy as blocked: {e}")


def increment_proxy_idx() -> int:
    """Increment proxy index and return new value."""
    try:
        new_idx = redis_client.incr(REDIS_PROXY_IDX_KEY)
        print(f"[COORDINATOR] Incremented proxy index to {new_idx}")
        return new_idx
    except Exception as e:
        print(f"[ERROR] Failed to increment proxy index: {e}")
        return get_current_proxy_idx()


def reset_request_count() -> None:
    """Reset request counter to 0."""
    try:
        redis_client.set(REDIS_REQUEST_COUNT_KEY, "0")
        print(f"[COORDINATOR] Reset request count to 0")
    except Exception as e:
        print(f"[ERROR] Failed to reset request count: {e}")


async def notify_workers_rotate_proxy(reason: str = "coordinator") -> Dict[str, bool]:
    """Notify all workers to rotate proxy.
    
    Returns:
        Dict mapping worker URL to success status
    """
    results = {}
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for worker_url in WORKER_URLS:
            try:
                response = await client.post(
                    f"{worker_url}/rotate-proxy",
                    json={"reason": reason}
                )
                success = response.status_code == 200
                results[worker_url] = success
                
                if success:
                    print(f"[COORDINATOR] Worker {worker_url} rotated proxy")
                else:
                    print(f"[COORDINATOR] Worker {worker_url} failed to rotate: {response.status_code}")
                    
            except Exception as e:
                print(f"[COORDINATOR] Failed to notify worker {worker_url}: {e}")
                results[worker_url] = False
    
    return results


# ---------- API ENDPOINTS ----------

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "ok": True,
        "proxy_count": len(PROXY_LIST),
        "worker_count": len(WORKER_URLS),
        "rotation_enabled": rotation_enabled,
        "current_proxy_idx": get_current_proxy_idx(),
        "request_count": get_request_count()
    }


@app.get("/status")
async def status():
    """Get current coordinator status."""
    current_idx = get_current_proxy_idx()
    request_count = get_request_count()
    
    # Check which proxies are blocked
    blocked_proxies = []
    available_proxies = []
    
    for idx in range(len(PROXY_LIST)):
        if is_proxy_blocked(idx):
            blocked_proxies.append(idx)
        else:
            available_proxies.append(idx)
    
    return {
        "proxy_list": PROXY_LIST,
        "current_proxy_idx": current_idx,
        "current_proxy": PROXY_LIST[current_idx % len(PROXY_LIST)] if PROXY_LIST else None,
        "request_count": request_count,
        "rotation_threshold": PROXY_ROTATION_REQUESTS,
        "rotation_enabled": rotation_enabled,
        "blocked_proxies": blocked_proxies,
        "available_proxies": available_proxies,
        "workers": WORKER_URLS
    }


@app.post("/increment-request")
async def increment_request(request: IncrementRequest):
    """Increment request counter and trigger rotation if threshold reached.
    
    This should be called by workers after each successful request.
    """
    if not rotation_enabled:
        return {
            "ok": True,
            "count": 0,
            "rotated": False,
            "message": "Rotation disabled"
        }
    
    # Increment counter (atomic)
    new_count = redis_client.incr(REDIS_REQUEST_COUNT_KEY)
    
    print(f"[COORDINATOR] Request count: {new_count}/{PROXY_ROTATION_REQUESTS}")
    
    # Check if threshold reached
    # Use EXACT match to prevent multiple rotations when count > threshold
    if new_count == PROXY_ROTATION_REQUESTS:
        print(f"\n{'='*80}")
        print(f"[COORDINATOR] ROTATION THRESHOLD REACHED: {new_count}/{PROXY_ROTATION_REQUESTS}")
        print(f"[COORDINATOR] Triggering proxy rotation for ALL workers")
        print(f"{'='*80}\n")
        
        # Get current proxy index before rotation
        old_idx = get_current_proxy_idx()
        
        # NOTE: Do NOT mark proxy as blocked on rotation threshold
        # The proxy is not blocked, just reached request limit
        # Only mark as blocked when worker reports actual proxy block
        
        # Increment proxy index
        new_idx = increment_proxy_idx()
        
        # Reset counter
        reset_request_count()
        
        # Notify all workers to rotate
        worker_results = await notify_workers_rotate_proxy("threshold reached")
        
        success_count = sum(1 for success in worker_results.values() if success)
        
        print(f"[COORDINATOR] Rotation complete: {success_count}/{len(WORKER_URLS)} workers rotated")
        
        return {
            "ok": True,
            "count": 0,  # Reset to 0
            "rotated": True,
            "old_proxy_idx": old_idx,
            "new_proxy_idx": new_idx,
            "workers_notified": len(worker_results),
            "workers_success": success_count,
            "worker_results": worker_results
        }
    
    return {
        "ok": True,
        "count": new_count,
        "rotated": False
    }


@app.post("/block-proxy")
async def block_proxy(request: BlockProxyRequest):
    """Mark a proxy as blocked and trigger rotation for all workers.
    
    This should be called when a worker detects proxy block.
    """
    proxy_idx = request.proxy_idx
    reason = request.reason
    
    if proxy_idx < 0 or proxy_idx >= len(PROXY_LIST):
        raise HTTPException(status_code=400, detail=f"Invalid proxy index: {proxy_idx}")
    
    print(f"\n{'='*80}")
    print(f"[COORDINATOR] PROXY BLOCK DETECTED")
    print(f"[COORDINATOR] Proxy index: {proxy_idx}")
    print(f"[COORDINATOR] Reason: {reason}")
    print(f"{'='*80}\n")
    
    # Mark proxy as blocked
    mark_proxy_blocked(proxy_idx, reason)
    
    # Check if we need to rotate (if current proxy is the blocked one)
    current_idx = get_current_proxy_idx()
    current_proxy_idx = current_idx % len(PROXY_LIST)
    
    if current_proxy_idx == proxy_idx:
        print(f"[COORDINATOR] Current proxy is blocked, triggering rotation")
        
        # Increment proxy index
        new_idx = increment_proxy_idx()
        
        # Notify all workers
        worker_results = await notify_workers_rotate_proxy(f"proxy {proxy_idx} blocked")
        
        success_count = sum(1 for success in worker_results.values() if success)
        
        print(f"[COORDINATOR] Rotation complete: {success_count}/{len(WORKER_URLS)} workers rotated")
        
        return {
            "ok": True,
            "blocked": True,
            "rotated": True,
            "old_proxy_idx": current_idx,
            "new_proxy_idx": new_idx,
            "workers_notified": len(worker_results),
            "workers_success": success_count
        }
    else:
        print(f"[COORDINATOR] Blocked proxy is not current, no rotation needed")
        
        return {
            "ok": True,
            "blocked": True,
            "rotated": False,
            "current_proxy_idx": current_idx
        }


@app.post("/rotate-proxy")
async def rotate_proxy(request: RotateProxyRequest):
    """Force proxy rotation for all workers.
    
    This can be called manually or by external systems.
    """
    reason = request.reason
    
    print(f"\n{'='*80}")
    print(f"[COORDINATOR] MANUAL PROXY ROTATION")
    print(f"[COORDINATOR] Reason: {reason}")
    print(f"{'='*80}\n")
    
    # Get current proxy index
    old_idx = get_current_proxy_idx()
    
    # Increment proxy index
    new_idx = increment_proxy_idx()
    
    # Notify all workers
    worker_results = await notify_workers_rotate_proxy(reason)
    
    success_count = sum(1 for success in worker_results.values() if success)
    
    print(f"[COORDINATOR] Rotation complete: {success_count}/{len(WORKER_URLS)} workers rotated")
    
    return {
        "ok": True,
        "rotated": True,
        "old_proxy_idx": old_idx,
        "new_proxy_idx": new_idx,
        "workers_notified": len(worker_results),
        "workers_success": success_count,
        "worker_results": worker_results
    }


@app.get("/current-proxy")
async def current_proxy():
    """Get current proxy information."""
    if not PROXY_LIST:
        return {
            "ok": False,
            "error": "No proxies configured"
        }
    
    current_idx = get_current_proxy_idx()
    proxy_idx = current_idx % len(PROXY_LIST)
    proxy_url = PROXY_LIST[proxy_idx]
    
    # Check if available
    available_idx = get_next_available_proxy_idx(proxy_idx)
    
    return {
        "ok": True,
        "proxy_idx": proxy_idx,
        "proxy_url": proxy_url,
        "shared_idx": current_idx,
        "is_blocked": is_proxy_blocked(proxy_idx),
        "next_available_idx": available_idx,
        "request_count": get_request_count()
    }


# ---------- STARTUP ----------

@app.on_event("startup")
async def startup():
    """Initialize coordinator on startup."""
    print(f"\n{'='*80}")
    print(f"[COORDINATOR] Starting Proxy Coordinator Server")
    print(f"[COORDINATOR] Port: {PORT}")
    print(f"[COORDINATOR] Redis: {REDIS_URL}")
    print(f"[COORDINATOR] Proxies: {len(PROXY_LIST)}")
    print(f"[COORDINATOR] Workers: {len(WORKER_URLS)}")
    print(f"[COORDINATOR] Rotation threshold: {PROXY_ROTATION_REQUESTS}")
    print(f"[COORDINATOR] Rotation enabled: {rotation_enabled}")
    print(f"{'='*80}\n")
    
    # Initialize Redis keys if not exist
    if redis_client.get(REDIS_PROXY_IDX_KEY) is None:
        redis_client.set(REDIS_PROXY_IDX_KEY, "0")
        print(f"[COORDINATOR] Initialized proxy index to 0")
    
    if redis_client.get(REDIS_REQUEST_COUNT_KEY) is None:
        redis_client.set(REDIS_REQUEST_COUNT_KEY, "0")
        print(f"[COORDINATOR] Initialized request count to 0")


# ---------- MAIN ----------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
