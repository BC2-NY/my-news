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

# 本文が取れている記事用。事実は本文の中だけから拾わせる。
PROMPT_WITH_BODY = """あなたはITニュースのキュレーターです。
与えられた記事の本文を読み、以下のJSON形式で必ず回答してください。

{
  "summary": "3〜4文の日本語要約。技術的に正確で、なぜ重要かを含める。",
  "tags": ["タグ1", "タグ2", "タグ3"]
}

厳守:
- **必ず日本語で書く**。原文が英語でも要約は日本語にする
- 本文に書かれていないことは書かない。数値・企業名・製品の性質を
  推測で補わない。本文が何の話か曖昧なら、曖昧なまま短く書く
- 誇張や煽りは避け、事実ベースで書く
- summaryは技術者が読んで価値があると感じる内容にする
- タグは最大4つ、内容を正確に反映させる
- 必ずJSONのみ返す（説明文や``` は不要）"""

# 本文が取れなかった記事用。ここで自由に書かせると捏造が起きるので、
# タイトルから読み取れる範囲に明示的に閉じ込める。
PROMPT_TITLE_ONLY = """あなたはITニュースのキュレーターです。
**記事タイトルしか手元にありません。本文は取得できませんでした。**
以下のJSON形式で必ず回答してください。

{
  "summary": "タイトルから確実に読み取れる範囲だけの、1〜2文の日本語の説明。",
  "tags": ["タグ1", "タグ2"]
}

厳守:
- **必ず日本語で書く**
- **タイトルに書かれていない事実を絶対に補わない**。製品の機能、企業の
  業種、金額、技術的な仕組み、影響範囲などを想像で書いてはいけない。
  これらは全て捏造になる
- 分かるのが「何についての記事らしいか」だけなら、それだけを書く
- 「〜と思われる」「〜についての記事」のように、断定を避けた書き方にする
- タグはタイトルに現れた語だけから付ける。最大2つ。無ければ空配列
- 必ずJSONのみ返す（説明文や``` は不要）"""

# これ未満なら本文とみなさない
MIN_BODY_CHARS = 80


def summarize_article(article: dict) -> dict:
    title = article.get("title", "")
    raw_desc = (article.get("raw_description") or "").strip()
    has_body = len(raw_desc) >= MIN_BODY_CHARS

    if has_body:
        user_content = f"タイトル: {title}\n\n本文:\n{raw_desc[:1500]}"
        full_prompt = PROMPT_WITH_BODY + "\n\n---\n\n" + user_content
    else:
        user_content = f"タイトル: {title}"
        full_prompt = PROMPT_TITLE_ONLY + "\n\n---\n\n" + user_content

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
            # 何を根拠に書かれた要約かを残す。UI側で断り書きを出すため。
            "basis": "content" if has_body else "title",
            "ok": True,
        }
    except json.JSONDecodeError:
        print(f"  [warn] JSON parse failed for: {title[:40]}")
        return {"summary": "", "tags": article.get("tags", []), "basis": "", "ok": False}
    except Exception as e:
        print(f"  [error] {title[:40]}: {e}")
        return {"summary": "", "tags": article.get("tags", []), "basis": "", "ok": False}


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

        body = len((article.get("raw_description") or "").strip())
        mark = "本文" if body >= MIN_BODY_CHARS else "タイトルのみ"
        print(f"  [{i+1}/{total}] ({mark}) {article['title'][:44]}")
        result = summarize_article(article)
        article["summary"] = result["summary"]
        article["summary_basis"] = result["basis"]
        if result["tags"]:
            article["tags"] = result["tags"]

        if result["ok"]:
            done += 1
        time.sleep(SLEEP_SEC)

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    thin = sum(1 for a in articles if a.get("summary_basis") == "title")
    print(f"=== summarize complete: {done}件を要約（うち{thin}件はタイトルのみ） → {target} ===")


if __name__ == "__main__":
    main()
