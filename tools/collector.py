"""매일 아침 브리핑 수집기.
국회 공지사항 / 청와대 공개일정 / 청와대 브리핑 / 방미통위(KMCC) 공지사항 / CNN / BBC 를
수집해서 state.json(평문, 전체 보관 이력)을 갱신한다.

Usage: python3 collector.py <state.json 경로>

실행 전제: requests, beautifulsoup4 가 설치돼 있어야 한다.
사이트 구조가 바뀌면 해당 fetch_* 함수만 고치면 된다 — 한 출처가 실패해도
나머지 출처 수집에는 영향이 없도록 모두 try/except로 감쌌다.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
HEADERS = {"User-Agent": UA}
TIMEOUT = 25
MAX_KEEP = 150  # 출처별 최대 보관 건수(오래된 것부터 제거)


def now_kst():
    return datetime.now(KST)


def log(msg):
    print(f"[collector] {msg}", flush=True)


# ---------- 출처별 수집 함수 ----------
# 각 함수는 [{title, date(YYYY-MM-DD), url, extra...}, ...] 를 반환한다 (최신순 아님 — merge 단계에서 정렬)

def fetch_assembly():
    """국회 홈페이지 공지사항"""
    url = "https://assembly.go.kr/portal/bbs/B0000054/list.do?menuNo=600100"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    table = None
    for t in soup.select("table"):
        cap = t.select_one("caption")
        if cap and "공지사항번호" in cap.get_text():
            table = t
            break
    table = table or soup.select_one("table")
    rows = table.select("tbody tr") if table else []
    if not rows:
        log(f"[진단] 국회: status={r.status_code} len={len(r.text)} title={soup.title.get_text(strip=True) if soup.title else None!r} table개수={len(soup.select('table'))}")
    for tr in rows:
        tds = tr.select("td")
        if len(tds) < 5:
            continue
        a = tds[2].select_one("a")  # 번호(0) 공지구분(1) 제목(2) 부서명(3) 작성일(4) ...
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        href = a.get("href") or ""
        link = requests.compat.urljoin(url, href) if href and not href.startswith("javascript") else url
        date = ""
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", tds[4].get_text())
        if m:
            date = m.group(1)
        dept = tds[3].get_text(" ", strip=True)[:40]
        out.append({"title": title, "date": date or now_kst().strftime("%Y-%m-%d"), "url": link, "dept": dept})
    return out


def fetch_president_schedule():
    """청와대 공개일정 — 이번 달 달력 페이지에서 날짜별 일정 추출"""
    url = "https://www.president.go.kr/schedule"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    links = soup.select("td.date a[data-dt]")
    if not links:
        log(f"[진단] 청와대일정: status={r.status_code} len={len(r.text)} title={soup.title.get_text(strip=True) if soup.title else None!r} td.date개수={len(soup.select('td.date'))} a[data-dt]개수={len(soup.select('a[data-dt]'))}")
    for a in links:
        dt = a.get("data-dt", "").replace(".", "-")
        if not re.match(r"^20\d{2}-\d{2}-\d{2}$", dt):
            continue
        items = [li.get_text(" ", strip=True) for li in a.select("li")]
        items = [t for t in items if t]
        if not items:
            continue
        out.append({"title": " · ".join(items), "date": dt, "url": url, "items": items})
    return out


def fetch_president_briefings():
    """청와대 브리핑(뉴스룸)"""
    url = "https://www.president.go.kr/briefings"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    cards = soup.select("ul.defulat > li")
    if not cards:
        log(f"[진단] 청와대브리핑: status={r.status_code} len={len(r.text)} title={soup.title.get_text(strip=True) if soup.title else None!r} ul개수={len(soup.select('ul'))}")
    for node in cards:
        title_el = node.select_one(".noticeTitle")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue
        date_el = node.select_one(".date")
        date_m = re.search(r"(20\d{2})\.(\d{2})\.(\d{2})", date_el.get_text()) if date_el else None
        date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}" if date_m else now_kst().strftime("%Y-%m-%d")
        a = node.select_one("a")
        href = a.get("href") if a else ""
        link = requests.compat.urljoin(url, href) if href and not href.startswith("javascript") else url
        summary_el = node.select_one(".noticeText")
        summary = summary_el.get_text(" ", strip=True)[:160] if summary_el else ""
        out.append({"title": title, "date": date, "url": link, "summary": summary})
    return out[:40]


def fetch_kmcc():
    """방미통위(KMCC) 공지사항"""
    url = "https://www.kmcc.go.kr/user.do?boardId=1112&page=A05020000&dc=K05020000"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    table = soup.select_one("table")
    rows = table.select("tbody tr") if table else []
    for tr in rows:
        tds = tr.select("td")
        if len(tds) < 6:
            continue
        a = tds[1].select_one("a")  # 번호(0) 제목(1) 담당부서(2) 공공누리(3) 첨부파일(4) 작성일(5) 조회수(6)
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        href = a.get("href") or ""
        link = requests.compat.urljoin(url, href) if href and not href.startswith("javascript") else url
        date = ""
        m = re.search(r"(20\d{2}-\d{2}-\d{2}|20\d{2}\.\d{2}\.\d{2})", tds[5].get_text())
        if m:
            date = m.group(1).replace(".", "-")
        out.append({"title": title, "date": date or now_kst().strftime("%Y-%m-%d"), "url": link})
    return out


def _parse_rss(xml_text, limit=30):
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        pub = (item.findtext("pubDate") or "").strip()
        date = now_kst().strftime("%Y-%m-%d")
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(pub)
            date = d.astimezone(KST).strftime("%Y-%m-%d")
        except Exception:
            pass
        if not title:
            continue
        out.append({"title": title, "date": date, "url": link, "summary": desc[:200]})
    return out


def fetch_bbc():
    url = "https://feeds.bbci.co.uk/news/world/rss.xml"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return _parse_rss(r.text)


def fetch_cnn():
    # CNN 자체 RSS는 서비스 종료 — 구글 뉴스 RSS(출처 필터)로 대체, 제목+요약+원문 링크만 사용
    url = "https://news.google.com/rss/search?q=site:cnn.com%20when:1d&hl=en-US&gl=US&ceid=US:en"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    items = _parse_rss(r.text)
    for it in items:
        it["title"] = re.sub(r"\s*-\s*CNN$", "", it["title"]).strip()
    return items


SOURCES = {
    "assembly": ("국회 공지사항", fetch_assembly),
    "schedule": ("청와대 공개일정", fetch_president_schedule),
    "briefing": ("청와대 브리핑", fetch_president_briefings),
    "kmcc": ("방미통위 공지사항", fetch_kmcc),
    "cnn": ("CNN", fetch_cnn),
    "bbc": ("BBC", fetch_bbc),
}


def item_key(it):
    return (it.get("url") or "") + "|" + it.get("title", "")


def merge(existing, fresh):
    by_key = {item_key(it): it for it in existing}
    added = 0
    for it in fresh:
        k = item_key(it)
        if k not in by_key:
            added += 1
        by_key[k] = {**by_key.get(k, {}), **it}  # 최신 수집값으로 갱신
    merged = list(by_key.values())
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    return merged[:MAX_KEEP], added


def main():
    state_path = sys.argv[1] if len(sys.argv) > 1 else "state.json"
    state = {"updated": "", "sources": {}}
    if os.path.exists(state_path):
        try:
            state = json.load(open(state_path, encoding="utf-8"))
        except Exception as e:
            log(f"기존 state.json 로드 실패, 새로 시작: {e}")
    state.setdefault("sources", {})

    any_ok = False
    for key, (label, fn) in SOURCES.items():
        try:
            fresh = fn()
            existing = state["sources"].get(key, {}).get("items", [])
            merged, added = merge(existing, fresh)
            state["sources"][key] = {"label": label, "items": merged, "lastOk": now_kst().strftime("%Y-%m-%d %H:%M")}
            log(f"{label}: 수집 {len(fresh)}건 (신규 {added}건, 누적 {len(merged)}건)")
            any_ok = True
        except Exception as e:
            log(f"{label}: 수집 실패 — {type(e).__name__}: {e}")
            # 실패해도 기존 데이터는 그대로 유지
            if key not in state["sources"]:
                state["sources"][key] = {"label": label, "items": [], "lastOk": None}

    state["updated"] = now_kst().strftime("%Y-%m-%d %H:%M")
    json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    log(f"state.json 저장 완료 ({state_path})")
    if not any_ok:
        log("경고: 모든 출처 수집 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
