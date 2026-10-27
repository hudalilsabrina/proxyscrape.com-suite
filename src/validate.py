"""Two-stage proxy validation.

Stage 1 (cheap, parallel): TCP connect, then an HTTP GET through the proxy to
learn the EGRESS IP. Stage 2 (expensive, serial): confirm inside Chromium,
because a proxy that answers urllib can still hang on the browser's CONNECT
handshake.

Also drops transparent proxies: if the egress IP equals our own public IP the
"proxy" is not proxying at all.
"""
import concurrent.futures
import json
import socket
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")


def my_ip(timeout=12):
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def _proxy_url(row):
    auth = row.get("auth") or ""
    return f"http://{auth}{row['ip']}:{row['port']}"


def _http_via(row, url, timeout):
    """GET url through the proxy; returns body text."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": _proxy_url(row), "https": _proxy_url(row)}))
    opener.addheaders = [("User-Agent", UA)]
    with opener.open(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _socks_via(row, url, timeout):
    import socks  # pysocks
    kind = socks.SOCKS5 if row["proto"] == "socks5" else socks.SOCKS4
    host, _, rest = url.partition("://")
    auth = (row.get("auth") or "").rstrip("@")
    user, _, pwd = auth.partition(":")
    s = socks.socksocket()
    s.set_proxy(kind, row["ip"], row["port"], username=user or None, password=pwd or None)
    s.settimeout(timeout)
    s.connect((rest.split("/")[0], 443 if host == "https" else 80))
    s.close()
    return ""  # tunnel established is enough for stage 1 on socks


def check_one(row, cfg):
    """Stage 1 for a single proxy."""
    t0 = time.time()
    res = dict(row)
    res.update({"alive": False, "egress_ip": None, "transparent": False,
                "https_ok": False, "latency_ms": None, "error": None})
    try:
        socket.create_connection((row["ip"], row["port"]), timeout=cfg["connect_timeout"]).close()
    except Exception as e:  # noqa: BLE001
        res["error"] = f"tcp:{type(e).__name__}"
        return res
    try:
        if row["proto"] == "http":
            body = _http_via(row, cfg["check_url"], cfg["http_timeout"])
            try:
                res["egress_ip"] = json.loads(body).get("origin", "").split(",")[0].strip()
            except Exception:
                res["egress_ip"] = body.strip()[:64]
        else:
            _socks_via(row, cfg["https_url"], cfg["http_timeout"])
            res["egress_ip"] = "socks-tunnel-ok"
        res["latency_ms"] = int((time.time() - t0) * 1000)
        res["alive"] = True
    except Exception as e:  # noqa: BLE001
        res["error"] = f"http:{type(e).__name__}"
        return res
    # https capability probe
    try:
        if row["proto"] == "http":
            _http_via(row, cfg["https_url"], cfg["http_timeout"])
        res["https_ok"] = True
    except Exception:
        res["https_ok"] = False
    return res


def validate_stage1(rows, cfg, my_public_ip=None, verbose=True):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["workers"]) as ex:
        futs = {ex.submit(check_one, r, cfg): r for r in rows}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            done += 1
            try:
                results.append(fut.result())
            except Exception:
                pass
            if verbose and done % 500 == 0:
                alive = sum(1 for x in results if x.get("alive"))
                print(f"  probed {done}/{len(rows)}  alive={alive}")
    if my_public_ip:
        for r in results:
            if r.get("egress_ip") == my_public_ip:
                r["transparent"] = True
    return results


def confirm_browser(rows, cfg, limit=40, timeout=25, verbose=True):
    """Stage 2: prove the survivors work in a real browser."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  browser stage skipped (playwright unavailable: {e})")
        return rows
    targets = [r for r in rows if r.get("alive")][:limit]
    if not targets:
        return rows
    if verbose:
        print(f"  browser-confirming {len(targets)} proxies...")
    ok = 0
    with sync_playwright() as p:
        for r in targets:
            try:
                b = p.chromium.launch(headless=True, args=["--no-sandbox"],
                                      proxy={"server": f"http://{r['ip']}:{r['port']}"})
                page = b.new_page()
                page.goto(cfg["https_url"], timeout=timeout * 1000)
                body = page.inner_text("body").strip()
                r["browser_ok"] = body[:64]
                ok += 1
                b.close()
            except Exception:
                r["browser_ok"] = None
                try:
                    b.close()
                except Exception:
                    pass
    if verbose:
        print(f"  browser-confirmed: {ok}/{len(targets)}")
    return rows
