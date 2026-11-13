"""地球の今日一日のデータを集める。

取れなかった項目は None のまま返す。日記の側で「測られへんかった」と書けばええ。
"""
from __future__ import annotations

import datetime as dt
import requests

from .moon import moon_phase

UA = {"User-Agent": "earth-diary (https://github.com/) daily bot"}
TIMEOUT = 30

USGS_DAY = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
SWPC_KP = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
SWPC_FLARES = "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json"
# 太陽風は置き場所が変わることがあるので、上から順に試す
SWPC_WIND = [
    "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json",
    "https://services.swpc.noaa.gov/products/solar-wind/plasma-3-day.json",
    "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json",
    "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json",
]


# 息（CO2）・冷え（海氷）・ほかの災害
CO2_DAILY = [
    "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_daily_mlo.csv",
    "https://scrippsco2.ucsd.edu/assets/data/atmospheric/stations/in_situ_co2/daily/daily_in_situ_co2_mlo.csv",
]
SEAICE_HOSTS = [
    "https://noaadata.apps.nsidc.org/NOAA/G02135",
    "https://masie_web.apps.nsidc.org/pub/DATASETS/NOAA/G02135",
]
GDACS = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"


def _text(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def _get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _parse_time(s: str) -> dt.datetime:
    s = s.replace("Z", "").replace("T", " ")
    s = s.split(".")[0]
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)


# ---------- 地震 ----------
def is_grave_quake(e: dict) -> bool:
    """人に被害が出ているかもしれない地震。迷ったら静かな方に倒す。

    USGSの被害推定（PAGER）は後から付くことがあるので、
    推定がまだない時のために地震そのものの情報でも先回りする。
    """
    if e.get("alert") in ("yellow", "orange", "red"):
        return True
    if e["mag"] >= 7.0:
        return True
    depth = e.get("depth")
    if e["mag"] >= 6.0 and depth is not None and depth <= 70:
        return True
    # mmi は震源の真上（海の上のことも多い）のいちばん強い揺れの推定。
    # 被害推定（PAGER）がもう付いていればそっちを信じ、mmi は推定がまだない時だけ使う。
    if e.get("alert") is None and (e.get("mmi") or 0) >= 6:     # 震度でいうとおおむね5強以上
        return True
    if (e.get("cdi") or 0) >= 6:                                # 人が感じた揺れの報告
        return True
    if (e.get("felt") or 0) >= 1000:                            # 揺れを感じた報告が多い
        return True
    if e.get("tsunami") == 1 and e["mag"] >= 6.0:
        return True
    return False


def summarize_quakes(geojson: dict) -> dict:
    feats = geojson.get("features", [])
    mags = []
    events = []
    for f in feats:
        p = f.get("properties", {})
        m = p.get("mag")
        if m is None:
            continue
        mags.append(m)
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        events.append({"mag": round(m, 1), "place": p.get("place") or "", "time": p.get("time"),
                       "alert": p.get("alert"), "depth": coords[2] if len(coords) > 2 else None,
                       "mmi": p.get("mmi"), "cdi": p.get("cdi"), "felt": p.get("felt"),
                       "tsunami": p.get("tsunami")})
    events.sort(key=lambda e: e["mag"], reverse=True)
    near_japan = [e for e in events if "Japan" in e["place"] and e["mag"] >= 4.0]
    grave = [e for e in events if is_grave_quake(e)]
    return {
        "grave": grave[:3],
        "count": len(mags),
        "m5_count": sum(1 for m in mags if m >= 5.0),
        "max_mag": max(mags) if mags else None,
        "top": events[:3],
        "near_japan": near_japan[:3],
    }


def fetch_quakes():
    return summarize_quakes(_get(USGS_DAY))


# ---------- 太陽フレア ----------
FLARE_ORDER = {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}


def flare_value(cls: str | None) -> float:
    """'M2.3' -> 3.23 のように比べやすい数にする。"""
    if not cls:
        return -1
    letter = cls[0].upper()
    try:
        num = float(cls[1:])
    except ValueError:
        num = 1.0
    return FLARE_ORDER.get(letter, -1) + min(num, 9.9) / 10


def summarize_flares(items: list, now: dt.datetime) -> dict:
    since = now - dt.timedelta(hours=24)
    recent = []
    for it in items:
        cls = it.get("max_class") or it.get("current_class")
        t = it.get("max_time") or it.get("begin_time")
        if not cls or not t:
            continue
        try:
            if _parse_time(t) >= since:
                recent.append(cls)
        except ValueError:
            continue
    biggest = max(recent, key=flare_value) if recent else None
    return {"count": len(recent), "max_class": biggest}


def fetch_flares(now):
    return summarize_flares(_get(SWPC_FLARES), now)


# ---------- 地磁気 Kp ----------
def summarize_kp(rows, now: dt.datetime) -> dict:
    """配列形式（先頭が見出し行）とオブジェクト形式の両方を受ける。"""
    since = now - dt.timedelta(hours=24)
    vals = []
    for row in rows:
        if isinstance(row, dict):
            t, kp = row.get("time_tag"), row.get("Kp", row.get("kp_index"))
        else:
            if row and row[0] == "time_tag":
                continue
            t, kp = row[0], row[1]
        try:
            if _parse_time(t) >= since:
                vals.append(float(kp))
        except (TypeError, ValueError):
            continue
    return {"kp_max": max(vals) if vals else None}


def fetch_kp(now):
    return summarize_kp(_get(SWPC_KP), now)


# ---------- 太陽風 ----------
def summarize_wind(rows, now: dt.datetime | None = None) -> dict:
    """配列形式（[time_tag, density, speed, ...]）とオブジェクト形式（proton_speed）の両方を受ける。"""
    since = (now - dt.timedelta(hours=24)) if now else None
    speeds = []
    for row in rows:
        try:
            if isinstance(row, dict):
                t, v = row.get("time_tag"), row.get("proton_speed", row.get("speed"))
            else:
                if not row or row[0] == "time_tag":
                    continue
                t, v = row[0], row[2]
            if since and t and _parse_time(t) < since:
                continue
            speeds.append(float(v))
        except (TypeError, ValueError, IndexError):
            continue
    return {"wind_max": round(max(speeds)) if speeds else None}


def fetch_wind(now):
    last = None
    for url in SWPC_WIND:
        try:
            out = summarize_wind(_get(url), now)
            if out["wind_max"] is not None:
                return out
        except Exception as e:
            last = e
    raise RuntimeError(f"太陽風のデータが見つからんかった: {last}")


# ---------- 息（CO2、マウナロア） ----------
def summarize_co2(text: str) -> dict:
    """年,月,日,…,ppm の行から、いちばん新しい値と一年前の同じころの値を出す。"""
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "%", '"')):
            continue
        cols = [c.strip() for c in line.split(",")]
        try:
            y, m, d = int(cols[0]), int(cols[1]), int(cols[2])
            ppm = float(cols[-1]) if len(cols) <= 5 else float(next(c for c in cols[4:] if c and float(c) > 100))
        except (ValueError, IndexError, StopIteration):
            continue
        if ppm > 100:
            rows.append((dt.date(y, m, d), ppm))
    if not rows:
        return {"ppm": None}
    day, ppm = rows[-1]
    week = [v for t, v in rows if 0 <= (day - t).days < 7]
    ago = [v for t, v in rows if 0 <= (day - t).days - 365 < 7]
    change = round(sum(week) / len(week) - sum(ago) / len(ago), 2) if week and ago else None
    return {"ppm": round(ppm, 2), "date": day.isoformat(), "year_change": change}


def fetch_co2():
    last = None
    for url in CO2_DAILY:
        try:
            out = summarize_co2(_text(url))
            if out["ppm"]:
                return out
        except Exception as e:
            last = e
    raise RuntimeError(f"CO2が取れんかった: {last}")


# ---------- 冷え（北極・南極の海氷） ----------
def _seaice_rows(text: str) -> list[tuple[dt.date, float]]:
    rows = []
    for line in text.splitlines():
        cols = [c.strip() for c in line.split(",")]
        try:
            rows.append((dt.date(int(cols[0]), int(cols[1]), int(cols[2])), float(cols[3])))
        except (ValueError, IndexError):
            continue  # 見出しや単位の行
    return rows


def summarize_seaice(daily: str, clim: str | None = None) -> dict:
    rows = _seaice_rows(daily)
    if not rows:
        return {"extent": None}
    day, ext = rows[-1]
    week = [v for t, v in rows if (day - t).days == 5]
    out = {"extent": round(ext, 2), "date": day.isoformat(),
           "change_5d": round(ext - week[-1], 2) if week else None, "vs_normal": None}
    if clim:
        doy = day.timetuple().tm_yday
        for line in clim.splitlines():
            cols = [c.strip() for c in line.split(",")]
            try:
                if int(cols[0]) == doy:
                    out["vs_normal"] = round(ext - float(cols[1]), 2)  # 1981-2010年の平均との差
                    break
            except (ValueError, IndexError):
                continue
    return out


def fetch_seaice():
    out, last = {}, None
    for pole, p in (("north", "N"), ("south", "S")):
        for host in SEAICE_HOSTS:
            try:
                daily = _text(f"{host}/{pole}/daily/data/{p}_seaice_extent_daily_v4.0.csv")
                try:
                    clim = _text(f"{host}/{pole}/daily/data/{p}_seaice_extent_climatology_1981-2010_v4.0.csv")
                except Exception:
                    clim = None
                out[pole] = summarize_seaice(daily, clim)
                break
            except Exception as e:
                last = e
    if not out:
        raise RuntimeError(f"海氷が取れんかった: {last}")
    return out


# ---------- ほかの災害（台風・洪水・火山・山火事、GDACS） ----------
HAZARD_JA = {"TC": "台風・サイクロン", "FL": "洪水", "VO": "火山", "WF": "山火事"}


def summarize_hazards(geo: dict, now: dt.datetime) -> dict:
    """今まさに続いている出来事だけ。干ばつは毎日ほぼ同じなので入れない。地震はUSGSで見る。"""
    since = now - dt.timedelta(hours=36)
    events = []
    for f in geo.get("features") or []:
        p = f.get("properties") or {}
        kind = p.get("eventtype")
        if kind not in HAZARD_JA:
            continue
        try:
            if p.get("todate") and _parse_time(p["todate"]) < since:
                continue
        except ValueError:
            pass
        events.append({
            "type": kind, "kind_ja": HAZARD_JA[kind],
            "name": p.get("eventname") or p.get("name") or "",
            "country": p.get("country") or "",
            "alert": (p.get("alertlevel") or "").lower(),
            "severity": ((p.get("severitydata") or {}).get("severitytext") or "")[:120],
        })
    rank = {"red": 0, "orange": 1, "green": 2}
    events.sort(key=lambda e: rank.get(e["alert"], 3))
    grave = [e for e in events if e["alert"] in ("orange", "red")]
    return {"count": len(events), "events": events[:5], "grave": grave[:3]}


def fetch_hazards(now):
    r = requests.get(GDACS, headers=UA, timeout=TIMEOUT, params={
        "eventlist": "TC;FL;VO;WF",
        "fromdate": (now - dt.timedelta(days=10)).strftime("%Y-%m-%d"),
        "todate": now.strftime("%Y-%m-%d"),
        "alertlevel": "green;orange;red",
    })
    r.raise_for_status()
    return summarize_hazards(r.json() if r.text.strip() else {}, now)


# ---------- まとめ ----------
def collect(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    data = {"utc": now.strftime("%Y-%m-%d %H:%M"), "errors": []}
    steps = {
        "quakes": fetch_quakes,
        "flares": lambda: fetch_flares(now),
        "kp": lambda: fetch_kp(now),
        "wind": lambda: fetch_wind(now),
        "co2": fetch_co2,
        "seaice": fetch_seaice,
        "hazards": lambda: fetch_hazards(now),
    }
    for key, fn in steps.items():
        try:
            data[key] = fn()
        except Exception as e:  # 取れんかった日は取れんかったと記録する
            data[key] = None
            data["errors"].append(f"{key}: {e}")
    data["moon"] = moon_phase(now)
    return data
