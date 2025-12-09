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
            # Quick check: Chrome processes exist
            chrome_alive = False
            chrome_count = 0
            
            for proc in psutil.process_iter(['name']):
                try:
                    name = proc.info['name'].lower()
                    if 'chromium' in name or 'chrome' in name:
                        chrome_alive = True
                        chrome_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Return status
            response = {
                "ok": chrome_alive,
                "chrome_processes": chrome_count,
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
