"""月齢をネットなしで計算する（基準の新月からの経過日数）。"""
from __future__ import annotations

import datetime as dt

SYNODIC = 29.530588853
REF_NEW_MOON = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)

NAMES = [
    (1.0, "新月", "new moon"),
    (6.4, "三日月", "waxing crescent"),
    (8.4, "上弦", "first quarter"),
    (13.8, "満ちていく月", "waxing gibbous"),
    (15.8, "満月", "full moon"),
    (21.1, "欠けていく月", "waning gibbous"),
    (23.1, "下弦", "last quarter"),
    (28.5, "細い月", "waning crescent"),
    (99, "新月", "new moon"),
]


def moon_phase(when: dt.datetime) -> dict:
    age = ((when - REF_NEW_MOON).total_seconds() / 86400) % SYNODIC
    for limit, ja, en in NAMES:
        if age < limit:
            return {"age": round(age, 1), "ja": ja, "en": en}
    return {"age": round(age, 1), "ja": "新月", "en": "new moon"}
