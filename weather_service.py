import requests
from datetime import datetime, timedelta
from django.conf import settings

class WeatherService:
    def __init__(self):
        # Free OpenWeatherMap API key - you'll need to get your own
        self.api_key = getattr(settings, 'OPENWEATHER_API_KEY', 'your_api_key_here')
        self.base_url = 'https://api.openweathermap.org/data/2.5'
        
    def get_current_weather(self, lat=40.7128, lon=-74.0060):  # Default: NYC
        """Get current weather data"""
        try:
            url = f"{self.base_url}/weather"
            params = {
                'lat': lat,
                'lon': lon,
                'appid': self.api_key,
                'units': 'metric'
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Weather API error: {e}")
            return None
    
    def get_forecast(self, lat=40.7128, lon=-74.0060):
        """Get 7-day weather forecast"""
        try:
            url = f"{self.base_url}/forecast"
            params = {
                'lat': lat,
                'lon': lon,
                'appid': self.api_key,
                'units': 'metric'
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Forecast API error: {e}")
            return None
    
    def parse_current_weather(self, data):
        """Parse current weather API response"""
        if not data:
            return self._get_fallback_current()
            
        main = data.get('main', {})
        weather = data.get('weather', [{}])[0]
        wind = data.get('wind', {})
        
        # Map OpenWeather conditions to our app conditions
        condition_map = {
            'clear sky': 'sunny',
            'few clouds': 'partly_cloudy',
            'scattered clouds': 'partly_cloudy',
            'broken clouds': 'cloudy',
            'overcast clouds': 'cloudy',
            'shower rain': 'rainy',
            'rain': 'rainy',
            'thunderstorm': 'stormy',
            'snow': 'snowy',
            'mist': 'foggy',
            'fog': 'foggy'
        }
        
        description = weather.get('description', '').lower()
        condition = condition_map.get(description, 'sunny')
        
        return {
            'condition': condition,
            'temperature': round(main.get('temp', 0)),
            'humidity': main.get('humidity', 0),
            'rain_probability': 0,  # Current weather doesn't include rain probability
            'wind_speed': round(wind.get('speed', 0) * 3.6),  # Convert m/s to km/h
            'pressure': main.get('pressure', 0),
            'visibility': round(data.get('visibility', 10000) / 1000),  # Convert m to km
            'feels_like': round(main.get('feels_like', 0)),
            'description': weather.get('description', '').title(),
            'location': data.get('name', 'Unknown'),
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
    
    def parse_forecast(self, data):
        """Parse forecast API response into 7-day format"""
        if not data:
            return self._get_fallback_forecast()
            
        forecast_list = data.get('list', [])
        if not forecast_list:
            return self._get_fallback_forecast()
        
        # Group by day and get daily highs/lows
        daily_data = {}
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        for item in forecast_list[:35]:  # 5 days * 8 (3-hour intervals)
            dt = datetime.fromtimestamp(item['dt'])
            date_key = dt.strftime('%Y-%m-%d')
            
            if date_key not in daily_data:
                daily_data[date_key] = {
                    'day': days[dt.weekday()],
                    'date': date_key,
                    'temps': [],
                    'conditions': [],
                    'rain_probs': []
                }
            
            daily_data[date_key]['temps'].append(item['main']['temp'])
            
            # Get condition
            weather = item.get('weather', [{}])[0]
            description = weather.get('description', '').lower()
            condition_map = {
                'clear sky': 'sunny',
                'few clouds': 'partly_cloudy',
                'scattered clouds': 'partly_cloudy',
                'broken clouds': 'cloudy',
                'overcast clouds': 'cloudy',
                'shower rain': 'rainy',
                'rain': 'rainy',
                'thunderstorm': 'stormy',
                'snow': 'snowy',
                'mist': 'foggy',
                'fog': 'foggy'
            }
            condition = condition_map.get(description, 'sunny')
            daily_data[date_key]['conditions'].append(condition)
            
            # Calculate rain probability from precipitation
            rain_prob = 0
            if 'rain' in item:
                rain_prob = min(100, item['rain'].get('3h', 0) * 20)  # Rough conversion
            elif condition in ['rainy', 'stormy']:
                rain_prob = 70
            elif condition == 'cloudy':
                rain_prob = 30
            elif condition == 'partly_cloudy':
                rain_prob = 15
            
            daily_data[date_key]['rain_probs'].append(rain_prob)
        
        # Convert to final format
        forecast = []
        for date_key in sorted(daily_data.keys())[:7]:  # Limit to 7 days
            day_data = daily_data[date_key]
            
            # Get most common condition
            conditions = day_data['conditions']
            condition = max(set(conditions), key=conditions.count) if conditions else 'sunny'
            
            forecast.append({
                'day': day_data['day'],
                'date': date_key,
                'condition': condition,
                'temp_high': round(max(day_data['temps'])) if day_data['temps'] else 25,
                'temp_low': round(min(day_data['temps'])) if day_data['temps'] else 15,
                'rain_probability': round(sum(day_data['rain_probs']) / len(day_data['rain_probs'])) if day_data['rain_probs'] else 10
            })
        
        # Fill remaining days with fallback data if needed
        while len(forecast) < 7:
            base_date = datetime.now() + timedelta(days=len(forecast))
            forecast.append({
                'day': days[base_date.weekday()],
                'date': base_date.strftime('%Y-%m-%d'),
                'condition': 'sunny',
                'temp_high': 25,
                'temp_low': 15,
                'rain_probability': 10
            })
        
        return forecast[:7]
    
    def _get_fallback_current(self):
        """Fallback current weather data when API fails"""
        return {
            'condition': 'sunny',
            'temperature': 24,
            'humidity': 60,
            'rain_probability': 10,
            'wind_speed': 14,
            'pressure': 1013,
            'visibility': 10,
            'feels_like': 26,
            'description': 'Clear skies (offline data)',
            'location': 'Unknown Location',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
    
    def _get_fallback_forecast(self):
        """Fallback forecast data when API fails"""
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        conditions = ['sunny', 'partly_cloudy', 'cloudy', 'rainy', 'sunny', 'windy', 'sunny']
        temp_highs = [26, 24, 21, 19, 23, 25, 27]
        temp_lows = [16, 15, 14, 13, 15, 16, 17]
        rain_probs = [5, 20, 40, 75, 15, 10, 5]
        
        forecast = []
        now = datetime.now()
        
        for i in range(7):
            date = now + timedelta(days=i)
            forecast.append({
                'day': days[date.weekday()],
                'date': date.strftime('%Y-%m-%d'),
                'condition': conditions[i],
                'temp_high': temp_highs[i],
                'temp_low': temp_lows[i],
                'rain_probability': rain_probs[i]
            })
        
        return forecast