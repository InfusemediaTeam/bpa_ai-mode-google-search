#!/usr/bin/env python3
"""
Health check script for browser worker.
MUST respond quickly (< 2 seconds) regardless of worker state.
"""
import sys
import http.client
import json
import psutil

def check_server_responding():
    """Check if lightweight health server responds.
    
    Uses separate health server (port 4102) that ALWAYS responds
    even when main FastAPI server is busy with search operations.
    This prevents false positives during long searches.
    """
    try:
        # Try lightweight health server first (always responsive)
        conn = http.client.HTTPConnection('localhost', 4102, timeout=2)
        conn.request('GET', '/health-simple')
        response = conn.getresponse()
        
        if response.status != 200:
            print(f"[HEALTHCHECK] Health server returned {response.status}")
            return False
        
        data = json.loads(response.read().decode())
        conn.close()
        
        # Health server checks Chrome processes
        if not data.get('ok', False):
            print(f"[HEALTHCHECK] Health server not ok: {data}")
            return False
        
        return True
        
    except Exception as e:
        print(f"[HEALTHCHECK] Health server check failed: {e}")
        # Fallback: try main server (may timeout during search)
        try:
            conn = http.client.HTTPConnection('localhost', 4101, timeout=2)
            conn.request('GET', '/health')
            response = conn.getresponse()
            
            if response.status != 200:
                return False
            
            data = json.loads(response.read().decode())
            conn.close()
            return data.get('ok', False)
        except Exception:
            return False

def check_chrome_alive():
    """Quick check if Chrome processes exist (not zombie)."""
    try:
        chrome_count = 0
        zombie_count = 0
        
        for proc in psutil.process_iter(['name', 'status']):
            try:
                name = proc.info['name'].lower()
                if 'chromium' in name or 'chrome' in name:
                    chrome_count += 1
                    if proc.info['status'] in ['zombie', 'dead']:
                        zombie_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Need at least 1 Chrome process (relaxed from 2)
        if chrome_count < 1:
            print(f"[HEALTHCHECK] No Chrome processes found")
            return False
        
        # Zombie processes are OK if there are enough live processes
        if zombie_count > 0 and chrome_count - zombie_count < 1:
            print(f"[HEALTHCHECK] Only zombie Chrome processes ({zombie_count})")
            return False
        
        return True
        
    except Exception as e:
        print(f"[HEALTHCHECK] Chrome check failed: {e}")
        return False

def main():
    """Run minimal health checks - optimized for speed (< 2 seconds)."""
    # Check 1: Chrome processes must be alive
    if not check_chrome_alive():
        print("[HEALTHCHECK] FAIL: Chrome not healthy")
        sys.exit(1)
    
    # Check 2: Server must respond quickly
    if not check_server_responding():
        print("[HEALTHCHECK] FAIL: Server not responding")
        sys.exit(1)
    
    print("[HEALTHCHECK] PASS")
    sys.exit(0)

if __name__ == "__main__":
    main()