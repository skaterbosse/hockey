"""Recovery policy: UTC, conservative deadline if actual end is unavailable."""
from datetime import datetime, timedelta, timezone
import re
from getGamePlayerStats import ahl_root, unpack_jsonp

FINAL = {'FINAL', 'OFF'}

def timestamp(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Missing timezone')
    return t.astimezone(timezone.utc)

def end_reference(game, root):
    start = timestamp(game['StartUTC'])
    # AHL exposes local endTime and duration. Require consistent values and identity.
    if game['League'] == 'AHL':
        try:
            p = root/'raw/games/AHL'/game['GameID']/'gameSummary.json'
            d = ahl_root(unpack_jsonp(p.read_text(encoding='utf-8-sig')))['details']
            if str(d['id']) != game['GameID'] or str(d['final']) != '1':
                raise ValueError('not final')
            local = datetime.fromisoformat(d['GameDateISO8601'])
            if local.tzinfo is None or abs((local-start).total_seconds()) > 60:
                raise ValueError('start mismatch')
            m = re.fullmatch(r'(\d+):(\d{2})', d['duration'])
            if not m or int(m[2]) >= 60:
                raise ValueError('duration')
            duration = timedelta(hours=int(m[1]), minutes=int(m[2]))
            if not timedelta(hours=1) <= duration <= timedelta(hours=12):
                raise ValueError('duration range')
            end = local + duration
            clock, zone = d['endTime'].rsplit(' ',1)
            offsets = {'EST':-5,'EDT':-4,'CST':-6,'CDT':-5,'MST':-7,'MDT':-6,'PST':-8,'PDT':-7,'AST':-4,'ADT':-3}
            if end.utcoffset() != timedelta(hours=offsets[zone]) or end.time().replace(second=0,microsecond=0) != datetime.strptime(clock.upper(),'%I:%M %p').time():
                raise ValueError('end mismatch')
            return end.astimezone(timezone.utc), 'AHL_REPORTED_END'
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            pass
    return start, 'SCHEDULED_START_CONSERVATIVE'

def decision(game, quality, now, reference, hours, last_attempt=None, interval=30):
    if game['Status'] not in FINAL or quality.get('gameStatus') not in FINAL:
        return 'NOT_FINAL'
    if quality.get('qualityStatus') == 'COMPLETE':
        return 'COMPLETE'
    if quality.get('qualityStatus') != 'INCOMPLETE':
        return 'UNKNOWN_QUALITY'
    if 'FETCH_MATCH_DATA' not in quality.get('requiredActions', []):
        return 'NO_STATS_ACTION'
    if reference is None or reference > now:
        return 'UNKNOWN_TIME'
    if now >= reference + timedelta(hours=hours):
        return 'EXPIRED'
    if last_attempt is not None and now < last_attempt + timedelta(minutes=interval):
        return 'COOLDOWN'
    return 'RECOVER'
