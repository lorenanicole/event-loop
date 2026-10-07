"""Check whether stored event links actually resolve.

Every event card has a "Learn more" link, and nothing until now checked that
any of them worked. The Den Theatre config carried a website_url whose domain
did not exist, so all 29 of its links were dead and nobody would have known
without clicking one.

    python link_health.py             # one sampled link per source
    python link_health.py --source chicago_venue_coless_bar   # every link there

Read the output with some care: 401, 403 and 406 are usually bot protection
rather than a dead link - Ticketmaster, Songkick and several venues reject a
scripted request but serve the same URL fine in a browser. A 404 or a DNS
failure is the real signal.
"""
import asyncio, sqlite3
import httpx

F = "(date_end >= date('now') OR (date_end IS NULL AND date >= date('now')))"

async def check(client, source, url, sem):
    async with sem:
        try:
            r = await client.head(url, timeout=20, follow_redirects=True)
            code = r.status_code
            if code in (403, 405):  # some servers reject HEAD
                r = await client.get(url, timeout=20, follow_redirects=True)
                code = r.status_code
        except Exception as exc:
            return source, url, f"ERR {type(exc).__name__}"
        return source, url, str(code)

async def main():
    import sys
    c = sqlite3.connect("data/events.db")
    if "--source" in sys.argv:
        source = sys.argv[sys.argv.index("--source") + 1]
        rows = c.execute(f"""SELECT source, origination_url FROM events
                             WHERE {F} AND source = ? AND origination_url LIKE 'http%'""",
                         (source,)).fetchall()
    else:
        rows = c.execute(f"""SELECT source, MIN(origination_url) FROM events
                             WHERE {F} AND origination_url LIKE 'http%'
                             GROUP BY source ORDER BY source""").fetchall()
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        results = await asyncio.gather(*(check(client, s, u, sem) for s, u in rows))
    bad = [(s, u, code) for s, u, code in results
           if not (code.startswith("2") or code.startswith("3"))]
    print(f"checked {len(results)} sources, {len(bad)} look broken\n")
    for s, u, code in sorted(bad, key=lambda r: r[0]):
        print(f"  {code:18} {s[:36]:38} {u[:58]}")
    print(f"\n{len(results) - len(bad)} sources returned a usable link.")

asyncio.run(main())
