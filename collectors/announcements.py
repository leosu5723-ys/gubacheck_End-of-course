"""
GubaCheck - ANNOUNCEMENT FULL TEXT AND EXACT PUBLICATION TIME
=========================================================================
    python3 -m collectors.announcements

For every announcement in data/raw/cninfo.jsonl:
  * exact publication time, parsed from the CNINFO link
    (`announcementTime=2026-01-30 20:42:11`), saved to
    data/raw/announcements.jsonl. This replaces the date-only assumption.
  * whether it is PROCEDURAL (legal opinions, meeting notices, internal
    rules, monthly returns ...). Procedural filings are labelled neutral by
    code and their PDFs are not downloaded.
  * for everything else, the PDF from
    http://static.cninfo.com.cn/finalpage/<date>/<ann_id>.PDF, its text in
    data/raw/ann_text/<ann_id>.txt (PDFs themselves are not kept).
    Periodic reports keep the "key financial data" section, which is what
    the knowledge base needs; other filings keep the first 6,000 characters.

Access: one request at a time, 1 s apart; stops on any non-PDF answer.
Resumable: text files already on disk are skipped.
=========================================================================
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
TEXT_DIR = os.path.join(RAW, "ann_text")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

PROCEDURAL = re.compile(
    r"法律意见书|律师事务所|会议资料|召开.{0,20}(股东|业绩说明会)|股东会的通知|提示性公告|"
    r"制度|章程|规则|证券变动月报表|翌日披露报表|核查意见|督导|自查报告|现金管理|理财|"
    r"募集资金.{0,10}(监管协议|存放|专用结算账户)|工商变更|担保|独立董事|董事会秘书|"
    r"职工代表|选举|会计师|审计机构|关联交易|投资者关系|股东会决议|董事会.{0,6}决议|监事会.{0,6}决议|"
    r"融资券|中期票据|债券|兑付|可持续发展报告|ESG|社会责任|细则|审计报告|验资报告|会议决议|会计政策")
PERIODIC = re.compile(r"年度报告|季度报告|半年度报告")


def exact_time(url, fallback_date):
    """Publication time from the link. "00:00:00" means no time was recorded:
    treated as after the close (23:59:59), the conservative choice."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    t = q.get("announcementTime", [""])[0]
    if not re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", t) or t.endswith("00:00:00"):
        return (t[:10] or fallback_date) + " 23:59:59"
    return t


def extract(pdf_bytes, periodic):
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    if not periodic:
        text = ""
        for page in reader.pages[:6]:
            text += page.extract_text() or ""
            if len(text) > 6000:
                break
        return text[:6000]
    text = ""
    for page in reader.pages[:40]:          # key data sits in the first sections
        text += page.extract_text() or ""
    m = re.search(r"主要会计数据和财务指标|主要财务数据", text)
    start = m.start() if m else 0
    return text[start:start + 6000]


def records():
    """All filings with exact time and flags, computed from cninfo.jsonl and
    whatever text is on disk. Usable while a download is still running."""
    out = []
    for line in open(os.path.join(RAW, "cninfo.jsonl"), encoding="utf-8"):
        a = json.loads(line)
        out.append(dict(a, time=exact_time(a["url"], a["date"]),
                        procedural=bool(PROCEDURAL.search(a["title"])) and not PERIODIC.search(a["title"]),
                        periodic=bool(PERIODIC.search(a["title"])) and "摘要" not in a["title"],
                        has_text=os.path.exists(os.path.join(TEXT_DIR, "%s.txt" % a["ann_id"]))))
    return out


def main():
    os.makedirs(TEXT_DIR, exist_ok=True)
    anns = [json.loads(line) for line in open(os.path.join(RAW, "cninfo.jsonl"), encoding="utf-8")]
    # filings inside spike watch windows first: they are what labelling and the backtest need
    spikes_path = os.path.join(ROOT, "data", "snapshot", "spikes.json")
    windows = []
    if os.path.exists(spikes_path):
        from datetime import date, timedelta
        for sp in json.load(open(spikes_path, encoding="utf-8")):
            end = (date.fromisoformat(sp["date"]) + timedelta(days=16)).isoformat()
            windows.append((sp["stock"], sp["date"], end))
    anns.sort(key=lambda a: (not any(a["stock"] == c and d0 <= a["date"] <= d1 for c, d0, d1 in windows),
                            not (PERIODIC.search(a["title"]) and "摘要" not in a["title"])))
    out, fetched = [], 0
    for a in anns:
        title = a["title"]
        rec = dict(a, time=exact_time(a["url"], a["date"]),
                   procedural=bool(PROCEDURAL.search(title)) and not PERIODIC.search(title),
                   periodic=bool(PERIODIC.search(title)) and "摘要" not in title)
        path = os.path.join(TEXT_DIR, "%s.txt" % a["ann_id"])
        rec["has_text"] = os.path.exists(path)
        if not rec["procedural"] and not rec["has_text"]:
            try:
                body = None
                for ext in ("PDF", "pdf"):          # both spellings exist on the server
                    url = "http://static.cninfo.com.cn/finalpage/%s/%s.%s" % (a["date"], a["ann_id"], ext)
                    try:
                        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                                    timeout=60) as r:
                            body = r.read()
                        break
                    except urllib.error.HTTPError as e:
                        if e.code != 404:
                            raise
                if body is None:
                    raise IOError("404 for both .PDF and .pdf")
                if not body.startswith(b"%PDF"):
                    print("STOPPED: non-PDF answer for", a["ann_id"], url)
                    break
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(extract(body, rec["periodic"]))
                rec["has_text"] = True
                fetched += 1
                if fetched % 50 == 0:
                    print("  fetched", fetched, flush=True)
            except Exception as e:
                print("  failed", a["ann_id"], str(e)[:80], flush=True)
            time.sleep(1.0)
        out.append(rec)
    with open(os.path.join(RAW, "announcements.jsonl"), "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_proc = sum(r["procedural"] for r in out)
    print("announcements %d | procedural %d | with text %d | fetched now %d"
          % (len(out), n_proc, sum(r["has_text"] for r in out), fetched))
    print("ANN DONE")


if __name__ == "__main__":
    main()
