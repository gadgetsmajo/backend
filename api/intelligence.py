"""
Agricultural Intelligence Engine — East Africa (EAT, UTC+3)

Seasons (East Africa):
  Long Rains  (Masika) : March–May
  Cool Dry             : June–August
  Short Rains (Vuli)   : October–November
  Hot Dry              : December–February
  Transition           : September
"""

from datetime import date

# ── Season detection ──────────────────────────────────────────────────────────

SEASONS = {
    'long_rains':   {'label': 'Long Rains (Masika)',  'months': [3, 4, 5]},
    'cool_dry':     {'label': 'Cool & Dry',           'months': [6, 7, 8]},
    'transition':   {'label': 'Transition',           'months': [9]},
    'short_rains':  {'label': 'Short Rains (Vuli)',   'months': [10, 11]},
    'hot_dry':      {'label': 'Hot & Dry',            'months': [12, 1, 2]},
}

def detect_season(month: int) -> dict:
    for key, s in SEASONS.items():
        if month in s['months']:
            return {'key': key, 'label': s['label']}
    return {'key': 'transition', 'label': 'Transition'}


# ── Crop profiles ─────────────────────────────────────────────────────────────
# water_demand_l_day : litres per 10m² per day at 25°C baseline
# stress_temp_high   : °C above which plant stress begins
# stress_moisture_low: % below which plant is stressed
# root_depth_factor  : deeper roots = soil holds moisture longer (< 1 = less frequent)
# season_adjust      : multiplier per season key

CROP_PROFILES = {
    'maize': {
        'label': 'Maize / Corn',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'wheat': {
        'label': 'Wheat',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'rice': {
        'label': 'Rice',
        'water_demand_l_day': 7.5,
        'stress_temp_high': 35,
        'stress_moisture_low': 50,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.35,
            'cool_dry': 0.95,
            'short_rains': 0.4,
            'hot_dry': 1.5,
            'transition': 1.0,
        },
    },
    'sorghum': {
        'label': 'Sorghum',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'millet': {
        'label': 'Millet',
        'water_demand_l_day': 4.0,
        'stress_temp_high': 28,
        'stress_moisture_low': 18,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'barley': {
        'label': 'Barley',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 25,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'oats': {
        'label': 'Oats',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'teff': {
        'label': 'Teff',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'quinoa': {
        'label': 'Quinoa',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'soybean': {
        'label': 'Soybean',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'beans': {
        'label': 'Beans',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'groundnut': {
        'label': 'Groundnut',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cowpea': {
        'label': 'Cowpea',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'pigeon_pea': {
        'label': 'Pigeon Pea',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'chickpea': {
        'label': 'Chickpea',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'lentil': {
        'label': 'Lentil',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 22,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'green_bean': {
        'label': 'Green Bean',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'lima_bean': {
        'label': 'Lima Bean',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'mung_bean': {
        'label': 'Mung Bean',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'fava_bean': {
        'label': 'Fava Bean',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'potato': {
        'label': 'Potato',
        'water_demand_l_day': 7.5,
        'stress_temp_high': 35,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.35,
            'cool_dry': 0.95,
            'short_rains': 0.4,
            'hot_dry': 1.5,
            'transition': 1.0,
        },
    },
    'cassava': {
        'label': 'Cassava',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'sweet_potato': {
        'label': 'Sweet Potato',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'yam': {
        'label': 'Yam',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 35,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'taro': {
        'label': 'Taro',
        'water_demand_l_day': 7.5,
        'stress_temp_high': 35,
        'stress_moisture_low': 40,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.35,
            'cool_dry': 0.95,
            'short_rains': 0.4,
            'hot_dry': 1.5,
            'transition': 1.0,
        },
    },
    'beetroot': {
        'label': 'Beetroot',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'carrot': {
        'label': 'Carrot',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'turnip': {
        'label': 'Turnip',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'radish': {
        'label': 'Radish',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'tomato': {
        'label': 'Tomato',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cabbage': {
        'label': 'Cabbage',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'onion': {
        'label': 'Onion',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cucumber': {
        'label': 'Cucumber',
        'water_demand_l_day': 7.5,
        'stress_temp_high': 35,
        'stress_moisture_low': 45,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.35,
            'cool_dry': 0.95,
            'short_rains': 0.4,
            'hot_dry': 1.5,
            'transition': 1.0,
        },
    },
    'spinach': {
        'label': 'Spinach',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'kale': {
        'label': 'Kale',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'lettuce': {
        'label': 'Lettuce',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'eggplant': {
        'label': 'Eggplant',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'okra': {
        'label': 'Okra',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'pumpkin': {
        'label': 'Pumpkin',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'zucchini': {
        'label': 'Zucchini',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'leek': {
        'label': 'Leek',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'garlic': {
        'label': 'Garlic',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 25,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'celery': {
        'label': 'Celery',
        'water_demand_l_day': 7.5,
        'stress_temp_high': 35,
        'stress_moisture_low': 45,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.35,
            'cool_dry': 0.95,
            'short_rains': 0.4,
            'hot_dry': 1.5,
            'transition': 1.0,
        },
    },
    'broccoli': {
        'label': 'Broccoli',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cauliflower': {
        'label': 'Cauliflower',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'amaranth': {
        'label': 'Amaranth',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'swiss_chard': {
        'label': 'Swiss Chard',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'banana': {
        'label': 'Banana',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'mango': {
        'label': 'Mango',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 25,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'watermelon': {
        'label': 'Watermelon',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'avocado': {
        'label': 'Avocado',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'papaya': {
        'label': 'Papaya',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'pineapple': {
        'label': 'Pineapple',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'passion_fruit': {
        'label': 'Passion Fruit',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'guava': {
        'label': 'Guava',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'orange': {
        'label': 'Orange',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'lemon': {
        'label': 'Lemon',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'lime': {
        'label': 'Lime',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'strawberry': {
        'label': 'Strawberry',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'melon': {
        'label': 'Melon',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'jackfruit': {
        'label': 'Jackfruit',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'coconut': {
        'label': 'Coconut',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cotton': {
        'label': 'Cotton',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'sugarcane': {
        'label': 'Sugarcane',
        'water_demand_l_day': 7.5,
        'stress_temp_high': 35,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.35,
            'cool_dry': 0.95,
            'short_rains': 0.4,
            'hot_dry': 1.5,
            'transition': 1.0,
        },
    },
    'sunflower': {
        'label': 'Sunflower',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 25,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'coffee': {
        'label': 'Coffee',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'tea': {
        'label': 'Tea',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cocoa': {
        'label': 'Cocoa',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'tobacco': {
        'label': 'Tobacco',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'sisal': {
        'label': 'Sisal',
        'water_demand_l_day': 4.0,
        'stress_temp_high': 28,
        'stress_moisture_low': 15,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'pyrethrum': {
        'label': 'Pyrethrum',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'vanilla': {
        'label': 'Vanilla',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'hops': {
        'label': 'Hops',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'palm_oil': {
        'label': 'Palm Oil',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'sesame': {
        'label': 'Sesame',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'safflower': {
        'label': 'Safflower',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'flaxseed': {
        'label': 'Flaxseed',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 22,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'canola': {
        'label': 'Canola',
        'water_demand_l_day': 4.5,
        'stress_temp_high': 30,
        'stress_moisture_low': 22,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.45,
            'cool_dry': 0.75,
            'short_rains': 0.55,
            'hot_dry': 1.15,
            'transition': 1.0,
        },
    },
    'pepper': {
        'label': 'Pepper',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'ginger': {
        'label': 'Ginger',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'turmeric': {
        'label': 'Turmeric',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'coriander': {
        'label': 'Coriander',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'basil': {
        'label': 'Basil',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'mint': {
        'label': 'Mint',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'chili': {
        'label': 'Chili',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 35,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'cardamom': {
        'label': 'Cardamom',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 33,
        'stress_moisture_low': 40,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'napier_grass': {
        'label': 'Napier Grass',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'alfalfa': {
        'label': 'Alfalfa',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 30,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'rhodes_grass': {
        'label': 'Rhodes Grass',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 25,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'desmodium': {
        'label': 'Desmodium',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 28,
        'root_depth_factor': 0.95,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
    'general': {
        'label': 'General Crop',
        'water_demand_l_day': 5.5,
        'stress_temp_high': 32,
        'stress_moisture_low': 20,
        'root_depth_factor': 1.05,
        'season_adjust': {
            'long_rains': 0.4,
            'cool_dry': 0.85,
            'short_rains': 0.5,
            'hot_dry': 1.3,
            'transition': 1.0,
        },
    },
}

def get_crop_profile(plant_type: str) -> dict:
    key = (plant_type or 'general').strip().lower()

    # Check DB overrides first (admin-managed profiles)
    try:
        from api.models import PlantProfile
        DEFAULT_SEASON_ADJUST = {
            'long_rains': 0.4, 'cool_dry': 0.85,
            'short_rains': 0.5, 'hot_dry': 1.3, 'transition': 1.0,
        }
        # Exact match first, then substring
        db_profile = (
            PlantProfile.objects.filter(key=key, is_active=True).first()
            or PlantProfile.objects.filter(key__icontains=key, is_active=True).first()
        )
        if db_profile:
            sa = db_profile.season_adjust or {}
            merged = {**DEFAULT_SEASON_ADJUST, **sa}
            return {
                'key': db_profile.key,
                'label': db_profile.label,
                'water_demand_l_day': db_profile.water_demand_l_day,
                'stress_temp_high': db_profile.stress_temp_high,
                'stress_moisture_low': db_profile.stress_moisture_low,
                'root_depth_factor': db_profile.root_depth_factor,
                'season_adjust': merged,
            }
    except Exception:
        pass

    # Fall back to built-in profiles
    for k in CROP_PROFILES:
        if k in key:
            return {'key': k, **CROP_PROFILES[k]}
    return {'key': 'general', **CROP_PROFILES['general']}


# ── Seasonal learning from historical logs ────────────────────────────────────

def compute_drying_rate(recent_logs: list) -> dict:
    """
    Analyse last 30 days of DailyAgriLog rows.
    Returns avg daily moisture drop and a trend label.
    recent_logs: list of dicts with keys: avg_moisture, avg_temp, total_rain_mm
    """
    if len(recent_logs) < 3:
        return {'rate': None, 'trend': 'insufficient_data', 'label': 'Not enough history yet'}

    drops = []
    for i in range(1, len(recent_logs)):
        prev = recent_logs[i - 1].get('avg_moisture') or 0
        curr = recent_logs[i].get('avg_moisture') or 0
        if prev and curr:
            drops.append(prev - curr)

    if not drops:
        return {'rate': None, 'trend': 'insufficient_data', 'label': 'Not enough history yet'}

    avg_drop = sum(drops) / len(drops)

    if avg_drop > 5:
        trend, label = 'fast_drying', 'Soil drying fast — increase irrigation'
    elif avg_drop > 2:
        trend, label = 'normal_drying', 'Normal drying rate'
    elif avg_drop > 0:
        trend, label = 'slow_drying', 'Soil retaining moisture well — reduce irrigation'
    else:
        trend, label = 'stable', 'Moisture stable — minimal irrigation needed'

    return {'rate': round(avg_drop, 2), 'trend': trend, 'label': label}


# ── Core smart irrigation calculator ─────────────────────────────────────────

PUMP_FLOW_RATE = 10  # L/min

def compute_smart_irrigation(
    temp: float,
    rain_prob: float,
    condition: str,
    soil_water_factor: float,
    base_duration: int,
    crop_profile: dict,
    season: dict,
    drying: dict,
    recent_logs: list,
) -> dict:
    """
    Returns a fully reasoned irrigation plan dict.
    """
    reasons = []
    season_key = season['key']

    # 1. Skip if heavy rain
    if rain_prob >= 70 or condition == 'rainy':
        return {
            'skip': True, 'cycles': 0, 'duration_min': 0, 'total_min': 0,
            'pump_times': [], 'water_per_cycle_l': 0, 'water_total_l': 0,
            'rain_saving_l': 0, 'estimated_need_l': 0,
            'reason': f'Skip — {"heavy rain expected" if rain_prob >= 70 else "rainy conditions"}',
            'smart_reasons': [f'Rain probability {rain_prob}% — irrigation not needed'],
            'season_label': season['label'],
            'crop_label': crop_profile['label'],
            'drying_label': drying['label'],
        }

    # 2. Base duration adjusted for soil
    duration = round(base_duration * soil_water_factor)

    # 3. Temperature → cycles
    if temp >= 32:
        cycles, temp_factor = 3, 1.4
        reasons.append(f'High temp {temp}°C — maximum irrigation')
    elif temp >= 28:
        cycles, temp_factor = 3, 1.2
        reasons.append(f'Warm {temp}°C — extra irrigation')
    elif temp >= 24:
        cycles, temp_factor = 2, 1.0
        reasons.append(f'Moderate {temp}°C — normal irrigation')
    else:
        cycles, temp_factor = 1, 0.8
        duration = round(duration * 0.8)
        reasons.append(f'Cool {temp}°C — reduced irrigation')

    # 4. Crop stress check
    if temp >= crop_profile['stress_temp_high']:
        cycles = min(cycles + 1, 4)
        reasons.append(f'{crop_profile["label"]} stress above {crop_profile["stress_temp_high"]}°C — extra cycle added')

    # 5. Season adjustment
    season_factor = crop_profile['season_adjust'].get(season_key, 1.0)
    duration = round(duration * season_factor)
    cycles = max(1, round(cycles * season_factor))
    reasons.append(f'{season["label"]} season — irrigation scaled by {season_factor}×')

    # 6. Drying rate adjustment from historical data
    drying_trend = drying.get('trend', 'insufficient_data')
    if drying_trend == 'fast_drying':
        cycles = min(cycles + 1, 4)
        reasons.append('Historical data: soil drying fast — added 1 cycle')
    elif drying_trend == 'slow_drying':
        cycles = max(1, cycles - 1)
        reasons.append('Historical data: soil retaining moisture — removed 1 cycle')
    elif drying_trend == 'stable':
        duration = round(duration * 0.85)
        reasons.append('Historical data: moisture stable — reduced duration')

    # 7. Partial rain reduction
    if rain_prob >= 40:
        cycles = max(1, cycles - 1)
        duration = round(duration * 0.7)
        reasons.append(f'Rain {rain_prob}% — reduced irrigation')
    elif rain_prob >= 20:
        duration = round(duration * 0.85)
        reasons.append(f'Light rain {rain_prob}% expected — slight reduction')

    # 8. Wind evaporation
    if condition == 'windy':
        duration = round(duration * 1.1)
        reasons.append('Windy — slight increase for evaporation loss')

    # 9. Water calculations
    daily_demand = crop_profile['water_demand_l_day'] * temp_factor * soil_water_factor * season_factor
    rain_saving = round((rain_prob / 100) * daily_demand, 1)
    water_per_cycle = round(duration * PUMP_FLOW_RATE, 1)
    water_total = round(cycles * water_per_cycle, 1)
    estimated_need = round((daily_demand - rain_saving) * 10, 1)

    # 10. Water optimization: cap total if estimated need is much lower
    if water_total > estimated_need * 1.5 and estimated_need > 0:
        cycles = max(1, cycles - 1)
        water_total = round(cycles * water_per_cycle, 1)
        reasons.append('Water optimization: capped excess irrigation')

    return {
        'skip': False,
        'cycles': cycles,
        'duration_min': duration,
        'total_min': cycles * duration,
        'pump_times': ['06:00', '12:00', '18:00', '21:00'][:cycles],
        'water_per_cycle_l': water_per_cycle,
        'water_total_l': water_total,
        'rain_saving_l': rain_saving * 10,
        'estimated_need_l': estimated_need,
        'reason': reasons[0] if reasons else 'Normal irrigation',
        'smart_reasons': reasons,
        'season_label': season['label'],
        'crop_label': crop_profile['label'],
        'drying_label': drying['label'],
        'drying_rate': drying.get('rate'),
        'season_factor': season_factor,
        'crop_stress_temp': crop_profile['stress_temp_high'],
    }
