import math


def _clip01(value):
    return max(0.0, min(1.0, float(value)))


def monod_limit(value, half_saturation):
    if half_saturation <= 0:
        raise ValueError("half_saturation must be positive")
    if value <= 0:
        return 0.0
    return _clip01(value / (value + half_saturation))


def temperature_limit(temp_c, optimum_c=28.0, width_c=12.0):
    if width_c <= 0:
        raise ValueError("width_c must be positive")
    distance = (float(temp_c) - optimum_c) / width_c
    return _clip01(math.exp(-(distance * distance)))


def _radiation_limit(value):
    return monod_limit(max(0.0, float(value)), 12.0)


def _wind_shelter_limit(value):
    wind = max(0.0, float(value))
    return _clip01(1.0 / (1.0 + wind / 2.0))


def mechanism_risk_index(sample):
    temp = float(sample.get("water_temperature_C", sample.get("air_temperature_C", 20.0)))
    phosphorus = float(sample.get("total_phosphorus_mg_L", 0.05))
    nitrogen = float(sample.get("total_nitrogen_mg_L", 1.0))
    radiation = float(sample.get("solar_radiation_MJ_m2_day", 12.0))
    wind = float(sample.get("wind_speed_m_s", 2.0))

    components = {
        "temperature_limit": temperature_limit(temp),
        "phosphorus_limit": monod_limit(phosphorus, 0.05),
        "nitrogen_limit": monod_limit(nitrogen, 0.50),
        "radiation_limit": _radiation_limit(radiation),
        "wind_shelter_limit": _wind_shelter_limit(wind),
    }
    risk = (
        0.30 * components["temperature_limit"]
        + 0.22 * components["phosphorus_limit"]
        + 0.16 * components["nitrogen_limit"]
        + 0.17 * components["radiation_limit"]
        + 0.15 * components["wind_shelter_limit"]
    )

    return {
        "model": "logistic_monod_mechanism",
        "risk_score": _clip01(risk),
        "components": components,
        "boundary": "mechanism prototype; not calibrated with final real labels",
    }

