"""
summarize.py  ―  Gemini API（無料枠）で記事を日本語3行要約 + タグ付け
"""

import json
import time
import os
from datetime import date
from pathlib import Path
from google import genai
from google.genai import types

TODAY = date.today().isoformat()
DATA_DIR = Path(__file__).parent.parent / "data"

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise SystemExit("環境変数 GEMINI_API_KEY が設定されていません。先に $env:GEMINI_API_KEY を設定してください。")

# vertexai=False を明示し、APIキー認証だけを使うようにする
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
        }
    except json.JSONDecodeError:
        print(f"  [warn] JSON parse failed for: {title[:40]}")
        return {"summary": "", "tags": article.get("tags", [])}
    except Exception as e:
        print(f"  [error] {title[:40]}: {e}")
        return {"summary": "", "tags": article.get("tags", [])}


def main():
    target = DATA_DIR / f"{TODAY}.json"
    if not target.exists():
        print(f"[error] {target} not found — run crawler.py first")
        return

    data = json.loads(target.read_text(encoding="utf-8"))
    articles = data["articles"]
    total = len(articles)
    print(f"=== summarize start (Gemini無料枠): {total} articles ===")

    for i, article in enumerate(articles):
        if article.get("summary"):
            print(f"  [{i+1}/{total}] skip: {article['title'][:40]}")
            continue

        print(f"  [{i+1}/{total}] summarizing: {article['title'][:50]}")
        result = summarize_article(article)
        article["summary"] = result["summary"]
        if result["tags"]:
            article["tags"] = result["tags"]

        time.sleep(4)

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== summarize complete → {target} ===")


if __name__ == "__main__":
    main()