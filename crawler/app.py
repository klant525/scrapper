import os
import time
import csv
import random
import tempfile
import shutil
import socket
import asyncio
import uuid
import gc
import psutil
import gzip
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import queue
import threading
import json
import hashlib
from functools import wraps, lru_cache
from io import StringIO

from flask import Flask, render_template, request, jsonify, send_file, Response, session
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import platform
import requests
from urllib.parse import quote_plus
import re
from collections import defaultdict, OrderedDict
num_results = request.form.get("num_results")


BASE_DIR = os.path.dirname(__file__)
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# -------------------- Enhanced Configuration --------------------
class Config:
    MAX_CONCURRENT_TASKS = 5
    MAX_DRIVERS_POOL = 3
    TASK_TIMEOUT = 300
    DRIVER_REUSE_LIMIT = 10
    RATE_LIMIT_WINDOW = 60
    RATE_LIMIT_MAX = 5
    
    MEMORY_THRESHOLD = 80
    CACHE_TTL = 3600
    BATCH_SIZE = 5
    COMPRESSION_THRESHOLD = 1024
    GC_INTERVAL = 300
    MAX_CACHE_SIZE = 100
    GPS_SEARCH_RADIUS = 50000  # 50km radius for GPS-based search
    SESSION_DEDUP_EXPIRY = 3600  # 1 hour for session deduplication
    MAX_RESULTS_PER_REQUEST = 100
    STREAM_CHUNK_SIZE = 5  # Stream results in chunks of 5

# -------------------- Session-based Deduplication Manager --------------------
class SessionDeduplicationManager:
    def __init__(self):
        self.session_results: Dict[str, Dict[str, Set[str]]] = {}
        self.session_timestamps: Dict[str, datetime] = {}
        self.lock = Lock()
    
    def get_session_id(self):
        """Get or create session ID"""
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        return session['session_id']
    
    def add_results(self, session_id: str, search_key: str, results: List[str]):
        """Add results to session deduplication cache"""
        with self.lock:
            if session_id not in self.session_results:
                self.session_results[session_id] = {}
                self.session_timestamps[session_id] = datetime.now()
            
            if search_key not in self.session_results[session_id]:
                self.session_results[session_id][search_key] = set()
            
            # Add place names to deduplication set
            for result in results:
                if isinstance(result, dict) and 'Tên địa điểm' in result:
                    self.session_results[session_id][search_key].add(result['Tên địa điểm'])
    
    def filter_duplicates(self, session_id: str, search_key: str, results: List[dict]) -> List[dict]:
        """Filter out duplicate results for the same search key in session"""
        with self.lock:
            if (session_id not in self.session_results or 
                search_key not in self.session_results[session_id]):
                return results
            
            seen_places = self.session_results[session_id][search_key]
            filtered_results = []
            
            for result in results:
                place_name = result.get('Tên địa điểm', '')
                if place_name and place_name not in seen_places:
                    filtered_results.append(result)
                    seen_places.add(place_name)
            
            return filtered_results
    
    def cleanup_expired_sessions(self):
        """Remove expired session data"""
        cutoff = datetime.now() - timedelta(seconds=Config.SESSION_DEDUP_EXPIRY)
        with self.lock:
            expired_sessions = [
                sid for sid, timestamp in self.session_timestamps.items()
                if timestamp < cutoff
            ]
            for sid in expired_sessions:
                self.session_results.pop(sid, None)
                self.session_timestamps.pop(sid, None)

# -------------------- Memory & Performance Monitoring --------------------
class PerformanceMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        self.error_count = 0
        self.lock = Lock()
    
    def record_request(self, success=True):
        with self.lock:
            self.request_count += 1
            if not success:
                self.error_count += 1
    
    def get_memory_usage(self):
        """Lấy thông tin sử dụng bộ nhớ"""
        process = psutil.Process()
        memory_info = process.memory_info()
        return {
            'rss': memory_info.rss / 1024 / 1024,  # MB
            'vms': memory_info.vms / 1024 / 1024,  # MB
            'percent': process.memory_percent()
        }
    
    def should_trigger_gc(self):
        """Kiểm tra có nên chạy garbage collection không"""
        memory = self.get_memory_usage()
        return memory['percent'] > Config.MEMORY_THRESHOLD
    
    def get_stats(self):
        uptime = time.time() - self.start_time
        return {
            'uptime': uptime,
            'requests': self.request_count,
            'errors': self.error_count,
            'error_rate': self.error_count / max(self.request_count, 1),
            'memory': self.get_memory_usage()
        }

# -------------------- Enhanced Caching System --------------------
class InMemoryCache:
    def __init__(self, max_size=Config.MAX_CACHE_SIZE):
        self.cache = {}
        self.access_times = {}
        self.max_size = max_size
        self.lock = Lock()
    
    def _evict_lru(self):
        """Xóa cache ít được sử dụng nhất"""
        if len(self.cache) >= self.max_size:
            lru_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[lru_key]
            del self.access_times[lru_key]
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                data, expiry = self.cache[key]
                if time.time() < expiry:
                    self.access_times[key] = time.time()
                    return data
                else:
                    del self.cache[key]
                    del self.access_times[key]
            return None
    
    def set(self, key, value, ttl=Config.CACHE_TTL):
        with self.lock:
            self._evict_lru()
            expiry = time.time() + ttl
            self.cache[key] = (value, expiry)
            self.access_times[key] = time.time()
    
    def clear_expired(self):
        """Xóa cache hết hạn"""
        current_time = time.time()
        with self.lock:
            expired_keys = [
                key for key, (_, expiry) in self.cache.items() 
                if current_time >= expiry
            ]
            for key in expired_keys:
                del self.cache[key]
                del self.access_times[key]

# -------------------- Response Compression --------------------
def gzip_response(f):
    """Decorator để nén response"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = f(*args, **kwargs)
        
        # Chỉ nén nếu client hỗ trợ và response đủ lớn
        if (request.headers.get('Accept-Encoding', '').find('gzip') != -1 and
            hasattr(response, 'data') and 
            len(response.data) > Config.COMPRESSION_THRESHOLD):
            
            compressed_data = gzip.compress(response.data)
            response.data = compressed_data
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = len(compressed_data)
        
        return response
    return decorated_function

# -------------------- Enhanced Task Manager --------------------
class TaskManager:
    def __init__(self):
        self.active_tasks: Dict[str, dict] = {}
        self.task_queue = queue.Queue(maxsize=20)
        self.rate_limiter: Dict[str, List[datetime]] = {}
        self.lock = Lock()
        self.cache = InMemoryCache()
        self.dedup_manager = SessionDeduplicationManager()
        
    def add_task(self, task_id: str, task_data: dict):
        with self.lock:
            self.active_tasks[task_id] = {
                **task_data,
                'status': 'queued',
                'created_at': datetime.now(),
                'progress': 0,
                'results': [],
                'batch_progress': {},
                'gps_optimized': bool(task_data.get('lat') and task_data.get('lng')),
                'session_id': task_data.get('session_id')
            }
    
    def update_task(self, task_id: str, updates: dict):
        with self.lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].update(updates)
    
    def get_task(self, task_id: str) -> Optional[dict]:
        with self.lock:
            return self.active_tasks.get(task_id)
    
    def remove_task(self, task_id: str):
        with self.lock:
            self.active_tasks.pop(task_id, None)
    
    def check_rate_limit(self, client_ip: str) -> bool:
        now = datetime.now()
        with self.lock:
            if client_ip not in self.rate_limiter:
                self.rate_limiter[client_ip] = []
            
            cutoff = now - timedelta(seconds=Config.RATE_LIMIT_WINDOW)
            self.rate_limiter[client_ip] = [
                req_time for req_time in self.rate_limiter[client_ip] 
                if req_time > cutoff
            ]
            
            if len(self.rate_limiter[client_ip]) >= Config.RATE_LIMIT_MAX:
                return False
            
            self.rate_limiter[client_ip].append(now)
            return True
    
    def get_cached_result(self, search_key: str, num_results: int, lat: str = '', lng: str = '', session_id: str = '') -> Optional[dict]:
        cache_key = hashlib.md5(f"{search_key}_{num_results}_{lat}_{lng}".encode()).hexdigest()
        cached_data = self.cache.get(cache_key)
        
        return cached_data
    
    def cache_result(self, search_key: str, num_results: int, results: list, lat: str = '', lng: str = '', session_id: str = ''):
        cache_key = hashlib.md5(f"{search_key}_{num_results}_{lat}_{lng}".encode()).hexdigest()
        self.cache.set(cache_key, results)

# -------------------- Optimized Driver Pool --------------------
class DriverPool:
    def __init__(self, max_drivers=Config.MAX_DRIVERS_POOL):
        self.max_drivers = max_drivers
        self.available_drivers = queue.Queue()
        self.busy_drivers = set()
        self.driver_usage = {}
        self.driver_performance = {}  # Theo dõi hiệu suất driver
        self.lock = Lock()
        self._initialize_pool()
    
    def _initialize_pool(self):
        for _ in range(min(2, self.max_drivers)):
            try:
                driver, profile = self._create_driver()
                self.available_drivers.put((driver, profile))
            except Exception as e:
                print(f"Lỗi khởi tạo driver pool: {e}")
    
    def _create_driver(self):
        if platform.system() == "Windows":
            chrome_profile = tempfile.mkdtemp(prefix="chrome-profile-")
        else:
            chrome_profile = tempfile.mkdtemp(dir="/tmp", prefix="chrome-profile-")
        
        opts = webdriver.ChromeOptions()
        
        performance_opts = [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--disable-web-security',
            '--allow-running-insecure-content',
            '--disable-gpu',
            '--headless=new',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            '--disable-background-networking',
            '--disable-sync',
            '--disable-default-apps',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-images',
            '--disable-javascript',
            '--memory-pressure-off',
            '--max_old_space_size=2048',
            '--disable-logging',
            '--disable-gpu-logging',
            '--silent'
        ]
        
        for opt in performance_opts:
            opts.add_argument(opt)
            
        opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        opts.add_experimental_option('useAutomationExtension', False)
        opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        opts.add_argument('--window-size=1366,768')
        opts.add_argument(f'--user-data-dir={chrome_profile}')
        opts.add_argument('--profile-directory=Default')
        opts.add_argument(f'--remote-debugging-port={self._free_port()}')
        
        prefs = {
            "profile.default_content_setting_values": {
                "images": 2,
                "plugins": 2,
                "popups": 2,
                "geolocation": 2,
                "notifications": 2,
                "media_stream": 2,
            },
            "profile.managed_default_content_settings": {
                "images": 2
            }
        }
        opts.add_experimental_option("prefs", prefs)
        
        service_args = ['--silent', '--log-level=3']
        
        try:
            driver = webdriver.Chrome(options=opts)
            driver.set_window_size(1366, 768)
            driver.set_page_load_timeout(10)
            driver.implicitly_wait(2)
            return driver, chrome_profile
        except Exception as e:
            if os.path.exists(chrome_profile):
                shutil.rmtree(chrome_profile, ignore_errors=True)
            raise e
    
    def _free_port(self):
        s = socket.socket()
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        return port
    
    def get_driver(self, timeout=20):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                driver, profile = self.available_drivers.get_nowait()
                with self.lock:
                    driver_id = id(driver)
                    self.busy_drivers.add(driver_id)
                    usage_count = self.driver_usage.get(driver_id, 0)
                    
                    if usage_count >= Config.DRIVER_REUSE_LIMIT:
                        try:
                            driver.quit()
                        except:
                            pass
                        if os.path.exists(profile):
                            shutil.rmtree(profile, ignore_errors=True)
                        driver, profile = self._create_driver()
                        self.driver_usage[id(driver)] = 0
                    
                return driver, profile
                
            except queue.Empty:
                with self.lock:
                    if len(self.busy_drivers) < self.max_drivers:
                        try:
                            driver, profile = self._create_driver()
                            self.busy_drivers.add(id(driver))
                            self.driver_usage[id(driver)] = 0
                            return driver, profile
                        except Exception as e:
                            print(f"Lỗi tạo driver mới: {e}")
                
                time.sleep(0.3)
        
        raise Exception("Không thể lấy driver trong thời gian quy định")

    def return_driver(self, driver, profile):
        try:
            with self.lock:
                driver_id = id(driver)
                if driver_id in self.busy_drivers:
                    self.busy_drivers.remove(driver_id)
                    self.driver_usage[driver_id] = self.driver_usage.get(driver_id, 0) + 1
                    
                    try:
                        driver.delete_all_cookies()
                        driver.execute_script("window.localStorage.clear();")
                        driver.execute_script("window.sessionStorage.clear();")
                        self.available_drivers.put((driver, profile))
                    except Exception as e:
                        print(f"Lỗi khi trả driver về pool: {e}")
                        try:
                            driver.quit()
                        except:
                            pass
                        if os.path.exists(profile):
                            shutil.rmtree(profile, ignore_errors=True)
        except Exception as e:
            print(f"Lỗi trả driver: {e}")
            try:
                driver.quit()
            except:
                pass
            if os.path.exists(profile):
                shutil.rmtree(profile, ignore_errors=True)
    
    def cleanup(self):
        while not self.available_drivers.empty():
            try:
                driver, profile = self.available_drivers.get_nowait()
                driver.quit()
                shutil.rmtree(profile, ignore_errors=True)
            except:
                pass

# Global instances
task_manager = TaskManager()
driver_pool = DriverPool()
executor = ThreadPoolExecutor(max_workers=Config.MAX_CONCURRENT_TASKS)
performance_monitor = PerformanceMonitor()  # Thêm monitor

# -------------------- Helper Functions --------------------
async def run_in_executor(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args, **kwargs)

@lru_cache(maxsize=128)  # Cache kết quả xpath
def get_text_by_xpath(driver, xpath, default='Không có dữ liệu', timeout=3):
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        return element.text.strip() or default
    except (TimeoutException, NoSuchElementException):
        return default

def wait_for_results_to_load(driver, min_results=5, max_wait=10):
    start_time = time.time()
    while time.time() - start_time < max_wait:
        results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        if len(results) >= min_results:
            return True
        time.sleep(0.5)
    return False

def find_results_sidebar(driver):
    try:
        all_links = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        if all_links:
            first_link = all_links[0]
            current_element = first_link
            for level in range(10):
                try:
                    parent = current_element.find_element(By.XPATH, "./..")
                    scroll_height = driver.execute_script("return arguments[0].scrollHeight", parent)
                    client_height = driver.execute_script("return arguments[0].clientHeight", parent)
                    overflow_y = driver.execute_script("return window.getComputedStyle(arguments[0]).overflowY", parent)
                    
                    if (scroll_height > client_height and scroll_height > 100 and 
                        overflow_y in ['auto', 'scroll', 'overlay']):
                        return parent
                    current_element = parent
                except Exception:
                    break
    except Exception:
        pass

    selectors_to_try = [
        "[data-value='Search results']",
        "div[role='main']",
        ".m6QErb.DxyBCb.kA9KIf.dS8AEf",
        ".m6QErb",
        ".siAUzd.Tj2rMd",
        ".lXJj5c.Hk4XGb",
    ]
    for selector in selectors_to_try:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elements:
                scroll_height = driver.execute_script("return arguments[0].scrollHeight", elem)
                client_height = driver.execute_script("return arguments[0].clientHeight", elem)
                if scroll_height > client_height and scroll_height > 200:
                    return elem
        except:
            continue

    return driver.find_element(By.TAG_NAME, 'body')

def scroll_and_collect_places(driver, target_count, max_scrolls=50, progress_callback=None):
    places_urls = set()
    scroll_count = 0
    consecutive_no_new = 0

    if not wait_for_results_to_load(driver):
        return list(places_urls)

    scrollable_element = find_results_sidebar(driver)
    
    initial_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
    for link in initial_results:
        href = link.get_attribute('href')
        if href and 'maps/place' in href:
            places_urls.add(href)

    while len(places_urls) < target_count and scroll_count < max_scrolls:
        previous_count = len(places_urls)
        
        try:
            if scroll_count % 3 == 0:
                driver.execute_script("""
                    arguments[0].scrollTo({
                        top: arguments[0].scrollTop + 800,
                        behavior: 'smooth'
                    });
                """, scrollable_element)
                time.sleep(2)
            else:
                driver.execute_script("arguments[0].scrollTop += 800", scrollable_element)
                time.sleep(1)
        except Exception:
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(1)

        current_results = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
        for link in current_results:
            href = link.get_attribute('href')
            if href and 'maps/place' in href:
                places_urls.add(href)

        new_count = len(places_urls)
        
        if progress_callback:
            progress = min(100, (new_count / target_count) * 100)
            progress_callback(progress, new_count)

        if new_count == previous_count:
            consecutive_no_new += 1
            if consecutive_no_new >= 5:
                break
        else:
            consecutive_no_new = 0

        scroll_count += 1
        time.sleep(random.uniform(1, 2))

    return list(places_urls)[:target_count]

def extract_place_info_batch(driver, place_urls, progress_callback=None):
    """Xử lý nhiều địa điểm cùng lúc để tối ưu hóa"""
    results = []
    successful_extracts = 0
    
    for i, place_url in enumerate(place_urls):
        try:
            driver.get(place_url)
            time.sleep(random.uniform(0.5, 1))
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.TAG_NAME, 'h1')))

            name = get_text_by_xpath(driver, '//h1[@class="DUwDvf lfPIob"]', 'Không có tên')
            if name == 'Không có tên':
                name = get_text_by_xpath(driver, '//h1', 'Không có tên')

            address_selectors = [
                "//div[contains(@class, 'Io6YTe') and contains(@class,'fdkmkc')]",
                "//button[@data-item-id='address']//div[contains(@class, 'fontBodyMedium')]",
                "//div[contains(@class, 'rogA2c')]//div[2]",
            ]
            address = 'Không có địa chỉ'
            for selector in address_selectors:
                address = get_text_by_xpath(driver, selector, 'Không có địa chỉ')
                if address != 'Không có địa chỉ':
                    break

            phone_selectors = [
                "//button[contains(@data-item-id, 'phone')]//div[contains(@class, 'fontBodyMedium')]",
                "//button[contains(@data-item-id, 'phone')]",
                "//a[starts-with(@href, 'tel:')]",
            ]
            phone = 'Không có số điện thoại'
            for selector in phone_selectors:
                phone = get_text_by_xpath(driver, selector, 'Không có số điện thoại')
                if phone != 'Không có số điện thoại' and phone.strip():
                    break

            website_selectors = [
                "//a[contains(@data-item-id, 'authority')]",
                "//button[contains(@data-item-id, 'authority')]//div[contains(@class, 'fontBodyMedium')]",
                "//a[contains(@href, 'http') and not(contains(@href, 'google'))]",
            ]
            website = 'Không có website'
            for selector in website_selectors:
                element_text = get_text_by_xpath(driver, selector, 'Không có website')
                if element_text != 'Không có website' and 'http' in element_text:
                    website = element_text
                    break
                try:
                    elem = driver.find_element(By.XPATH, selector)
                    href = elem.get_attribute('href')
                    if href and 'http' in href and 'google' not in href:
                        website = href
                        break
                except:
                    continue

            result = {
                'Tên địa điểm': name,
                'Địa chỉ': address,
                'Số điện thoại': phone,
                'Website': website
            }
            results.append(result)
            
            if name != 'Lỗi lấy dữ liệu':
                successful_extracts += 1
                
        except Exception as e:
            results.append({
                'Tên địa điểm': 'Lỗi lấy dữ liệu',
                'Địa chỉ': 'Lỗi lấy dữ liệu',
                'Số điện thoại': 'Lỗi lấy dữ liệu',
                'Website': 'Lỗi lấy dữ liệu'
            })
        
        if progress_callback:
            progress = ((i + 1) / len(place_urls)) * 100
            progress_callback(progress, i + 1, successful_extracts)
        
        if i < len(place_urls) - 1:
            time.sleep(random.uniform(0.3, 0.8))
    
    return results, successful_extracts

# -------------------- GPS Optimization Functions --------------------
def build_gps_optimized_url(keyword: str, lat: float, lng: float) -> str:
    """Build GPS-optimized Google Maps search URL"""
    keyword_encoded = keyword.replace(' ', '+')
    # Use GPS coordinates with appropriate zoom level for local search
    return f'https://www.google.com/maps/search/{keyword_encoded}/@{lat},{lng},13z'

def validate_gps_coordinates(lat_str: str, lng_str: str) -> tuple:
    """Validate and convert GPS coordinates"""
    try:
        lat = float(lat_str.strip())
        lng = float(lng_str.strip())
        
        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            raise ValueError("Latitude must be between -90 and 90")
        if not (-180 <= lng <= 180):
            raise ValueError("Longitude must be between -180 and 180")
            
        return lat, lng
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid GPS coordinates: {e}")

# -------------------- Enhanced Task Processing --------------------
def process_scraping_task(task_id: str, search_params: dict):
    driver = None
    profile = None
    
    try:
        session_id = search_params.get('session_id', '')
        
        cached_result = task_manager.get_cached_result(
            search_params['search_key'],
            search_params['num_results'],
            search_params.get('lat', ''),
            search_params.get('lng', ''),
            session_id
        )
        
        if cached_result and session_id:
            original_count = len(cached_result)
            deduplicated_results = task_manager.dedup_manager.filter_duplicates(
                session_id, search_params['search_key'], cached_result
            )
            
            task_manager.dedup_manager.add_results(session_id, search_params['search_key'], deduplicated_results)
            
            task_manager.update_task(task_id, {
                'status': 'completed',
                'progress': 100,
                'results': deduplicated_results,
                'total_found': len(deduplicated_results),
                'successful_extracts': len(deduplicated_results),
                'from_cache': True,
                'deduplicated': True,
                'original_count': original_count,
                'deduplicated_count': len(deduplicated_results),
                'removed_duplicates': original_count - len(deduplicated_results)
            })
            return
        elif cached_result:
            task_manager.update_task(task_id, {
                'status': 'completed',
                'progress': 100,
                'results': cached_result,
                'total_found': len(cached_result),
                'successful_extracts': len(cached_result),
                'from_cache': True,
                'deduplicated': False
            })
            return

        driver, profile = driver_pool.get_driver()
        task_manager.update_task(task_id, {'status': 'running'})
        
        keyword = search_params['search_key']
        lat_str = search_params.get('lat', '').strip()
        lng_str = search_params.get('lng', '').strip()
        
        if lat_str and lng_str:
            try:
                lat, lng = validate_gps_coordinates(lat_str, lng_str)
                crawl_url = build_gps_optimized_url(keyword, lat, lng)
                task_manager.update_task(task_id, {'gps_optimized': True})
            except ValueError as e:
                # Fallback to regular search if GPS coordinates are invalid
                crawl_url = f'https://www.google.com/maps/search/{keyword.replace(" ", "+")}'
                task_manager.update_task(task_id, {'gps_error': str(e)})
        else:
            crawl_url = f'https://www.google.com/maps/search/{keyword.replace(" ", "+")}'

        driver.get(crawl_url)
        time.sleep(2)
        
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a.hfpxzc'))
            )
        except TimeoutException:
            pass

        def update_progress(progress, count):
            task_manager.update_task(task_id, {
                'progress': progress * 0.7,
                'current_count': count
            })

        places_urls = scroll_and_collect_places(
            driver, 
            search_params['num_results'],
            progress_callback=update_progress
        )
        
        if not places_urls:
            task_manager.update_task(task_id, {
                'status': 'failed',
                'error': 'Không tìm thấy kết quả nào'
            })
            return

        def extract_progress(progress, current, successful):
            total_progress = 70 + (progress * 0.3)
            task_manager.update_task(task_id, {
                'progress': total_progress,
                'current_extracted': current,
                'successful_extracts': successful
            })

        results, successful_extracts = extract_place_info_batch(
            driver, places_urls, extract_progress
        )

        if session_id:
            original_count = len(results)
            results = task_manager.dedup_manager.filter_duplicates(session_id, keyword, results)
            deduplicated_count = len(results)
            
            task_manager.dedup_manager.add_results(session_id, keyword, results)
            
            task_manager.update_task(task_id, {
                'deduplicated': True,
                'original_count': original_count,
                'deduplicated_count': deduplicated_count,
                'removed_duplicates': original_count - deduplicated_count
            })

        data_file = os.path.join(BASE_DIR, 'data', f'results_{task_id}.csv')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        
        with open(data_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Tên địa điểm','Địa chỉ','Số điện thoại','Website']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        task_manager.cache_result(
            keyword,
            num_results,
            results if not session_id else cached_result or results,  # Cache original results
            search_params.get('lat', ''),
            search_params.get('lng', ''),
            session_id
        )

        task_manager.update_task(task_id, {
            'status': 'completed',
            'progress': 100,
            'results': results,
            'total_found': len(places_urls),
            'successful_extracts': successful_extracts,
            'file_path': data_file
        })

        performance_monitor.record_request(True)

    except Exception as e:
        task_manager.update_task(task_id, {
            'status': 'failed',
            'error': str(e)
        })
        performance_monitor.record_request(False)
    finally:
        if driver and profile:
            driver_pool.return_driver(driver, profile)

def stream_search_results(keyword, location, max_results, user_lat=None, user_lng=None, session_id=None):
    """Stream search results progressively"""
    results = []
    seen_places = set()
    
    # Get session-specific seen places to avoid duplicates
    if session_id:
        session_key = f"seen_places_{session_id}_{keyword.lower()}"
        if session_key in session:
            seen_places = set(session[session_key])
    
    driver = None
    profile = None
    
    try:
        driver, profile = driver_pool.get_driver()
        
        # Build search URL with location optimization
        if user_lat and user_lng:
            search_url = f"https://www.google.com/maps/search/{quote_plus(keyword)}/@{user_lat},{user_lng},15z"
        else:
            search_url = f"https://www.google.com/maps/search/{quote_plus(keyword)}+{quote_plus(location)}"
        
        driver.get(search_url)
        time.sleep(2)
        
        # Progressive scrolling and result streaming
        scroll_count = 0
        max_scrolls = min(20, max_results // 5)
        
        while len(results) < max_results and scroll_count < max_scrolls:
            # Find new results
            places = driver.find_elements(By.CSS_SELECTOR, '[data-result-index]')
            
            batch_results = []
            for place in places:
                if len(results) >= max_results:
                    break
                    
                try:
                    name_elem = place.find_element(By.CSS_SELECTOR, '[class*="fontHeadlineSmall"]')
                    name = name_elem.text.strip()
                    
                    # Skip duplicates
                    if name.lower() in seen_places:
                        continue
                    
                    seen_places.add(name.lower())
                    
                    # Extract additional info
                    rating = "N/A"
                    address = "N/A"
                    phone = "N/A"
                    
                    try:
                        rating_elem = place.find_element(By.CSS_SELECTOR, '[class*="fontBodyMedium"] span[aria-label*="stars"]')
                        rating = rating_elem.get_attribute('aria-label').split()[0]
                    except:
                        pass
                    
                    try:
                        address_elem = place.find_element(By.CSS_SELECTOR, '[data-value="Address"]')
                        address = address_elem.text.strip()
                    except:
                        pass
                    
                    result = {
                        'name': name,
                        'rating': rating,
                        'address': address,
                        'phone': phone,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    results.append(result)
                    batch_results.append(result)
                    
                    # Stream results in chunks
                    if len(batch_results) >= Config.STREAM_CHUNK_SIZE:
                        yield json.dumps({
                            'type': 'results',
                            'data': batch_results,
                            'total_found': len(results),
                            'progress': min(100, (len(results) / max_results) * 100)
                        }) + '\n'
                        batch_results = []
                
                except Exception as e:
                    continue
            
            # Stream remaining results in batch
            if batch_results:
                yield json.dumps({
                    'type': 'results',
                    'data': batch_results,
                    'total_found': len(results),
                    'progress': min(100, (len(results) / max_results) * 100)
                }) + '\n'
            
            # Scroll for more results
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            scroll_count += 1
            
            # Send progress update
            yield json.dumps({
                'type': 'progress',
                'progress': min(100, (len(results) / max_results) * 100),
                'message': f'Đã tìm thấy {len(results)} kết quả...'
            }) + '\n'
    
    except Exception as e:
        yield json.dumps({
            'type': 'error',
            'message': f'Lỗi tìm kiếm: {str(e)}'
        }) + '\n'
    
    finally:
        # Save seen places to session
        if session_id:
            session_key = f"seen_places_{session_id}_{keyword.lower()}"
            session[session_key] = list(seen_places)
        
        if driver and profile:
            driver_pool.return_driver(driver, profile)
        
        # Send completion
        yield json.dumps({
            'type': 'complete',
            'total_results': len(results),
            'message': f'Hoàn thành! Tìm thấy {len(results)} kết quả.'
        }) + '\n'

@app.route('/stream_search')
def stream_search():
    keyword = request.args.get('keyword', '').strip()
    location = request.args.get('location', '').strip()
    max_results = min(int(request.args.get('max_results', 20)), Config.MAX_RESULTS_PER_REQUEST)
    user_lat = request.args.get('lat')
    user_lng = request.args.get('lng')
    
    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400
    
    # Generate session ID for deduplication
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    session_id = session['session_id']
    
    # Convert coordinates
    try:
        if user_lat and user_lng:
            user_lat = float(user_lat)
            user_lng = float(user_lng)
    except:
        user_lat = user_lng = None
    
    def generate():
        yield "data: " + json.dumps({'type': 'start', 'message': 'Bắt đầu tìm kiếm...'}) + '\n\n'
        
        for chunk in stream_search_results(keyword, location, max_results, user_lat, user_lng, session_id):
            yield f"data: {chunk}\n"
        
        yield "data: " + json.dumps({'type': 'end'}) + '\n\n'
    
    return Response(generate(), mimetype='text/plain')

# -------------------- Routes --------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
@gzip_response
def search():
    client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
    if not task_manager.check_rate_limit(client_ip):
        return jsonify({
            'error': 'Quá nhiều request. Vui lòng thử lại sau.'
        }), 429

    search_key = (request.form.get('search_key') or '').strip()
    if not search_key:
        return jsonify({'error': 'Vui lòng nhập từ khóa tìm kiếm'}), 400

    try:
        num_results = int(request.form.get('num_results', '10') or 10)
        if num_results <= 0 or num_results > 100:
            return jsonify({'error': 'Số lượng kết quả phải từ 1 đến 100'}), 400
    except ValueError:
        return jsonify({'error': 'Số lượng kết quả không hợp lệ'}), 400

    lat_str = (request.form.get('lat') or '').strip()
    lng_str = (request.form.get('lng') or '').strip()
    
    if lat_str or lng_str:
        if not (lat_str and lng_str):
            return jsonify({'error': 'Vui lòng nhập cả vĩ độ và kinh độ'}), 400
        
        try:
            validate_gps_coordinates(lat_str, lng_str)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    if performance_monitor.should_trigger_gc():
        gc.collect()

    active_count = len([t for t in task_manager.active_tasks.values() 
                       if t['status'] in ['running', 'queued']])
    if active_count >= Config.MAX_CONCURRENT_TASKS:
        return jsonify({
            'error': 'Server đang xử lý quá nhiều tác vụ. Vui lòng thử lại sau.'
        }), 503

    task_id = str(uuid.uuid4())
    session_id = task_manager.dedup_manager.get_session_id()
    
    search_params = {
        'search_key': search_key,
        'num_results': num_results,
        'lat': lat_str,
        'lng': lng_str,
        'session_id': session_id,  # Added session tracking
        'gps_enabled': bool(lat_str and lng_str)  # GPS flag
    }

    task_manager.add_task(task_id, {
        'search_params': search_params,
        'client_ip': client_ip,
        'session_id': session_id  # Added session tracking
    })

    future = executor.submit(process_scraping_task, task_id, search_params)
    
    return jsonify({
        'task_id': task_id,
        'status': 'queued',
        'message': 'Tác vụ đã được thêm vào hàng đợi',
        'gps_enabled': bool(lat_str and lng_str),  # GPS status
        'session_id': session_id  # Return session ID
    })

@app.route('/status/<task_id>', methods=['GET'])
@gzip_response
def get_status(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({'error': 'Task không tồn tại'}), 404

    response_data = {
        'task_id': task_id,
        'status': task.get('status', 'unknown'),
        'progress': task.get('progress', 0),
        'current_count': task.get('current_count', 0),
        'current_extracted': task.get('current_extracted', 0),
        'successful_extracts': task.get('successful_extracts', 0),
        'from_cache': task.get('from_cache', False),
        'gps_optimized': task.get('gps_optimized', False),
        'deduplicated': task.get('deduplicated', False),
        'removed_duplicates': task.get('removed_duplicates', 0)
    }

    if task['status'] == 'completed':
        response_data.update({
            'results': task.get('results', []),
            'total_found': task.get('total_found', 0),
            'original_count': task.get('original_count', 0),
            'message': f"Đã hoàn thành thu thập {task.get('successful_extracts', 0)}/{task.get('total_found', 0)} địa điểm"
        })
        
        if task.get('removed_duplicates', 0) > 0:
            response_data['message'] += f" (đã loại bỏ {task.get('removed_duplicates')} kết quả trùng lặp)"
            
    elif task['status'] == 'failed':
        response_data['error'] = task.get('error', 'Lỗi không xác định')
        if task.get('gps_error'):
            response_data['gps_error'] = task.get('gps_error')

    return jsonify(response_data)

@app.route('/download/<task_id>', methods=['GET'])
def download_csv(task_id):
    task = task_manager.get_task(task_id)
    if not task or task['status'] != 'completed':
        return jsonify({'error': 'Task chưa hoàn thành hoặc không tồn tại'}), 404

    file_path = task.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File kết quả không tồn tại'}), 404

    return send_file(file_path, as_attachment=True, 
                    download_name=f'google_maps_results_{task_id}.csv')

@app.route('/cleanup/<task_id>', methods=['DELETE'])
def cleanup_task(task_id):
    task = task_manager.get_task(task_id)
    if task:
        file_path = task.get('file_path')
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        
        task_manager.remove_task(task_id)
        return jsonify({'message': 'Task đã được xóa'})
    
    return jsonify({'error': 'Task không tồn tại'}), 404

@app.route('/system/status', methods=['GET'])
@gzip_response
def system_status():
    active_tasks = [t for t in task_manager.active_tasks.values() 
                   if t['status'] in ['running', 'queued']]
    
    return jsonify({
        'active_tasks': len(active_tasks),
        'max_concurrent': Config.MAX_CONCURRENT_TASKS,
        'driver_pool_busy': len(driver_pool.busy_drivers),
        'driver_pool_available': driver_pool.available_drivers.qsize(),
        'max_drivers': driver_pool.max_drivers,
        'performance': performance_monitor.get_stats(),
        'cache_size': len(task_manager.cache.cache),
        'memory_usage': performance_monitor.get_memory_usage()
    })

@app.route('/system/clear-cache', methods=['POST'])
def clear_cache():
    task_manager.cache.cache.clear()
    task_manager.cache.access_times.clear()
    gc.collect()
    return jsonify({'message': 'Cache đã được xóa'})

# -------------------- Background Tasks --------------------
def cleanup_old_tasks():
    cutoff = datetime.now() - timedelta(hours=2)
    to_remove = []
    
    for task_id, task in task_manager.active_tasks.items():
        if task['created_at'] < cutoff:
            file_path = task.get('file_path')
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            to_remove.append(task_id)
    
    for task_id in to_remove:
        task_manager.remove_task(task_id)

def periodic_maintenance():
    while True:
        time.sleep(Config.GC_INTERVAL)
        
        cleanup_old_tasks()
        task_manager.cache.clear_expired()
        task_manager.dedup_manager.cleanup_expired_sessions()
        
        if performance_monitor.should_trigger_gc():
            gc.collect()
        
        print(f"Maintenance completed. Memory: {performance_monitor.get_memory_usage()['percent']:.1f}%")

# Start background threads
cleanup_thread = threading.Thread(target=periodic_maintenance, daemon=True)
cleanup_thread.start()

# -------------------- Main --------------------
if __name__ == '__main__':
    os.makedirs(os.path.join(BASE_DIR, 'templates'), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
    
    try:
        print("🚀 Starting Google Maps Scraper Server...")
        print(f"📊 Max concurrent tasks: {Config.MAX_CONCURRENT_TASKS}")
        print(f"🔧 Driver pool size: {Config.MAX_DRIVERS_POOL}")
        print(f"💾 Cache size limit: {Config.MAX_CACHE_SIZE}")
        print(f"🌍 GPS optimization enabled")
        print(f"🔄 Session deduplication enabled")
        
        # Initialize driver pool
        print("🔧 Initializing driver pool...")
        
        # Start Flask app
        app.run(
            host='0.0.0.0',
            port=int(os.environ.get('PORT', 8080)),
            debug=False,
            threaded=True
        )
        
    except KeyboardInterrupt:
        print("\n⏹️  Shutting down server...")
    except Exception as e:
        print(f"❌ Server error: {e}")
    finally:
        # Cleanup resources
        print("🧹 Cleaning up resources...")
        try:
            driver_pool.cleanup()
            executor.shutdown(wait=True)
        except:
            pass
        print("✅ Server shutdown complete")
