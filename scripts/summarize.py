"""
summarize.py  ―  Gemini API（無料枠）で記事を日本語3行要約 + タグ付け

無料枠: gemini-2.5-flash-lite は 1日20リクエストまで（このアカウントの場合）
重要: Gemini APIで「課金を有効化」すると無料枠が消えるので、絶対に有効化しないこと。
"""

import json
import time
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from google import genai
from google.genai import types

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
DATA_DIR = Path(__file__).parent.parent / "data"

# ── 設定 ──────────────────────────────────────────────
# 1日あたり要約する最大件数（無料枠の上限に合わせる。超えると429エラーになる）
DAILY_LIMIT = 20
# APIリクエストの間隔（秒）。レート制限(RPM)対策
SLEEP_SEC = 4
# ──────────────────────────────────────────────────────

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise SystemExit("環境変数 GEMINI_API_KEY が設定されていません。先に設定してください。")

client = genai.Client(api_key=API_KEY, vertexai=False)

MODEL = "gemini-2.5-flash-lite"

SYSTEM_PROMPT = """あなたはITニュースのキュレーターです。
与えられた記事タイトルと説明文を読み、以下のJSON形式で必ず回答してください。

{
  "summary": "3〜4文の日本語要約。技術的に正確で、なぜ重要かを含める。",
  "tags": ["タグ1", "タグ2", "タグ3"]
}

注意:
- summaryは技術者が読んで価値があると感じる内容にする
- 誇張や煽りは避け、事実ベースで書く
- タグは最大4つ、内容を正確に反映させる
- 必ずJSONのみ返す（説明文や```は不要）"""


def summarize_article(article: dict) -> dict:
    title = article.get("title", "")
    raw_desc = article.get("raw_description", "")

    user_content = f"タイトル: {title}"
    if raw_desc:
        user_content += f"\n説明: {raw_desc[:400]}"

    full_prompt = SYSTEM_PROMPT + "\n\n---\n\n" + user_content

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=400,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        text = response.text.strip()
        parsed = json.loads(text)
        return {
            "summary": parsed.get("summary", ""),
            "tags": parsed.get("tags", [])[:4],
            "ok": True,
        }
    except json.JSONDecodeError:
        print(f"  [warn] JSON parse failed for: {title[:40]}")
        return {"summary": "", "tags": article.get("tags", []), "ok": False}
    except Exception as e:
        print(f"  [error] {title[:40]}: {e}")
        return {"summary": "", "tags": article.get("tags", []), "ok": False}


def main():
    target = DATA_DIR / f"{TODAY}.json"
    if not target.exists():
        print(f"[error] {target} not found — run crawler.py first")
        return

    data = json.loads(target.read_text(encoding="utf-8"))
    articles = data["articles"]
    total = len(articles)
    print(f"=== summarize start (Gemini無料枠 / 上限{DAILY_LIMIT}件): {total} articles ===")

    done = 0  # 今回API要約した件数
    for i, article in enumerate(articles):
        # すでに要約済みならスキップ（APIを消費しない）
        if article.get("summary"):
            continue

        # 1日の上限に達したら、残りは未要約のまま打ち切る
        if done >= DAILY_LIMIT:
            print(f"  [上限] {DAILY_LIMIT}件に達したので残り{total - i}件は明日に回します")
            break

        print(f"  [{i+1}/{total}] summarizing: {article['title'][:50]}")
        result = summarize_article(article)
        article["summary"] = result["summary"]
        if result["tags"]:
            article["tags"] = result["tags"]

        if result["ok"]:
            done += 1
        time.sleep(SLEEP_SEC)

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== summarize complete: {done}件を要約 → {target} ===")


if __name__ == "__main__":
    main()
