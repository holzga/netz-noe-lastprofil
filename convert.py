#!/usr/bin/env python3
"""Convert Netz NÖ smart-meter exports to the Lastprofil upload format.

Source files (Jahresverbrauch-YYYY.csv) use naive local Vienna time with
comma-decimal kWh values. The target format (Lastprofilvorlage_YYYY.csv) needs
ISO-8601 timestamps with an explicit UTC offset (+01:00 / +02:00) that flips on
daylight-saving transitions, plus fixed ;QH;KWH; columns.

The script merges both source files, derives the correct DST offset for every
15-minute interval from the data itself (cross-checked against the Europe/Vienna
rule), then prompts for a date range and writes one combined CSV.
"""

import sys
from datetime import datetime, timedelta

# --- configuration ----------------------------------------------------------

SOURCE_FILES = ["Jahresverbrauch-2025.csv", "Jahresverbrauch-2026.csv"]
OUTPUT_FILE = "Lastprofil_export.csv"
HEADER = "Ende Ablesezeitraum;Messintervall;Abrechnungsmaßeinheit;Verbrauch"

QUARTER = timedelta(minutes=15)


# --- parsing ----------------------------------------------------------------

def read_source(path):
    """Yield (naive_datetime, raw_value_str) for each data row in a source CSV."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        next(fh, None)  # skip header
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(";")
            ts, value = parts[0], parts[1]
            naive = datetime.strptime(ts, "%d.%m.%Y %H:%M")
            yield naive, value


# --- daylight-saving handling ----------------------------------------------

def last_sunday(year, month):
    """Date of the last Sunday in the given month."""
    d = datetime(year, month, 31)
    while d.month != month:
        d -= timedelta(days=1)
    while d.weekday() != 6:  # 6 == Sunday
        d -= timedelta(days=1)
    return d


def vienna_offset_hours(naive):
    """Expected UTC offset (1 or 2) for a naive Vienna timestamp per the EU rule.

    DST runs from the last Sunday of March 02:00 (local std) to the last Sunday
    of October 03:00 (local DST). Within the ambiguous fall-back hour this returns
    the daylight value; that ambiguity is resolved by the data-driven detection,
    so this is only a coarse sanity check.
    """
    spring = last_sunday(naive.year, 3).replace(hour=2)
    fall = last_sunday(naive.year, 10).replace(hour=3)
    return 2 if spring <= naive < fall else 1


def assign_offsets(rows):
    """Walk an ordered series, attaching the DST offset (in hours) to each row.

    Detection mirrors the meter's own markers:
      * a forward jump of 75 min (01:45 -> 03:00) = spring forward -> +2
      * any backward step (02:45 -> 02:00)        = fall back      -> +1
    The series starts on Jan 1 (winter, +1). A warning is logged whenever the
    detected offset disagrees with the Europe/Vienna rule, surfacing data gaps.
    """
    offset = 1
    prev = None
    for naive, value in rows:
        if prev is not None:
            delta = naive - prev
            if delta == timedelta(minutes=75):
                offset = 2  # spring forward
            elif delta < timedelta(0):
                offset = 1  # fall back
        expected = vienna_offset_hours(naive)
        # On the fall-back day the first 02:00-02:45 pass is +2 while the rule
        # already reports +1 for that wall-clock hour, so skip the warning there.
        if offset != expected and not (naive.month == 10 and naive.hour == 2):
            log(f"offset {offset:+d}h disagrees with Vienna rule "
                f"{expected:+d}h at {naive:%Y-%m-%d %H:%M} (possible data gap)")
        yield naive, offset, value
        prev = naive


# --- helpers ----------------------------------------------------------------

def log(msg):
    print(f"warning: {msg}", file=sys.stderr)


def load_all():
    """Read and offset-tag every source file, then merge into one ordered list."""
    merged = []
    seen = set()
    for path in SOURCE_FILES:
        for naive, offset, value in assign_offsets(read_source(path)):
            key = (naive, offset)
            if key in seen:
                continue
            seen.add(key)
            merged.append((naive, offset, value))
    # Sort by the true UTC instant so the fall-back hour stays in order
    # (02:00+02:00 precedes 02:00+01:00, which share the same wall-clock time).
    merged.sort(key=lambda r: r[0] - timedelta(hours=r[1]))
    return merged


def format_value(raw):
    """0,021000 -> 0,02100 (5 decimals, comma separator)."""
    return f"{float(raw.replace(',', '.')):.5f}".replace(".", ",")


def format_row(naive, offset, value):
    ts = naive.strftime("%Y-%m-%dT%H:%M") + f"+{offset:02d}:00"
    return f"{ts};QH;KWH;{format_value(value)}"


def latest_complete_day(rows):
    """Last calendar day whose closing interval (next-day 00:00) is present."""
    last_naive = rows[-1][0]
    # The interval stamped D+1 00:00 closes day D.
    if last_naive.hour == 0 and last_naive.minute == 0:
        return (last_naive - QUARTER).date()
    return last_naive.date() - timedelta(days=1)


def rows_in_day_range(rows, start_date, end_date):
    """Rows whose interval belongs to a day in [start_date, end_date] inclusive.

    A day D owns the intervals stamped D 00:15 .. (D+1) 00:00 (end-of-interval).
    """
    lo = datetime.combine(start_date, datetime.min.time()) + QUARTER
    hi = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    return [r for r in rows if lo <= r[0] <= hi]


# --- interactive range selection -------------------------------------------

def parse_date(text):
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def choose_range(rows):
    first_day = (rows[0][0] - QUARTER).date()
    last_day = latest_complete_day(rows)
    print(f"\nAvailable data: {first_day:%Y-%m-%d} .. {last_day:%Y-%m-%d} "
          f"(last complete day: {last_day:%Y-%m-%d})")
    print("\nHow do you want to select the export range?")
    print("  [1] enter start and end dates")
    print("  [2] last N complete days")
    choice = input("Choice [1/2]: ").strip()

    if choice == "2":
        n = int(input("Number of complete days: ").strip())
        end = last_day
        start = end - timedelta(days=n - 1)
        if start < first_day:
            start = first_day
    else:
        start = parse_date(input(f"Start date (YYYY-MM-DD) [{first_day}]: ")
                            or str(first_day))
        end = parse_date(input(f"End date   (YYYY-MM-DD) [{last_day}]: ")
                         or str(last_day))

    if end < start:
        sys.exit("error: end date is before start date")
    return start, end


# --- output -----------------------------------------------------------------

def write_output(rows, path):
    lines = [HEADER] + [format_row(*r) for r in rows]
    data = "\r\n".join(lines) + "\r\n"
    with open(path, "w", encoding="iso-8859-1", newline="") as fh:
        fh.write(data)


def main():
    rows = load_all()
    if not rows:
        sys.exit("error: no data rows found")
    start, end = choose_range(rows)
    selected = rows_in_day_range(rows, start, end)
    if not selected:
        sys.exit("error: no rows in the selected range")
    write_output(selected, OUTPUT_FILE)
    print(f"\nWrote {len(selected)} rows to {OUTPUT_FILE}")
    print(f"  first: {format_row(*selected[0])}")
    print(f"  last:  {format_row(*selected[-1])}")


if __name__ == "__main__":
    main()
