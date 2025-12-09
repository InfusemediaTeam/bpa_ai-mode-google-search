#!/usr/bin/env python3
"""
Worker health monitor service - runs in dedicated container.
Monitors all browser workers and restarts unhealthy containers.
"""
import os
import time
import logging
import schedule
import docker
import requests
from datetime import datetime
from flask import Flask, jsonify

# Configuration - check ACTUAL state frequently
CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', '15'))  # Check every 15s
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
DOCKER_SOCKET = os.environ.get('DOCKER_SOCKET', '/var/run/docker.sock')
MAX_RESTART_ATTEMPTS = int(os.environ.get('MAX_RESTART_ATTEMPTS', '3'))

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='[MONITOR] %(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Flask app for health endpoint
app = Flask(__name__)

# Docker client
docker_client = docker.from_env()

# Stats tracking
stats = {
    'last_check': None,
    'total_checks': 0,
    'failed_checks': 0,
    'restarts_performed': 0,
    'healthy_workers': [],
    'unhealthy_workers': []
}

def check_worker_health(container):
    """Check ACTUAL state of worker - no timeouts, just facts."""
    try:
        container_name = container.name
        logger.debug(f"Checking health of {container_name}")
        
        # Fact 1: Container must be running
        container.reload()
        container_state = container.attrs.get('State', {})
        
        if not container_state.get('Running'):
            logger.warning(f"{container_name} is not running")
            return False
        
        if container_state.get('Restarting'):
            logger.info(f"{container_name} is restarting (healthy)")
            return True  # Restarting = healthy
        
        # Fact 2: Check Docker healthcheck result (if available)
        docker_health = container.attrs.get('State', {}).get('Health', {}).get('Status')
        if docker_health:
            is_healthy = docker_health in ['healthy', 'starting']
            if is_healthy:
                logger.debug(f"{container_name} Docker health: {docker_health}")
                return True
            else:
                logger.warning(f"{container_name} Docker health: {docker_health}")
                return False
        
        # Fact 3: If no Docker health, check HTTP endpoint quickly
        try:
            networks = container.attrs['NetworkSettings']['Networks']
            container_ip = None
            for network_name, network_info in networks.items():
                if 'app_net' in network_name:
                    container_ip = network_info['IPAddress']
                    break
            
            if not container_ip:
                logger.warning(f"Could not get IP for {container_name}")
                return False
            
            # Quick check (2s) - if server responds, parse result
            response = requests.get(
                f"http://{container_ip}:4101/health",
                timeout=2
            )
            
            if response.status_code != 200:
                logger.warning(f"Health endpoint returned {response.status_code} for {container_name}")
                return False
            
            data = response.json()
            ok = data.get('ok', False)
            
            if not ok:
                logger.warning(f"{container_name} reports not ok: {data}")
            else:
                logger.debug(f"{container_name} is healthy")
            
            return ok
                
        except requests.exceptions.Timeout:
            logger.warning(f"Health endpoint timeout for {container_name}")
            return False
        except Exception as e:
            logger.warning(f"Health check failed for {container_name}: {e}")
            return False
        
    except Exception as e:
        logger.error(f"Error checking {container.name}: {e}")
        return False

def restart_worker(container, client):
    """Restart unhealthy worker and wait for ACTUAL healthy state."""
    container_name = container.name
    logger.info(f"Restarting unhealthy worker: {container_name}")
    
    try:
        # Stop the container
        logger.info(f"Stopping {container_name}...")
        container.stop(timeout=10)
        
        # Start it again
        logger.info(f"Starting {container_name}...")
        container.start()
        
        # Wait for ACTUAL healthy state - check frequently, stop when healthy
        max_attempts = 30  # 30 attempts = ~60s max wait
        check_delay = 2    # Check every 2 seconds
        
        logger.info(f"Waiting for {container_name} to report healthy state...")
        
        for attempt in range(1, max_attempts + 1):
            time.sleep(check_delay)
            container.reload()
            
            # Fact: container must be running
            if not container.attrs.get('State', {}).get('Running'):
                logger.debug(f"{container_name} not running yet (attempt {attempt})")
                continue
            
            # Fact: check health immediately
            if check_worker_health(container):
                elapsed = attempt * check_delay
                logger.info(f"{container_name} is healthy after {elapsed}s")
                return True
            
            logger.debug(f"{container_name} not healthy yet (attempt {attempt})")
        
        total_wait = max_attempts * check_delay
        logger.error(f"{container_name} did not become healthy after {total_wait}s")
        return False
        
    except Exception as e:
        logger.error(f"Error restarting {container_name}: {e}")
        return False

def monitor_all_workers():
    """Check all browser workers and restart unhealthy ones."""
    logger.info("Starting worker health check cycle")
    stats['total_checks'] += 1
    stats['last_check'] = datetime.now().isoformat()
    
    healthy_workers = []
    unhealthy_workers = []
    
    try:
        # Get all browser worker containers
        containers = docker_client.containers.list(
            filters={"name": "google-search-ai-browser-worker"}
        )
        
        if not containers:
            logger.warning("No browser worker containers found")
            return
            
        logger.info(f"Found {len(containers)} worker containers")
        
        # Check each worker
        for container in containers:
            if check_worker_health(container):
                healthy_workers.append(container.name)
            else:
                unhealthy_workers.append(container.name)
                stats['failed_checks'] += 1
                
                # Attempt restart
                if restart_worker(container, docker_client):
                    healthy_workers.append(container.name)
                    unhealthy_workers.remove(container.name)
        
        # Update stats
        stats['healthy_workers'] = healthy_workers
        stats['unhealthy_workers'] = unhealthy_workers
        
        logger.info(f"Health check complete: {len(healthy_workers)} healthy, {len(unhealthy_workers)} unhealthy")
        
    except Exception as e:
        logger.error(f"Error during monitoring cycle: {e}")
        stats['failed_checks'] += 1

# Flask routes
@app.route('/health')
def health():
    """Health endpoint for the monitor service itself."""
    return jsonify({
        'status': 'healthy',
        'service': 'worker-monitor',
        'last_check': stats['last_check'],
        'uptime': time.time()
    })

@app.route('/stats')
def get_stats():
    """Get monitoring statistics."""
    return jsonify(stats)

@app.route('/check')
def manual_check():
    """Trigger manual health check."""
    monitor_all_workers()
    return jsonify({
        'status': 'check_completed',
        'timestamp': datetime.now().isoformat()
    })

def run_scheduler():
    """Run the scheduled monitoring in a separate thread."""
    schedule.every(CHECK_INTERVAL).seconds.do(monitor_all_workers)
    
    logger.info(f"Starting worker monitor scheduler (interval: {CHECK_INTERVAL}s)")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    import threading
    
    logger.info("Starting Worker Health Monitor Service")
    
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=8080, debug=False)