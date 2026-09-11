from datetime import UTC, datetime

from news_curator.models import run_date_for


def test_india_has_no_dst_a_fixed_offset_is_correct():
    # 2026-01-15T19:00:00Z + 5:30 = 2026-01-16T00:30 IST (winter, no DST either way)
    winter = datetime(2026, 1, 15, 19, 0, 0, tzinfo=UTC)
    assert run_date_for("IN", now=winter) == "2026-01-16"


def test_us_central_time_observes_dst_summer():
    # 2026-07-15T04:30:00Z is 2026-07-14 23:30 CDT (UTC-5 in summer) — still
    # the previous calendar day in America/Chicago.
    summer = datetime(2026, 7, 15, 4, 30, 0, tzinfo=UTC)
    assert run_date_for("US", now=summer) == "2026-07-14"


def test_us_central_time_observes_dst_winter():
    # 2026-01-15T05:30:00Z is 2026-01-14 23:30 CST (UTC-6 in winter) — a fixed
    # -5:00 offset would get this wrong.
    winter = datetime(2026, 1, 15, 5, 30, 0, tzinfo=UTC)
    assert run_date_for("US", now=winter) == "2026-01-14"


def test_unknown_country_falls_back_to_india():
    now = datetime(2026, 1, 15, 19, 0, 0, tzinfo=UTC)
    assert run_date_for("FR", now=now) == run_date_for("IN", now=now)
