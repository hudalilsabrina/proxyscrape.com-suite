"""Public free-proxy list endpoints and their line parsers.

One endpoint yields a few hundred stale entries; twenty yield tens of thousands
after dedupe. Everything here is plain text or JSON over HTTPS.
"""
import json

PROXYSCRAPE = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text",
]

GITHUB_RAW = [
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", "http"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt", "http"),
    ("https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", "socks5"),
    ("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt", "http"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt", None),
]

JSON_APIS = [
    ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc", "geonode"),
    ("https://api.openproxylist.xyz/http.txt", "http"),
]


def sources():
    """Yield (url, proto_hint, kind) for every configured endpoint."""
    for u in PROXYSCRAPE:
        proto = "socks5" if "socks5" in u else "socks4" if "socks4" in u else "http"
        yield u, proto, "text"
    for u, proto in GITHUB_RAW:
        yield u, proto, "text"
    for u, kind in JSON_APIS:
        yield u, ("http" if kind != "geonode" else None), kind


def parse_text(body, proto_hint):
    """Parse `ip:port`, `user:pass@ip:port`, `proto://[user:pass@]ip:port`."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        proto = proto_hint or "http"
        if "://" in line:
            proto, _, line = line.partition("://")
        auth = ""
        if "@" in line:
            auth, _, line = line.rpartition("@")
            auth += "@"
        if line.count(":") != 1:
            continue
        host, _, port = line.partition(":")
        if not host or not port.isdigit():
            continue
        out.append({"proto": proto.lower(), "ip": host, "port": int(port), "auth": auth})
    return out


def parse_geonode(body):
    try:
        data = json.loads(body)
    except Exception:
        return []
    out = []
    for row in data.get("data", []):
        protos = row.get("protocols") or []
        proto = "socks5" if "socks5" in protos else "http"
        ip, port = row.get("ip"), row.get("port")
        if ip and port:
            out.append({"proto": proto, "ip": ip, "port": int(port), "auth": ""})
    return out


def parse(body, proto_hint, kind):
    if kind == "geonode":
        return parse_geonode(body)
    return parse_text(body, proto_hint)
