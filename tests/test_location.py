from bot.utils.location import haversine

def test_haversine_distance():
    # Berlin Alexanderplatz to Potsdamer Platz (~3km)
    lat1, lon1 = 52.5219, 13.4132
    lat2, lon2 = 52.5096, 13.3759
    
    distance = haversine(lat1, lon1, lat2, lon2)
    assert 2800 < distance < 3200

def test_haversine_same_point():
    lat, lon = 52.5, 13.4
    assert haversine(lat, lon, lat, lon) == 0

def test_haversine_nearby():
    # 100m distance
    lat1, lon1 = 52.5, 13.4
    lat2, lon2 = 52.5, 13.40147 # approx 100m east at this latitude
    distance = haversine(lat1, lon1, lat2, lon2)
    assert 90 < distance < 110
