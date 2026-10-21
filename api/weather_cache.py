"""
Weather API caching layer with Redis support and fallback to in-memory cache.
Implements 10-minute TTL for weather data keyed by rounded (lat, lon).
"""
import json
import time
import urllib.request
from typing import Optional, Tuple, Dict, Any
from django.conf import settings

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# In-memory cache always available as fallback
_MEMORY_CACHE = {}


def get_redis_client():
    """Return a connected Redis client or None if unavailable."""
    if not REDIS_AVAILABLE:
        return None
    redis_url = getattr(settings, 'REDIS_URL', None)
    if not redis_url:
        return None
    try:
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        return client
    except Exception as e:
        print(f'Redis connection failed: {e}')
        return None


class WeatherCache:
    """Weather API cache with Redis backend and in-memory fallback"""
    
    CACHE_TTL = 600  # 10 minutes in seconds
    COORD_PRECISION = 2  # Round coordinates to 2 decimal places (~1km precision)
    
    def __init__(self):
        self.redis_client = get_redis_client()
    
    def _make_cache_key(self, lat: float, lon: float, data_type: str) -> str:
        """Generate cache key from rounded coordinates"""
        lat_rounded = round(lat, self.COORD_PRECISION)
        lon_rounded = round(lon, self.COORD_PRECISION)
        return f"weather:{data_type}:{lat_rounded}:{lon_rounded}"
    
    def get(self, lat: float, lon: float, data_type: str) -> Optional[Dict[str, Any]]:
        """Get cached weather data"""
        cache_key = self._make_cache_key(lat, lon, data_type)
        
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                print(f"Redis get error: {e}")
        else:
            # In-memory fallback
            if cache_key in _MEMORY_CACHE:
                entry = _MEMORY_CACHE[cache_key]
                if time.time() - entry['timestamp'] < self.CACHE_TTL:
                    return entry['data']
                else:
                    del _MEMORY_CACHE[cache_key]
        
        return None
    
    def set(self, lat: float, lon: float, data_type: str, data: Dict[str, Any]) -> None:
        """Cache weather data with TTL"""
        cache_key = self._make_cache_key(lat, lon, data_type)
        
        if self.redis_client:
            try:
                self.redis_client.setex(
                    cache_key,
                    self.CACHE_TTL,
                    json.dumps(data)
                )
            except Exception as e:
                print(f"Redis set error: {e}")
        else:
            # In-memory fallback with manual TTL
            _MEMORY_CACHE[cache_key] = {
                'data': data,
                'timestamp': time.time()
            }
            # Simple cleanup: remove expired entries if cache grows too large
            if len(_MEMORY_CACHE) > 100:
                now = time.time()
                expired = [k for k, v in _MEMORY_CACHE.items() 
                          if now - v['timestamp'] >= self.CACHE_TTL]
                for k in expired:
                    del _MEMORY_CACHE[k]


# Global cache instance
_weather_cache = WeatherCache()


def fetch_weather_with_cache(lat: float, lon: float) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Fetch current weather and forecast with caching.
    Returns: (current_data, forecast_data)
    """
    api_key = getattr(settings, 'OPENWEATHER_API_KEY', '')
    if not api_key:
        return None, None
    
    # Try to get from cache first
    current_cached = _weather_cache.get(lat, lon, 'current')
    forecast_cached = _weather_cache.get(lat, lon, 'forecast')
    
    if current_cached and forecast_cached:
        return current_cached, forecast_cached
    
    # Cache miss - fetch from API
    current_data = None
    forecast_data = None
    
    try:
        # Fetch current weather
        current_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        with urllib.request.urlopen(current_url, timeout=8) as r:
            current_data = json.loads(r.read().decode())
        
        # Fetch forecast
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        with urllib.request.urlopen(forecast_url, timeout=8) as r:
            forecast_data = json.loads(r.read().decode())
        
        # Cache the results
        if current_data:
            _weather_cache.set(lat, lon, 'current', current_data)
        if forecast_data:
            _weather_cache.set(lat, lon, 'forecast', forecast_data)
        
    except Exception as e:
        print(f"Weather API fetch error: {e}")
    
    return current_data, forecast_data
