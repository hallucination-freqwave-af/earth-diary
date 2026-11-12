"""ネットなしで通すテスト：python -m pytest tests -q（または python tests/test_offline.py）"""
import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from earth_diary import fetch, mood, video, write
from earth_diary.moon import moon_phase

NOW = dt.datetime(2026, 11, 11, 21, 47, tzinfo=dt.timezone.utc)


def quake_geojson(mags):
    return {"features": [{"properties": {"mag": m, "place": f"spot {i} Japan" if i == 0 else f"spot {i}",
                                          "time": 0}} for i, m in enumerate(mags)]}


def test_summaries():
    q = fetch.summarize_quakes(quake_geojson([5.1, 4.6, 2.0, 5.1, None]))
    assert q["count"] == 4 and q["m5_count"] == 2 and q["max_mag"] == 5.1
    assert q["near_japan"][0]["mag"] == 5.1

    flares = [
        {"max_class": "C3.0", "max_time": "2026-11-11T17:51:00Z"},
        {"max_class": "M1.2", "max_time": "2026-11-09T10:00:00Z"},  # 24時間より前
    ]
    assert fetch.summarize_flares(flares, NOW) == {"count": 1, "max_class": "C3.0"}

    kp_rows = [["time_tag", "Kp", "a_running", "station_count"],
               ["2026-11-11 00:00:00.000", "2.67", "12", "8"],
               ["2026-11-11 18:00:00.000", "3.00", "15", "8"],
               ["2026-11-09 18:00:00.000", "6.00", "80", "8"]]
    assert fetch.summarize_kp(kp_rows, NOW) == {"kp_max": 3.0}
    assert fetch.summarize_kp([{"time_tag": "2026-11-11T20:00:00", "Kp": 1.67}], NOW) == {"kp_max": 1.67}

    wind = [["time_tag", "density", "speed", "temperature"], ["x", "3", "512.4", "1"], ["y", "2", None, "1"]]
    assert fetch.summarize_wind(wind) == {"wind_max": 512}
    rtsw = [{"time_tag": "2026-11-11T21:40:00", "proton_speed": 612.3},
            {"time_tag": "2026-11-09T21:40:00", "proton_speed": 900.0}]  # 24時間より前は数えない
    assert fetch.summarize_wind(rtsw, NOW) == {"wind_max": 612}


def data(kp, flare, mags, wind):
    return {"quakes": fetch.summarize_quakes(quake_geojson(mags)),
            "flares": {"count": 1, "max_class": flare}, "kp": {"kp_max": kp},
            "wind": {"wind_max": wind}, "moon": moon_phase(NOW), "errors": []}


QUIET_DAY = data(1.67, "B5.0", [4.2, 3.0], 400)
NORMAL_DAY = data(3.0, "C3.0", [5.1, 5.1, 4.6], 520)   # 11/11 の実際に近い日
HONEST_DAY = data(4.33, "M2.0", [6.1], 600)
LOUD_DAY = data(8.0, "X5.1", [5.7, 4.9], 969)          # 2025/11/12 の実際に近い日


def test_moods():
    assert mood.raw_mood(QUIET_DAY) == mood.QUIET
    assert mood.raw_mood(NORMAL_DAY) == mood.TATSUKAN
    assert mood.raw_mood(HONEST_DAY) == mood.SHOJIKI
    assert mood.raw_mood(LOUD_DAY) == mood.URUSAI
    # 測れんかった日でも落ちない
    assert mood.raw_mood({"quakes": None, "flares": None, "kp": None, "wind": None}) == mood.QUIET


def test_satori():
    q = {"raw": mood.QUIET, "mood": mood.QUIET}
    assert mood.decide(QUIET_DAY, [q, q]) == mood.QUIET                 # 2日では来ない
    assert mood.decide(QUIET_DAY, [q, q, q]) == mood.SATORI             # 3日続いた後に来る
    s = {"raw": mood.QUIET, "mood": mood.SATORI}
    assert mood.decide(QUIET_DAY, [s, q, q, q]) == mood.QUIET           # 最近来たばかりなら来ない
    assert mood.decide(LOUD_DAY, [q, q, q]) == mood.URUSAI              # 荒れた日は悟らない


def test_moon():
    m = moon_phase(NOW)
    assert m["ja"] == "三日月" and 1 < m["age"] < 4   # 11/9 が新月


def test_compose():
    text = write.compose("11月12日", {"ja": "もうええて。", "en": "Enough already."}, LOUD_DAY, mood.URUSAI)
    assert text.index("もうええて") < text.index("Enough") < text.index("判定：うるさい")
    assert "最大フレア X5.1" in text and "Kp 8" in text and "969km/s" in text
    facts = write.facts_for_prompt(LOUD_DAY, mood.URUSAI)
    assert "M5.7" in facts and "日本の近く" in facts
    assert "X5.1" not in facts and "大きい" in facts and "激しい嵐" in facts   # フレア記号は渡さない
    # 11/12の実データ：M5以上8回はふつうの範囲、正直にはならない
    real = data(2.67, "M1.7", [5.4, 5.1, 5.1, 5.0, 5.0, 5.0, 5.0, 5.0], None)
    assert mood.raw_mood(real) == mood.TATSUKAN


def test_grave_day():
    gj = quake_geojson([6.4, 4.0])
    gj["features"][0]["properties"]["alert"] = "orange"
    d = dict(LOUD_DAY, quakes=fetch.summarize_quakes(gj))
    assert write.is_grave(d) and not write.is_grave(QUIET_DAY)
    assert write.human_stance("被害の恐れ", "x") == "皮膚の上"
    big = dict(QUIET_DAY, quakes=fetch.summarize_quakes(quake_geojson([7.1])))
    assert write.is_grave(big)
    # 被害推定がまだなくても、浅いM6・強い揺れ・多くの報告で静かに倒す
    g = lambda **kw: fetch.is_grave_quake({"mag": 5.0, **kw})
    assert fetch.is_grave_quake({"mag": 6.2, "depth": 30})
    assert not fetch.is_grave_quake({"mag": 6.2, "depth": 300})
    assert g(mmi=6.4) and g(felt=2500) and not g(felt=40) and not g()


def test_parse_diary():
    tagged = "<ja>\nもうええて。\n寝る。\n</ja>\n<en>\nEnough.\nGoing to bed.\n</en>"
    assert write.parse_diary(tagged) == {"ja": "もうええて。\n寝る。", "en": "Enough.\nGoing to bed."}
    raw_json = '{"ja": "一行目\n二行目", "en": "line one\nline two"}'  # 生の改行入り（今回落ちた形）
    assert write.parse_diary(raw_json)["ja"] == "一行目\n二行目"


def test_slots():
    s = video.slots(NOW)
    assert len(s) == 71 and s[0] == "2150" and s[-1] == "2110"


def fake_earth(n):
    out = []
    for i in range(n):
        im = Image.new("RGB", (550, 550), "black")
        d = ImageDraw.Draw(im)
        d.ellipse((25, 25, 525, 525), fill=(20, 60, 140))
        x = 25 + int(500 * i / n)
        d.rectangle((x, 25, x + 120, 525), fill=(5, 10, 25))  # 夜が横切る
        out.append(im)
    return out


def test_video():
    if not shutil.which("ffmpeg"):
        return
    sun = Image.new("RGB", (512, 512), (230, 160, 40))
    with tempfile.TemporaryDirectory() as tmp:
        quiet = video.make_video(mood.TATSUKAN, Path(tmp) / "q.mp4", now=NOW, earth_frames=fake_earth(40))
        loud = video.make_video(mood.URUSAI, Path(tmp) / "l.mp4", now=NOW, earth_frames=fake_earth(40),
                                sun_image=sun)
        assert quiet.stat().st_size > 10_000 and loud.stat().st_size > 10_000
        assert video.make_video(mood.TATSUKAN, Path(tmp) / "x.mp4", now=NOW, earth_frames=fake_earth(5)) is None
        keep = os.environ.get("KEEP_VIDEO")
        if keep:
            shutil.copy(loud, keep)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
