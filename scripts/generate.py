"""
generate.py  ―  日別JSONを docs/api/ に書き出し、軽量な index.html を生成

以前は全日分のJSONを index.html に埋め込んでいたため、1日20KBずつ
肥大化し（75日で1.5MB）、訪問者は「今日の20件」を見るために全期間を
ダウンロードしていた。ここでは日ごとにJSONを切り出し、ページ本体には
日付一覧（アーカイブ帯に必要な最小限）だけを埋め込む。
"""

import json
import hashlib
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
TMPL_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "docs"
API_DIR = OUTPUT_DIR / "api"

# 過去ログを何日分まで残すか（0なら全部）
MAX_DAYS = 0


def main():
    files = sorted(DATA_DIR.glob("*.json"), reverse=True)
    if not files:
        print("[error] No data files found. Run crawler.py first.")
        return

    if MAX_DAYS > 0:
        files = files[:MAX_DAYS]

    OUTPUT_DIR.mkdir(exist_ok=True)
    API_DIR.mkdir(exist_ok=True)

    days = []
    written = 0
    for f in files:
        try:
            day = json.loads(f.read_text(encoding="utf-8"))
            date_key = day.get("date") or f.stem
            articles = day.get("articles", [])
            articles.sort(key=lambda x: x.get("score", 0), reverse=True)
        except Exception as e:
            print(f"[warn] skip {f.name}: {e}")
            continue

        payload = json.dumps(
            {"date": date_key, "articles": articles},
            ensure_ascii=False, separators=(",", ":"),
        )

        out = API_DIR / f"{date_key}.json"
        # 中身が変わっていなければ書かない（毎日のコミットに差分を出さないため）
        if not out.exists() or out.read_text(encoding="utf-8") != payload:
            out.write_text(payload, encoding="utf-8")
            written += 1

        days.append({
            "d": date_key,
            "n": len(articles),
            "top": max((a.get("score", 0) for a in articles), default=0),
            # 内容が変わったときだけURLが変わるようにして、キャッシュを正しく無効化する
            "v": hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8],
        })

    if not days:
        print("[error] No valid data could be loaded.")
        return

    days.sort(key=lambda x: x["d"], reverse=True)
    index = {"days": days}
    index_json = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    (API_DIR / "index.json").write_text(index_json, encoding="utf-8")

    env = Environment(loader=FileSystemLoader(TMPL_DIR))
    tmpl = env.get_template("index.html.j2")
    html = tmpl.render(index_json=index_json)

    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")

    total = sum(d["n"] for d in days)
    print(f"=== generated: {index_path} ({index_path.stat().st_size:,} bytes) ===")
    print(f"=== {len(days)} days, {total} articles / {written} day-files updated ===")


if __name__ == "__main__":
    main()
