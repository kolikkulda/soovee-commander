"""Legacy FTP LIST formats used by Unix servers and Windows/IIS appliances."""
import re
from datetime import datetime, timedelta

from .providers import Entry, safe_name


def parse_listing(lines):
    entries = []
    now = datetime.now()
    months = dict(zip("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), range(1, 13)))
    for line in lines:
        if not line.strip() or line.startswith("total "):
            continue
        dos = re.match(r"^(\d{2,4})-(\d{2})-(\d{2,4})\s+(\d{1,2}):(\d{2})(AM|PM)?\s+(<DIR>|\d+)\s+(.*)$", line, re.I)
        try:
            if dos:
                month, day, year, hour, minute, meridiem, size, name = dos.groups()
                year = int(year)
                if year < 100:
                    year += 2000 if year < 70 else 1900
                hour = int(hour)
                if meridiem:
                    hour = hour % 12 + (12 if meridiem.upper() == "PM" else 0)
                modified = datetime(year, int(month), int(day), hour, int(minute)).timestamp()
                directory, link = size.upper() == "<DIR>", False
                size = 0 if directory else int(size)
            else:
                parts = line.split(None, 8)
                if len(parts) != 9 or parts[0][0] not in "-dl":
                    raise ValueError('Unsupported FTP LIST format: ' + line)
                mode, _, owner, group, size, month, day, clock, name = parts
                directory, link, size = mode[0] == "d", mode[0] == "l", int(size)
                if link:
                    name = name.split(" -> ", 1)[0]
                if ":" in clock:
                    hour, minute = map(int, clock.split(":"))
                    stamp = datetime(now.year, months[month], int(day), hour, minute)
                    if stamp > now + timedelta(days=1):
                        stamp = stamp.replace(year=now.year - 1)
                else:
                    stamp = datetime(int(clock), months[month], int(day))
                modified = stamp.timestamp()
            if name in (".", ".."):
                continue
            safe_name(name)
            entries.append(Entry(name, directory, size, modified, link))
        except (ValueError, KeyError, OverflowError) as exc:
            raise ValueError('Cannot interpret FTP directory entry: ' + line) from exc
    return entries
