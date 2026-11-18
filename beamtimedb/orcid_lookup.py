import json
import time
from contextlib import suppress
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_API_BASE = "https://pub.orcid.org/v3.0"
_HEADERS = {"Accept": "application/json"}
_TIMEOUT = 10


def _search(query, rows=5):
    """Runs a query against the ORCID public search API, return ORCID id strings."""
    url = f"{_API_BASE}/search?{urlencode({'q': query, 'rows': rows})}"
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return [item["orcid-identifier"]["path"] for item in (data.get("result") or [])]


def find_orcid(last_name, first_name, email=None, affiliation=None):
    """Finds a unique ORCID iD for a person."""
    if email:
        with suppress(HTTPError, URLError):
            hits = _search(f'email:"{email}"')
            if len(hits) == 1:
                return hits[0]

    if last_name and first_name:
        q = f'family-name:"{last_name}" AND given-names:"{first_name}"'
        if affiliation:
            q += f' AND affiliation-org-name:"{affiliation}"'
        with suppress(HTTPError, URLError):
            hits = _search(q)
            if len(hits) == 1:
                return hits[0]

    return None
