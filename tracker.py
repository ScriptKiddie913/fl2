import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
POLL_INTERVAL_SECONDS = int(os.getenv('POLL_INTERVAL_SECONDS', '30'))
AIRLABS_API_KEY = (os.getenv('AIRLABS_API_KEY') or os.getenv('AIRLABS_KEY') or '').strip()

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
HEADERS = {'User-Agent': 'Mozilla/5.0'}
SESSION = requests.Session()

AIRPORT_COORDS = {
    'LAX': (33.9416, -118.4085),
    'JFK': (40.6413, -73.7781),
    'LHR': (51.4700, -0.4543),
    'DXB': (25.2532, 55.3657),
    'CDG': (49.0097, 2.5479),
    'AMS': (52.3105, 4.7683),
    'SIN': (1.3644, 103.9915),
    'HKG': (22.3080, 113.9185),
    'NRT': (35.7719, 140.3929),
    'SYD': (-33.9399, 151.1753),
    'ORD': (41.9742, -87.9073),
    'ATL': (33.6407, -84.4277),
    'DFW': (32.8998, -97.0403),
    'MIA': (25.7959, -80.2870),
    'BOS': (42.3656, -71.0096),
    'SEA': (47.4502, -122.3088),
    'SFO': (37.6213, -122.3790),
    'YYZ': (43.6777, -79.6248),
    'MEX': (19.4361, -99.0719),
    'GRU': (-23.4356, -46.4731),
    'EZE': (-34.8222, -58.5358),
    'CPT': (-33.9700, 18.5970),
    'JNB': (-26.1337, 28.2420),
    'DOH': (25.2736, 51.6081),
    'AUH': (24.4330, 54.6511),
    'KUL': (2.7456, 101.7072),
    'BKK': (13.6900, 100.7501),
    'ICN': (37.4602, 126.4407),
    'PEK': (40.0799, 116.6031),
    'PVG': (31.1443, 121.8083),
    'DEL': (28.5562, 77.1000),
    'BOM': (19.0896, 72.8656),
    'MUC': (48.3538, 11.7861),
    'FRA': (50.0379, 8.5622),
    'ZRH': (47.4581, 8.5555),
    'VIE': (48.1103, 16.5697),
    'BCN': (41.2974, 2.0833),
    'MAD': (40.4983, -3.5676),
    'FCO': (41.8003, 12.2389),
    'MXP': (45.6306, 8.7231),
    'IST': (41.2753, 28.7519),
    'CAI': (30.1219, 31.4056),
    'NBO': (-1.3192, 36.9278),
    'ADD': (8.9779, 38.7993),
    'LOS': (6.5774, 3.3212),
    'ACC': (5.6052, -0.1668),
    'CMN': (33.3675, -7.5899),
    'ALG': (36.6910, 3.2154),
}

TRACKING_CACHE: Dict[str, Dict[str, Any]] = {}


def log(message: str) -> None:
    print(f'[{datetime.now(timezone.utc).isoformat()}] {message}', flush=True)


def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    delays = [2, 4, 8]
    last_error: Optional[Exception] = None
    for index, delay in enumerate(delays, start=1):
        try:
            response = SESSION.get(url, params=params, headers=HEADERS, timeout=25)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            log(f'HTTP attempt {index} failed for {url}: {exc}')
            if index < len(delays):
                time.sleep(delay)
    raise last_error or RuntimeError(f'Failed to fetch {url}')


def distance(lat1, lon1, lat2, lon2):

    R = 6371

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(math.radians(lat1)) *
        math.cos(math.radians(lat2)) *
        math.sin(dlon / 2) ** 2
    )

    return R * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )


def get_weather(lat, lon):

    try:
        data = request_json(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': lat,
                'longitude': lon,
                'current': 'temperature_2m,wind_speed_10m,visibility,cloud_cover,precipitation',
            },
        )

        if not data:
            return None

        return data.get('current')

    except Exception:
        return None


def weather_score(weather):

    if not weather:
        return 10

    score = 0

    visibility = weather.get('visibility', 10000)
    wind = weather.get('wind_speed_10m', 0)
    cloud = weather.get('cloud_cover', 0)
    rain = weather.get('precipitation', 0)

    if visibility < 3000:
        score += 25

    elif visibility < 7000:
        score += 10

    if wind > 40:
        score += 18

    elif wind > 25:
        score += 10

    if cloud > 90:
        score += 10

    if rain > 3:
        score += 20

    return min(score, 95)


def congestion_metrics(lat, lon):

    try:
        data = request_json(
            f'https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/100'
        )

        if not data:
            return 5, 0

        aircraft = data.get('ac', [])

        count = len(aircraft)

        if count > 200:
            return 35, count

        elif count > 100:
            return 20, count

        elif count > 50:
            return 10, count

        return 3, count

    except Exception:
        return 5, 0


def estimate_delay(
    altitude,
    speed,
    weather,
    congestion
):

    score = 0

    if altitude < 12000:
        score += 15

    if altitude < 5000:
        score += 10

    if speed < 250:
        score += 20

    elif speed < 350:
        score += 10

    score += weather
    score += congestion

    return min(round(score, 2), 95)


def best_match(
    aircraft,
    target_lat,
    target_lon,
    target_speed,
    target_heading,
    target_airline
):

    best = None
    best_score = 999999

    for a in aircraft:

        try:

            callsign = (
                a.get("flight") or ""
            ).strip()

            lat = a.get("lat")
            lon = a.get("lon")

            speed = a.get("gs") or 0
            heading = a.get("track") or 0

            altitude = a.get("alt_baro") or 0

            if lat is None or lon is None:
                continue

            dist = distance(
                target_lat,
                target_lon,
                lat,
                lon
            )

            heading_diff = abs(
                heading - target_heading
            )

            speed_diff = abs(
                speed - target_speed
            )

            airline_bonus = 0

            if callsign.startswith(target_airline):
                airline_bonus = -200

            score = (
                dist * 10 +
                heading_diff * 2 +
                speed_diff * 0.2 +
                airline_bonus
            )

            if score < best_score:

                best_score = score

                best = {
                    'hex': a.get('hex'),
                    'flight': callsign,
                    'lat': lat,
                    'lon': lon,
                    'altitude': altitude,
                    'speed': speed,
                    'heading': heading,
                    'score': round(score, 2)
                }

        except Exception:
            pass

    return best


def unwrap_aircraft(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        for key in ('ac', 'response', 'data', 'aircraft', 'results'):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if all(not isinstance(value, (dict, list)) for value in data.values()):
            return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def airport_coords(iata: Optional[str]) -> Optional[Tuple[float, float]]:
    if not iata:
        return None
    return AIRPORT_COORDS.get(str(iata).upper())


def combine_datetime(date_text: str, time_text: str) -> datetime:
    normalized_time = time_text if len(time_text) > 5 else f'{time_text}:00'
    return datetime.fromisoformat(f'{date_text}T{normalized_time}').replace(tzinfo=timezone.utc)


def interpolate_position(
    departure_coords: Tuple[float, float],
    arrival_coords: Tuple[float, float],
    departure_time: datetime,
    arrival_time: datetime,
    now: datetime,
) -> Tuple[float, float, float]:
    total_seconds = max(1.0, (arrival_time - departure_time).total_seconds())
    progress = min(1.0, max(0.0, (now - departure_time).total_seconds() / total_seconds))
    lat = departure_coords[0] + (arrival_coords[0] - departure_coords[0]) * progress
    lon = departure_coords[1] + (arrival_coords[1] - departure_coords[1]) * progress
    return lat, lon, progress


def bearing(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def airlabs_bootstrap(flight_number: str) -> Optional[Dict[str, Any]]:
    if not AIRLABS_API_KEY:
        return None

    try:
        data = request_json(
            'https://airlabs.co/api/v9/flight',
            params={
                'flight_iata': flight_number,
                'api_key': AIRLABS_API_KEY,
            },
        )

        response = data.get('response') if isinstance(data, dict) else None
        if not response:
            return None

        return response

    except Exception as exc:
        log(f'[AIRLABS ERROR] {flight_number}: {exc}')
        return None


def adsb_callsign_lookup(flight_number: str) -> Optional[Dict[str, Any]]:
    try:
        data = request_json(f'https://api.adsb.lol/v2/callsign/{flight_number}')
        aircraft = unwrap_aircraft(data)
        if not aircraft:
            return None
        for item in aircraft:
            callsign = str(item.get('flight') or item.get('callsign') or '').strip().upper()
            if callsign == flight_number.upper() or flight_number.upper() in callsign:
                return item
        return aircraft[0]
    except Exception as exc:
        log(f'[CALLSIGN LOOKUP ERROR] {flight_number}: {exc}')
        return None


def area_search_lookup(flight: Dict[str, Any], now: datetime, bootstrap: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    departure_coords = airport_coords(flight.get('departure_airport'))
    arrival_coords = airport_coords(flight.get('arrival_airport'))
    if not departure_coords or not arrival_coords:
        return None

    departure_time = combine_datetime(flight['departure_date'], flight['departure_time'])
    arrival_time = combine_datetime(flight['arrival_date'], flight['arrival_time'])
    target_lat, target_lon, _ = interpolate_position(departure_coords, arrival_coords, departure_time, arrival_time, now)

    try:
        data = request_json(f'https://api.adsb.lol/v2/lat/{target_lat}/lon/{target_lon}/dist/150')
        aircraft = unwrap_aircraft(data)
        target_speed = int(float((bootstrap or {}).get('speed') or 900))
        target_heading = int(float((bootstrap or {}).get('dir') or (bootstrap or {}).get('heading') or bearing(departure_coords[0], departure_coords[1], arrival_coords[0], arrival_coords[1])))
        target_airline = str((bootstrap or {}).get('airline_icao') or str(flight.get('flight_number') or '')[:3]).upper()
        best = best_match(
            aircraft,
            target_lat,
            target_lon,
            target_speed,
            target_heading,
            target_airline,
        )
        return best
    except Exception as exc:
        log(f'[AREA SEARCH ERROR] {flight.get("flight_number")}: {exc}')
        return None


def resolve_active_flights(now: datetime) -> List[Dict[str, Any]]:
    today = now.date().isoformat()
    trips_result = (
        supabase.table('trips')
        .select('id, start_date, end_date')
        .lte('start_date', today)
        .gte('end_date', today)
        .execute()
    )

    active_trip_ids = [row['id'] for row in (trips_result.data or [])]
    if not active_trip_ids:
        return []

    flights_result = (
        supabase.table('trip_flights')
        .select('id, trip_id, flight_number, departure_airport, arrival_airport, departure_date, departure_time, arrival_date, arrival_time')
        .in_('trip_id', active_trip_ids)
        .execute()
    )

    flights = flights_result.data or []
    seen = set()
    active: List[Dict[str, Any]] = []

    for flight in flights:
        flight_number = str(flight.get('flight_number') or '').strip().upper()
        if not flight_number or flight_number in seen:
            continue

        departure_time = combine_datetime(flight['departure_date'], flight['departure_time'])
        arrival_time = combine_datetime(flight['arrival_date'], flight['arrival_time'])
        buffered_start = departure_time - timedelta(hours=2)
        buffered_end = arrival_time + timedelta(hours=2)

        if buffered_start <= now <= buffered_end:
            seen.add(flight_number)
            active.append(flight)

    return active


def live_aircraft_from_hex(hex_code: str) -> Optional[Dict[str, Any]]:
    if not hex_code:
        return None
    try:
        data = request_json(f'https://api.adsb.lol/v2/hex/{hex_code}')
        aircraft = unwrap_aircraft(data)
        return aircraft[0] if aircraft else None
    except Exception as exc:
        log(f'[HEX LOOKUP ERROR] {hex_code}: {exc}')
        return None


def estimate_eta(now: datetime, remaining_nm: float, speed_knots: float, scheduled_arrival: datetime) -> datetime:
    if speed_knots <= 0:
        return scheduled_arrival
    eta = now + timedelta(hours=remaining_nm / max(speed_knots, 1.0))
    if eta > scheduled_arrival + timedelta(hours=3):
        return scheduled_arrival
    return eta


def persist_position(payload: Dict[str, Any]) -> None:
    supabase.table('live_flight_positions').upsert(payload, on_conflict='flight_number').execute()


def mark_stale_flights() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    (
        supabase.table('live_flight_positions')
        .update({'status': 'landed', 'is_airborne': False})
        .lt('last_updated', cutoff)
        .execute()
    )


def track_flight(flight: Dict[str, Any], now: datetime) -> None:
    flight_number = str(flight.get('flight_number') or '').strip().upper()
    if not flight_number:
        return

    bootstrap = TRACKING_CACHE.get(flight_number)
    if bootstrap is None:
        bootstrap = {'hex': None, 'callsign': flight_number}
        TRACKING_CACHE[flight_number] = bootstrap

        candidate = adsb_callsign_lookup(flight_number)
        if candidate is None:
            candidate = airlabs_bootstrap(flight_number)
        if candidate is None:
            candidate = area_search_lookup(flight, now, bootstrap)

        if candidate:
            bootstrap['hex'] = candidate.get('hex') or candidate.get('icao24') or candidate.get('hex_ident')
            bootstrap['candidate'] = candidate
            bootstrap['callsign'] = str(candidate.get('flight') or candidate.get('callsign') or flight_number).strip().upper()
            bootstrap['airline_icao'] = candidate.get('airline_icao')
            bootstrap['dir'] = candidate.get('dir') or candidate.get('heading')
            bootstrap['speed'] = candidate.get('speed') or candidate.get('gs')

    live = None
    if bootstrap.get('hex'):
        live = live_aircraft_from_hex(str(bootstrap['hex']))
    if live is None:
        live = bootstrap.get('candidate')

    departure_coords = airport_coords(flight.get('departure_airport'))
    arrival_coords = airport_coords(flight.get('arrival_airport'))
    if not departure_coords or not arrival_coords:
        log(f'Skipping {flight_number}: missing airport coordinates')
        return

    departure_time = combine_datetime(flight['departure_date'], flight['departure_time'])
    arrival_time = combine_datetime(flight['arrival_date'], flight['arrival_time'])
    now_utc = now.astimezone(timezone.utc)
    scheduled_seconds = max(1.0, (arrival_time - departure_time).total_seconds())
    progress = min(1.0, max(0.0, (now_utc - departure_time).total_seconds() / scheduled_seconds))

    if live and live.get('lat') is not None and live.get('lon') is not None:
        lat = float(live.get('lat'))
        lon = float(live.get('lon'))
        altitude = int(float(live.get('alt_baro') or live.get('altitude') or 0))
        speed = int(float(live.get('gs') or live.get('speed') or 0))
        heading = int(float(live.get('track') or live.get('heading') or 0))
        callsign = str(live.get('flight') or live.get('callsign') or bootstrap.get('callsign') or flight_number)
        hex_code = str(live.get('hex') or bootstrap.get('hex') or '')
        source = 'adsb'
        is_airborne = True
        status = 'tracking'
    else:
        lat, lon, _ = interpolate_position(departure_coords, arrival_coords, departure_time, arrival_time, now_utc)
        altitude = 0
        speed = int(float(bootstrap.get('speed') or 450))
        heading = int(float(bootstrap.get('dir') or bearing(departure_coords[0], departure_coords[1], arrival_coords[0], arrival_coords[1])))
        callsign = str(bootstrap.get('callsign') or flight_number)
        hex_code = str(bootstrap.get('hex') or '')
        source = 'scheduled'
        is_airborne = True
        status = 'tracking'

    destination_weather = get_weather(arrival_coords[0], arrival_coords[1])
    weather = weather_score(destination_weather)
    congestion, congestion_count = congestion_metrics(arrival_coords[0], arrival_coords[1])
    remaining_nm = max(0.0, distance(lat, lon, arrival_coords[0], arrival_coords[1]) * 0.539957)
    delay_probability = estimate_delay(altitude, speed, weather, congestion)
    eta = estimate_eta(now_utc, remaining_nm, float(speed or 0), arrival_time)

    persist_position(
        {
            'flight_number': flight_number,
            'lat': lat,
            'lon': lon,
            'altitude': altitude,
            'speed': speed,
            'heading': heading,
            'callsign': callsign,
            'hex': hex_code,
            'departure_airport': flight.get('departure_airport'),
            'arrival_airport': flight.get('arrival_airport'),
            'delay_probability': delay_probability,
            'weather_score': weather,
            'congestion_score': max(congestion, min(100, congestion_count * 4)),
            'estimated_arrival_utc': eta.isoformat(),
            'source': source,
            'last_updated': now_utc.isoformat(),
            'is_airborne': is_airborne,
            'status': status,
        }
    )
    log(f'Tracked {flight_number}: {lat:.4f},{lon:.4f} alt={altitude} speed={speed} heading={heading} delay={delay_probability:.1f}%')


def cycle() -> None:
    now = datetime.now(timezone.utc)
    active_flights = resolve_active_flights(now)
    log(f'=== Flight tracker cycle: tracking {len(active_flights)} active flights ===')

    for flight in active_flights:
        try:
            track_flight(flight, now)
        except Exception as exc:
            log(f'Flight tracking error for {flight.get("flight_number")}: {exc}')

    mark_stale_flights()


def main() -> None:
    log('Flight tracker worker starting up')
    while True:
        try:
            cycle()
            time.sleep(POLL_INTERVAL_SECONDS)
        except Exception as exc:
            log(f'Unhandled tracker error: {exc}')
            time.sleep(60)


if __name__ == '__main__':
    main()