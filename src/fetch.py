"""Parallel fetch of every public list, then dedupe on proto://host:port."""
import concurrent.futures
import json
import urllib.request

from .sources import parse, sources

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_all(workers=12, timeout=20, verbose=True):
    """Return (deduped proxy dicts, per-source report)."""
    jobs = list(sources())
    merged = {}
    report = []

    def work(job):
        url, proto, kind = job
        try:
            body = _get(url, timeout)
            rows = parse(body, proto, kind)
            return url, rows, None
        except Exception as e:  # noqa: BLE001
            return url, [], f"{type(e).__name__}: {e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for url, rows, err in ex.map(work, jobs):
            report.append({"url": url, "count": len(rows), "error": err})
            if verbose:
                mark = "ERR" if err else f"{len(rows):>6}"
                print(f"  {mark}  {url[:88]}")
            for r in rows:
                key = f"{r['proto']}://{r['auth']}{r['ip']}:{r['port']}"
                merged[key] = r

    return list(merged.values()), report


def save_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
