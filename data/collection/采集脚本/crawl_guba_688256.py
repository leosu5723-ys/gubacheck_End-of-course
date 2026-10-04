# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import concurrent.futures
import datetime as dt
import json
import pathlib
import time
import urllib.parse
import urllib.request
import socket
import threading

# Resolve only this public endpoint through DNS-over-HTTPS if local DNS fails.
_original_getaddrinfo = socket.getaddrinfo
_dns_lock = threading.Lock()
_dns_cache = None

def _endpoint_getaddrinfo(host, *args, **kwargs):
    global _dns_cache
    try:
        return _original_getaddrinfo(host, *args, **kwargs)
    except socket.gaierror:
        if host != 'gbapi.eastmoney.com':
            raise
        with _dns_lock:
            if _dns_cache is None or time.monotonic() >= _dns_cache[1]:
                with urllib.request.urlopen('https://dns.google/resolve?name=gbapi.eastmoney.com&type=A', timeout=20) as response:
                    answer = json.load(response)
                record = next(item for item in answer['Answer'] if item['type'] == 1)
                _dns_cache = (record['data'], time.monotonic() + record['TTL'])
        return _original_getaddrinfo(_dns_cache[0], *args, **kwargs)

socket.getaddrinfo = _endpoint_getaddrinfo

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DATA_DIR = ROOT / '十个股票的股吧数据'
RAW_DIR = ROOT / '原始数据与断点'
REPORT_DIR = ROOT / '采集报告'
for folder in (DATA_DIR, RAW_DIR, REPORT_DIR):
    folder.mkdir(exist_ok=True)
START = '2025-10-03 00:00:00'
END = '2026-10-02 17:35:28'
RAW = RAW_DIR / '688256_raw_pages.jsonl'
OUT = DATA_DIR / '688256_365days.jsonl'
REPORT = REPORT_DIR / '688256_采集报告.json'
BASE = 'https://gbapi.eastmoney.com/webarticlelist/api/Article/Articlelist?'

def fetch(page):
    params = dict(code='688256', type=0, p=page, ps=100, sorttype=0,
                  deviceid=100, version=200, product='Guba', plat='Web')
    for attempt in range(5):
        try:
            req = urllib.request.Request(BASE + urllib.parse.urlencode(params), headers={'User-Agent':'Mozilla/5.0','Referer':'https://guba.eastmoney.com/'})
            with urllib.request.urlopen(req, timeout=35) as response:
                data = json.load(response)
            if data.get('rc') != 1 or not isinstance(data.get('re'),list):
                raise ValueError(str(data)[:200])
            return page, data
        except Exception:
            if attempt == 4: raise
            time.sleep(2 ** attempt)

seen = {}; completed = set(); last_page = None
if RAW.exists():
    for line in RAW.open():
        entry=json.loads(line); completed.add(entry['page'])
        for p in entry['data']['re']:
            if START <= p['post_publish_time'] <= END:
                seen[p['post_id']] = p

def save(status, error=None):
    with OUT.open('w') as f:
        for p in sorted(seen.values(), key=lambda p:(p['post_publish_time'],p['post_id']), reverse=True):
            row=dict(post_id=int(p['post_id']),stock='688256',time=p['post_publish_time'],title=p['post_title'],reads=int(p['post_click_count']),comments=int(p['post_comment_count']),post_type=int(p['post_type']),bar_code='688256')
            f.write(json.dumps(row,ensure_ascii=False)+'\n')
    times=[p['post_publish_time'] for p in seen.values()]
    REPORT.write_text(json.dumps(dict(status=status,error=error,start=START,end=END,records=len(seen),pages=len(completed),last_page=last_page,min_time=min(times) if times else None,max_time=max(times) if times else None,reference_projects=['https://github.com/zcyeee/EastMoney_Crawler','https://github.com/wonchermaine960/eastmoney-cli'],method='公开接口，p/ps分页，sorttype=0按发布时间降序；post_id去重；reads/comments为抓取时快照'),ensure_ascii=False,indent=2))

import os
if os.environ.get('GUBA_PAUSED_EXPORT') == '1':
    save('已暂停')
    print(json.dumps(dict(records=len(seen),pages=len(completed)),ensure_ascii=False))
    raise SystemExit(0)

try:
    page=max(1, max(completed, default=0)-23)
    completed.difference_update(range(page, max(completed, default=0)+1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool, RAW.open('a') as raw:
        while True:
            batch=[p for p in range(page,page+24) if p not in completed]
            stop=False
            for num,data in pool.map(fetch,batch):
                raw.write(json.dumps(dict(page=num,data=data),ensure_ascii=False)+'\n'); raw.flush(); completed.add(num)
                posts=data['re']
                for p in posts:
                    if START <= p['post_publish_time'] <= END: seen[p['post_id']]=p
                # Pinned posts are excluded from the stopping criterion by examining the tail.
                tail=posts[-10:]
                if not posts or (len(tail)==10 and all(p['post_publish_time']<START for p in tail)):
                    stop=True; last_page=num if last_page is None else min(last_page,num)
            save('采集中')
            print(json.dumps(dict(page=page+23,records=len(seen),oldest=min((p['post_publish_time'] for p in seen.values()),default=None)),ensure_ascii=False),flush=True)
            if stop: break
            page+=24
            if page>10000: raise RuntimeError('达到10000页限制')
            time.sleep(.4)
    save('完成')
except Exception as e:
    save('未完成',str(e)); raise
