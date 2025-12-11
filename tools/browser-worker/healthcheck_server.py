#!/usr/bin/env python3
"""
Separate lightweight HTTP server for health checks.
Runs in a separate thread and ALWAYS responds immediately,
independent of main FastAPI server state.
"""
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import psutil


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks."""
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
    
    def do_GET(self):
        """Handle GET requests to /health-simple endpoint."""
        if self.path != '/health-simple':
            self.send_error(404)
            return
        
        try:
            # Quick check: Chrome processes exist AND are not zombies
            chrome_alive = False
            chrome_count = 0
            zombie_count = 0
            
            for proc in psutil.process_iter(['name', 'status']):
                try:
                    name = proc.info['name'].lower()
                    status = proc.info.get('status', '')
                    # Check for actual chromium browser process (not chromedriver)
                    # chromedriver has 'chromedriver' in name, browser has 'chromium' or 'chrome'
                    is_browser = ('chromium' in name or 'chrome' in name) and 'driver' not in name
                    if is_browser:
                        chrome_count += 1
                        # Check if process is zombie/defunct
                        if status in ['zombie', 'dead'] or status == psutil.STATUS_ZOMBIE:
                            zombie_count += 1
                        else:
                            chrome_alive = True  # At least one live browser process
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Return status - only OK if we have at least one LIVE (non-zombie) browser process
            response = {
                "ok": chrome_alive,
                "chrome_processes": chrome_count,
                "zombie_processes": zombie_count,
                "live_processes": chrome_count - zombie_count,
                "pid": os.getpid()
            }
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            
        except Exception as e:
            error_response = {
                "ok": False,
                "error": str(e)
            }
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(error_response).encode())


def start_health_server(port=4102):
    """Start health check server in a separate thread."""
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    
    def run_server():
        print(f"[HEALTH SERVER] Starting on port {port}")
        print(f"[HEALTH SERVER] Endpoint: http://0.0.0.0:{port}/health-simple")
        server.serve_forever()
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    print(f"[HEALTH SERVER] Started in background thread")
    return server


if __name__ == "__main__":
    # For testing standalone
    server = start_health_server()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[HEALTH SERVER] Shutting down...")
        server.shutdown()
