"""
crawler.py  ―  はてブ / Hacker News / Reddit から今日のITトレンド記事を取得
"""

import json
import time
import feedparser
import requests
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "ITNoise-NewsBot/1.0 (personal aggregator)"}

# ── 設定 ──────────────────────────────────────────────────────────────
HATENA_FEEDS = [
    "https://b.hatena.ne.jp/hotentry/it.rss",
]
HATENA_TOP_N = 8  # はてブから取得する記事数
HN_TOP_N   = 8    # HN から取得する記事数
REDDIT_SUBS = ["programming", "webdev", "MachineLearning", "artificial"]
REDDIT_TOP_N = 1  # 各サブレから1件ずつ（4サブレ = 4件）


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

                articles.append({
                    "id": f"hatena_{abs(hash(entry.link)) % 100000:05d}",
                    "source": "hatena",
                    "title": entry.title,
                    "url": entry.link,
                    "score": score,
                    "comments": 0,
                    "raw_description": summary[:500],
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
                articles.append({
                    "id": f"hn_{story_id}",
                    "source": "hackernews",
                    "title": item.get("title", ""),
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                    "score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "raw_description": "",  # HNは本文なし → Claudeがタイトルから要約
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
                    raw_desc = entry.content[0].value[:500]

                articles.append({
                    "id": f"reddit_{abs(hash(entry.link)) % 100000:05d}",
                    "source": "reddit",
                    "title": entry.title,
                    "url": entry.link,
                    "score": score,
                    "comments": 0,
                    "raw_description": raw_desc,
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