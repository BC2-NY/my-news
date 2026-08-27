"""
crawler.py  ―  はてブ / Hacker News / Reddit から今日のITトレンド記事を取得
"""

import json
import re
import time
import hashlib
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "ITNoise-NewsBot/1.0 (personal aggregator)"}


def url_id(prefix: str, url: str) -> str:
    """URLから安定したIDを作る。

    組み込みの hash() は文字列に対してプロセスごとにランダム化される
    (PYTHONHASHSEED) ため、同じ記事でも実行のたびにIDが変わってしまう。
    日をまたいだ重複判定に使えるよう hashlib で固定する。
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:12]}"


def strip_html(html: str) -> str:
    """HTML片からテキストだけ取り出す（RSSのdescriptionにタグが入るため）"""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_page_text(url: str) -> tuple[str, str]:
    """記事ページから要約の材料になるテキストを取る。

    戻り値は (本文, 取得元)。取れなければ ("", "none")。
    優先順位は og:description / meta description → <article>/<main> の本文。
    メタ記述は書き手が要約した一文なので、雑な本文抽出より当たりが良い。
    """
    try:
        res = requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT,
                           allow_redirects=True, stream=True)
        if res.status_code != 200:
            return "", "none"
        if "html" not in res.headers.get("content-type", "").lower():
            return "", "none"

        chunks, size = [], 0
        for chunk in res.iter_content(8192):
            chunks.append(chunk)
            size += len(chunk)
            if size >= FETCH_MAX_BYTES:
                break
        res.close()
        html = b"".join(chunks).decode(res.encoding or "utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")

        meta = ""
        for sel, attr in (({"property": "og:description"}, "content"),
                          ({"name": "description"}, "content")):
            tag = soup.find("meta", attrs=sel)
            if tag and tag.get(attr):
                meta = re.sub(r"\s+", " ", tag[attr]).strip()
                break

        for junk in soup(["script", "style", "noscript", "nav", "header",
                          "footer", "aside", "form", "iframe"]):
            junk.decompose()
        main = soup.find("article") or soup.find("main") or soup.body
        body = re.sub(r"\s+", " ", main.get_text(" ")).strip() if main else ""

        # メタ記述だけで十分な長さなら本文と繋げず、それを使う
        if len(body) >= 200:
            combined = (meta + " " + body).strip() if meta else body
            return combined[:BODY_CHARS], "page"
        if len(meta) >= 60:
            return meta[:BODY_CHARS], "meta"
        return "", "none"

    except Exception as e:
        print(f"  [body] {url[:60]}: {type(e).__name__}")
        return "", "none"


def enrich_bodies(articles: list[dict]) -> None:
    """説明文が薄い記事に本文を補う。ここが要約品質を決める。"""
    if not FETCH_BODY:
        return
    need = [a for a in articles if len(a.get("raw_description", "")) < 120]
    print(f"[body] {len(need)}/{len(articles)} 件の本文を取得します")
    for a in need:
        text, origin = fetch_page_text(a["url"])
        if text:
            a["raw_description"] = text
            a["content_source"] = origin
        time.sleep(FETCH_SLEEP)
    got = sum(1 for a in need if a.get("content_source") in ("page", "meta"))
    print(f"[body] {got}/{len(need)} 件で本文を取得")

# ── 設定 ──────────────────────────────────────────────────────────────
HATENA_FEEDS = [
    "https://b.hatena.ne.jp/hotentry/it.rss",
]
HATENA_TOP_N = 8  # はてブから取得する記事数
HN_TOP_N   = 8    # HN から取得する記事数
REDDIT_SUBS = ["programming"]
REDDIT_TOP_N = 4  # 各サブレから4件ずつ（1サブレ = 4件）

# 本文取得の設定。要約の材料が無いとAIが内容を捏造するため、
# 説明文が空の記事は元ページから本文を取りに行く。
FETCH_BODY = True
BODY_CHARS = 1500      # Geminiに渡す本文の最大文字数
FETCH_TIMEOUT = 12     # 1ページあたりの上限（秒）
FETCH_MAX_BYTES = 600_000
FETCH_SLEEP = 0.6      # 相手サイトへの連続アクセスを避ける


# ──────────────────────────────────────────────────────────────────────
# はてなブックマーク
# ──────────────────────────────────────────────────────────────────────
def fetch_hatena() -> list[dict]:
    articles = []
    for url in HATENA_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:HATENA_TOP_N]:
                # はてブカウントを取得（エントリのSummaryから抽出）
                score = 0
                summary = getattr(entry, 'summary', '') or ''
                # はてブRSSには users タグが含まれる場合がある
                if hasattr(entry, 'hatena_bookmarkcount'):
                    score = int(entry.hatena_bookmarkcount)

                desc = strip_html(summary)
                articles.append({
                    "id": url_id("hatena", entry.link),
                    "source": "hatena",
                    "title": entry.title,
                    "url": entry.link,
                    "score": score,
                    "comments": 0,
                    "raw_description": desc[:BODY_CHARS],
                    "content_source": "feed" if desc else "none",
                    "tags": [],
                    "fetched_at": datetime.now(JST).isoformat(),
                })
        except Exception as e:
            print(f"[hatena] fetch error: {e}")
    print(f"[hatena] {len(articles)} articles")
    return articles


# ──────────────────────────────────────────────────────────────────────
# Hacker News（公式JSONアAPI）
# ──────────────────────────────────────────────────────────────────────
def fetch_hackernews() -> list[dict]:
    articles = []
    try:
        res = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            headers=HEADERS, timeout=10
        )
        ids = res.json()[:HN_TOP_N]

        for story_id in ids:
            try:
                r = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    headers=HEADERS, timeout=10
                )
                item = r.json()
                if not item or item.get("type") != "story":
                    continue
                # Ask HN / Show HN などの自己投稿は本文が text に入る。
                # 外部リンク記事はここが空なので、あとで enrich_bodies が拾う。
                self_text = strip_html(item.get("text", ""))
                articles.append({
                    "id": f"hn_{story_id}",
                    "source": "hackernews",
                    "title": item.get("title", ""),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                    "score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "raw_description": self_text[:BODY_CHARS],
                    "content_source": "hn_text" if self_text else "none",
                    "tags": [],
                    "fetched_at": datetime.now(JST).isoformat(),
                })
                time.sleep(0.1)  # HN API へのレート制限を回避
            except Exception as e:
                print(f"[hn] item {story_id} error: {e}")

    except Exception as e:
        print(f"[hn] fetch error: {e}")
    print(f"[hn] {len(articles)} articles")
    return articles


# ──────────────────────────────────────────────────────────────────────
# Reddit（RSS フィード）
# ──────────────────────────────────────────────────────────────────────
def fetch_reddit() -> list[dict]:
    articles = []
    for sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit={REDDIT_TOP_N}"
        try:
            feed = feedparser.parse(url, agent=HEADERS["User-Agent"])
            for entry in feed.entries[:REDDIT_TOP_N]:
                # Reddit RSS の score は content タグに埋め込まれている場合がある
                score = 0
                raw_desc = ""
                if entry.get("content"):
                    raw_desc = strip_html(entry.content[0].value)

                articles.append({
                    "id": url_id("reddit", entry.link),
                    "source": "reddit",
                    "title": entry.title,
                    "url": entry.link,
                    "score": score,
                    "comments": 0,
                    "raw_description": raw_desc[:BODY_CHARS],
                    "content_source": "feed" if raw_desc else "none",
                    "tags": [sub],
                    "fetched_at": datetime.now(JST).isoformat(),
                })
        except Exception as e:
            print(f"[reddit] r/{sub} error: {e}")
    print(f"[reddit] {len(articles)} articles")
    return articles


# ──────────────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────────────
def main():
    print(f"=== crawler start: {TODAY} ===")
    all_articles = []
    all_articles.extend(fetch_hatena())
    all_articles.extend(fetch_hackernews())
    all_articles.extend(fetch_reddit())

    enrich_bodies(all_articles)

    # スコアでソート
    all_articles.sort(key=lambda x: x["score"], reverse=True)

    output = {
        "date": TODAY,
        "generated_at": datetime.now(JST).isoformat(),
        "articles": all_articles,
    }

    out_path = OUTPUT_DIR / f"{TODAY}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"=== saved {len(all_articles)} articles → {out_path} ===")


if __name__ == "__main__":
    main()