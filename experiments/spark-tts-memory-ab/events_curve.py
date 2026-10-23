#!/usr/bin/env python3
"""Print the memory curve of one arm from its pool events (works for tripped runs too)."""
import json, sys, statistics
GIB = 1024**3
events = json.load(open(sys.argv[1]))
ready = [e for e in events if e["kind"] == "pool_ready"]
results = [e for e in events if e["kind"] == "result"]
trip = [e for e in events if e["kind"] == "reserve_failure"]
if ready:
    r = ready[0]
    print(f"pool_ready memAvail={r['memAvailableBytes']/GIB:.1f} GiB allocConf={r.get('cudaAllocConf')} release={r.get('releaseCudaCache')}")
loads = [e for e in events if e["kind"] == "ready"]
if loads:
    c = [e["memory"]["cuda"] for e in loads if e.get("memory", {}).get("cuda")]
    print(f"after load: worker rss={statistics.median(e['memory']['rssBytes'] for e in loads)/GIB:.2f} GiB  cuda reserved={statistics.median(x['reservedBytes'] for x in c)/GIB:.2f} allocated={statistics.median(x['allocatedBytes'] for x in c)/GIB:.2f} GiB")
print(f"results={len(results)} trip={bool(trip)}")
per_worker = {}
for i, e in enumerate(results):
    c = (e.get("memory") or {}).get("cuda") or {}
    per_worker.setdefault(e["worker"], []).append(c)
    if i % 8 == 7 or i == len(results) - 1:
        print(f"  result#{i+1:3d} window={e['index']:4d} memAvail={e['memAvailableBytes']/GIB:6.1f} GiB  worker{e['worker']} reserved={c.get('reservedBytes',0)/GIB:5.2f} allocated={c.get('allocatedBytes',0)/GIB:5.2f} maxAlloc={c.get('maxAllocatedBytes',0)/GIB:5.2f} rss={(e.get('memory') or {}).get('rssBytes',0)/GIB:4.2f} gen={e['generationSeconds']:.1f}s rel={e.get('releaseSeconds')}")
print("per-worker reserved GiB by window:")
for w, rows in sorted(per_worker.items()):
    print(f"  w{w}: " + " ".join(f"{r.get('reservedBytes',0)/GIB:.1f}" for r in rows) + f"   allocated last {rows[-1].get('allocatedBytes',0)/GIB:.2f}")
if results:
    mem = [e["memAvailableBytes"]/GIB for e in results]
    print(f"memAvail first→last result: {mem[0]:.1f} → {mem[-1]:.1f} GiB over {len(mem)} results = {(mem[0]-mem[-1])/max(len(mem)-1,1):.2f} GiB/window")
    tot = sum(r.get("reservedBytes",0) for rows in per_worker.values() for r in rows[-1:])
    print(f"sum of workers' last reserved: {tot/GIB:.1f} GiB")
if trip:
    t = trip[0]
    print(f"TRIP memAvail={t['memAvailableBytes']/GIB:.1f} GiB parentRss={(t.get('parentRssBytes') or 0)/GIB:.2f} pending={t['pendingWindows']} received={t['receivedWindows']}")
