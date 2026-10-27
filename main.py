#!/usr/bin/env python3
"""ProxyScrape Suite - harvest, validate, and export free proxy pools.

  ./run.sh fetch                  # pull every public list -> data/raw.jsonl
  ./run.sh validate --limit 3000  # stage 1 + browser confirm -> data/alive.jsonl
  ./run.sh export                 # out/proxies.txt + out/proxies.json
  ./run.sh run --limit 3000       # all three
  ./run.sh stats
"""
import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from src.fetch import fetch_all, load_jsonl, save_jsonl
from src.validate import confirm_browser, my_ip, validate_stage1

DATA = BASE / "data"
OUT = BASE / "out"
RAW = DATA / "raw.jsonl"
ALIVE = DATA / "alive.jsonl"


def load_cfg():
    with open(BASE / "config.toml", "rb") as f:
        return tomllib.load(f)


def cmd_fetch(cfg, args):
    print("Fetching public proxy lists...")
    rows, report = fetch_all(workers=cfg["fetch"]["workers"], timeout=cfg["fetch"]["timeout"])
    DATA.mkdir(exist_ok=True)
    save_jsonl(RAW, rows)
    bad = [r for r in report if r["error"]]
    print(f"\nUnique proxies: {len(rows)} from {len(report)} sources ({len(bad)} failed)")
    return 0


def cmd_validate(cfg, args):
    if not RAW.exists():
        print("data/raw.jsonl missing - run `fetch` first")
        return 1
    rows = load_jsonl(RAW)
    allowed = set(args.ports or cfg["validate"]["ports"])
    before = len(rows)
    rows = [r for r in rows if r["port"] in allowed]
    print(f"Port filter {sorted(allowed)}: {before} -> {len(rows)}")
    if args.limit:
        rows = rows[: args.limit]
        print(f"Limit applied: probing {len(rows)}")

    mine = my_ip()
    print(f"Our public IP: {mine}")
    vcfg = dict(cfg["validate"])
    res = validate_stage1(rows, vcfg, my_public_ip=mine)
    alive = [r for r in res if r.get("alive") and not r.get("transparent")]

    if cfg["browser"]["enabled"] and not args.no_browser:
        alive = confirm_browser(alive, vcfg,
                                limit=args.browser_limit or cfg["browser"]["max_confirm"],
                                timeout=cfg["browser"]["timeout"])

    for r in alive:
        score = 0
        score += 40 if r.get("alive") else 0
        score += 25 if r.get("https_ok") else 0
        score += 25 if r.get("browser_ok") else 0
        lat = r.get("latency_ms") or 9999
        score += 10 if lat < 1500 else 5 if lat < 4000 else 0
        r["score"] = score
    alive.sort(key=lambda r: (-r["score"], r.get("latency_ms") or 9999))
    save_jsonl(ALIVE, alive)

    trans = sum(1 for r in res if r.get("transparent"))
    print(f"\nTCP+HTTP alive: {sum(1 for r in res if r.get('alive'))} | transparent (dropped): {trans}")
    print(f"Usable after filters: {len(alive)}")
    print(f"Browser-confirmed: {sum(1 for r in alive if r.get('browser_ok'))}")
    return 0


def cmd_export(cfg, args):
    if not ALIVE.exists():
        print("data/alive.jsonl missing - run `validate` first")
        return 1
    rows = load_jsonl(ALIVE)
    if args.min_score:
        rows = [r for r in rows if r.get("score", 0) >= args.min_score]
    if args.proto:
        rows = [r for r in rows if r["proto"] == args.proto]
    OUT.mkdir(exist_ok=True)
    txt = OUT / "proxies.txt"
    js = OUT / "proxies.json"
    with open(txt, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['proto']}://{r.get('auth') or ''}{r['ip']}:{r['port']}\n")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print(f"Exported {len(rows)} proxies -> {txt} , {js}")
    return 0


def cmd_run(cfg, args):
    rc = cmd_fetch(cfg, args)
    if rc:
        return rc
    rc = cmd_validate(cfg, args)
    if rc:
        return rc
    return cmd_export(cfg, args)


def cmd_stats(cfg, args):
    for label, path in (("raw", RAW), ("alive", ALIVE)):
        if not path.exists():
            print(f"{label}: (none)")
            continue
        rows = load_jsonl(path)
        by_proto = {}
        for r in rows:
            by_proto[r["proto"]] = by_proto.get(r["proto"], 0) + 1
        print(f"{label}: {len(rows)}  {by_proto}")
        if label == "alive" and rows:
            best = rows[0]
            print(f"  best: {best['proto']}://{best['ip']}:{best['port']} "
                  f"score={best.get('score')} latency={best.get('latency_ms')}ms")
    return 0


def main():
    ap = argparse.ArgumentParser(description="ProxyScrape Suite")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("fetch", "validate", "export", "run", "stats"):
        p = sub.add_parser(name)
        if name in ("validate", "run"):
            p.add_argument("--limit", type=int, default=0, help="probe at most N candidates")
            p.add_argument("--ports", type=int, nargs="*", help="override allowed ports")
            p.add_argument("--no-browser", action="store_true")
            p.add_argument("--browser-limit", type=int, default=0)
        if name == "export":
            p.add_argument("--min-score", type=int, default=0)
            p.add_argument("--proto", choices=["http", "socks4", "socks5"])

    args = ap.parse_args()
    cfg = load_cfg()
    return {"fetch": cmd_fetch, "validate": cmd_validate, "export": cmd_export,
            "run": cmd_run, "stats": cmd_stats}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
