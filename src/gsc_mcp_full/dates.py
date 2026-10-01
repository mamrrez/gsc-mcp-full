"""Date ranges the way Search Console counts them.

Search Console days are **Pacific Time** days (UTC−7/−8). For a site in
Tehran (UTC+3:30) or Tokyo (UTC+9) the report's "Monday" is not the local
Monday — it runs from Monday ~10:30/16:00 local into Tuesday. Daily data
cannot be re-cut; hourly data (last 10 days) can, see :func:`bucket_hours`.

Data for the last ~3 days is provisional and keeps changing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
FINAL_LAG_DAYS = 3  # data older than this is final in practice
MAX_HISTORY_DAYS = 16 * 30 + 10  # the API keeps about 16 months

PERIODS = (
    "today",
    "yesterday",
    "last_7_days",
    "last_28_days",
    "last_3_months",
    "last_6_months",
    "last_12_months",
    "last_16_months",
    "this_month",
    "last_month",
)


def today_pacific() -> date:
    return datetime.now(PACIFIC).date()


def parse_date(s: str) -> date:
    s = s.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError as e:
        raise ValueError(f"dates must be YYYY-MM-DD, got {s!r}") from e


def _minus_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28)


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def start_iso(self) -> str:
        return self.start.isoformat()

    @property
    def end_iso(self) -> str:
        return self.end.isoformat()

    def __str__(self) -> str:
        return f"{self.start_iso} → {self.end_iso} ({self.days} days)"

    def previous(self) -> DateRange:
        """The same number of days immediately before this range."""
        end = self.start - timedelta(days=1)
        return DateRange(end - timedelta(days=self.days - 1), end)

    def year_ago(self) -> DateRange:
        """The same calendar dates one year earlier (29 Feb maps to 28 Feb)."""
        return DateRange(_minus_year(self.start), _minus_year(self.end))

    def weeks_52_ago(self) -> DateRange:
        """364 days earlier, which keeps weekdays aligned."""
        return DateRange(self.start - timedelta(days=364), self.end - timedelta(days=364))


def resolve_range(
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
    period: str | None = None,
    lag: int = 1,
) -> DateRange:
    """Turn whatever the caller gave into a concrete range.

    Priority: explicit ``start``/``end`` > ``period`` name > ``days`` (default 28).
    ``lag`` is how many days before today the range ends by default (1 = yesterday),
    because today's data is nearly empty for most of the day.
    """
    today = today_pacific()
    if start or end:
        s = parse_date(start) if start else None
        e = parse_date(end) if end else today - timedelta(days=lag)
        if s is None:
            s = e - timedelta(days=(days or 28) - 1)
        if s > e:
            raise ValueError(f"start {s} is after end {e}")
        return DateRange(s, e)
    if period:
        p = period.strip().lower().replace(" ", "_").replace("-", "_")
        if p == "today":
            return DateRange(today, today)
        if p == "yesterday":
            y = today - timedelta(days=1)
            return DateRange(y, y)
        if p == "this_month":
            return DateRange(today.replace(day=1), today - timedelta(days=lag) if today.day > lag else today)
        if p == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            return DateRange(last_prev.replace(day=1), last_prev)
        table = {
            "last_7_days": 7,
            "last_28_days": 28,
            "last_3_months": 91,
            "last_6_months": 182,
            "last_12_months": 365,
            "last_16_months": MAX_HISTORY_DAYS,
        }
        if p not in table:
            raise ValueError(f"unknown period {period!r}; use one of {', '.join(PERIODS)} or start/end dates")
        days = table[p]
    if days is not None and days < 1:
        raise ValueError("days must be at least 1")
    n = days or 28
    e = today - timedelta(days=lag)
    return DateRange(e - timedelta(days=n - 1), e)


def is_final(d: date) -> bool:
    return d <= today_pacific() - timedelta(days=FINAL_LAG_DAYS)


def parse_hour(s: str) -> datetime:
    """The API's hour strings: ``2026-09-27T14:00:00-07:00``."""
    return datetime.fromisoformat(s)


def bucket_hours(rows: list[dict], tz: str, by: str = "day") -> list[dict]:
    """Re-bucket hourly rows (``keys[0]`` = hour string) into local ``day`` or ``hour`` buckets.

    Each output dict has ``bucket``, ``clicks``, ``impressions``, ``ctr``, ``position``.
    This is the only way to get a *local* day out of Search Console.
    """
    zone = ZoneInfo(tz)
    agg: dict[str, dict] = {}
    for r in rows:
        hour = parse_hour(r["keys"][0]).astimezone(zone)
        # %H:%M, not %H:00: Tehran, Delhi and Kathmandu sit on :30 and :45 offsets.
        b = hour.date().isoformat() if by == "day" else hour.strftime("%Y-%m-%d %H:%M")
        a = agg.setdefault(b, {"bucket": b, "clicks": 0, "impressions": 0, "_pw": 0.0})
        imps = int(r.get("impressions", 0))
        a["clicks"] += int(r.get("clicks", 0))
        a["impressions"] += imps
        a["_pw"] += float(r.get("position", 0)) * imps
    out = []
    for a in sorted(agg.values(), key=lambda x: x["bucket"]):
        imps = a["impressions"]
        a["ctr"] = round(a["clicks"] / imps, 4) if imps else 0.0
        a["position"] = round(a["_pw"] / imps, 2) if imps else 0.0
        del a["_pw"]
        out.append(a)
    return out


def local_day_note(tz: str | None) -> str:
    if not tz:
        return "Dates are Search Console days (Pacific Time, UTC−7/−8), not local days."
    try:
        offset = datetime.now(ZoneInfo(tz)).utcoffset()
    except Exception:
        return f"Unknown timezone {tz!r}; dates are Pacific Time days."
    return (
        f"Dates are Search Console days in Pacific Time; {tz} is {offset} from UTC, so each "
        "report day starts mid-morning or later local time. Use hourly_performance for local days."
    )
