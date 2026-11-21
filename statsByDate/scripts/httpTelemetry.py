"""Opt-in, best-effort HTTP call counts for StatsByDate Python subprocesses.

Counts requests.Session.send and urllib.request.urlopen calls. Does not inspect
payloads or change responses. Redirects, lower-level clients and external tools
are outside this metric; unknown must never be reported as zero.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

LOG = os.environ.get('STATS_METRICS_LOG')


def _record(url, success):
    if not LOG:
        return
    try:
        host = (urlsplit(str(url)).hostname or '').lower()
        source = ('NHL' if host.endswith('nhl.com') or host.endswith('nhle.com') else
                  'AHL' if 'theahl.com' in host or 'hockeytech' in host else 'OTHER')
        Path(LOG).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps({'kind': 'http', 'source': source,
                                      'success': bool(success)}) + '\n').encode())
        finally:
            os.close(fd)
    except Exception:
        pass  # Metrics must never break statistics fetching.


if LOG:
    try:
        import urllib.request
        _urlopen = urllib.request.urlopen

        def _counted_urlopen(url, *args, **kwargs):
            target = getattr(url, 'full_url', url)
            try:
                response = _urlopen(url, *args, **kwargs)
            except Exception:
                _record(target, False)
                raise
            _record(target, getattr(response, 'status', 200) < 400)
            return response

        urllib.request.urlopen = _counted_urlopen
    except ImportError:
        pass
    try:
        import requests
        _send = requests.sessions.Session.send

        def _counted_send(self, request, **kwargs):
            try:
                response = _send(self, request, **kwargs)
            except Exception:
                _record(request.url, False)
                raise
            _record(request.url, response.status_code < 400)
            return response

        requests.sessions.Session.send = _counted_send
    except ImportError:
        pass
