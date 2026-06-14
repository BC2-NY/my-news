"""
generate.py  ―  全日付の JSON をまとめて1つの index.html を生成（日付セレクタ対応）

docs/index.html に、過去すべての日付のニュースを埋め込む。
ページ内の日付ドロップダウンでJSが表示を切り替える（サーバー不要）。
"""

import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
TMPL_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)

# 過去ログを何日分まで保持するか（古いものは一覧から外す。0なら全部保持）
MAX_DAYS = 0


def main():
    files = sorted(DATA_DIR.glob("*.json"), reverse=True)
    if not files:
        print("[error] No data files found. Run crawler.py first.")
        return

    if MAX_DAYS > 0:
        files = files[:MAX_DAYS]

    # 日付 → その日のデータ、の辞書を作る
    all_data = {}
    for f in files:
        try:
            day = json.loads(f.read_text(encoding="utf-8"))
            date_key = day.get("date") or f.stem
            day["articles"].sort(key=lambda x: x.get("score", 0), reverse=True)
            all_data[date_key] = day
        except Exception as e:
            print(f"[warn] skip {f.name}: {e}")

    if not all_data:
        print("[error] No valid data could be loaded.")
        return

    # JSをそのまま使えるよう、辞書をJSON文字列にしてテンプレートに渡す
    all_data_json = json.dumps(all_data, ensure_ascii=False)

    env = Environment(loader=FileSystemLoader(TMPL_DIR))
    tmpl = env.get_template("index.html.j2")
    html = tmpl.render(all_data_json=all_data_json)

    out_path = OUTPUT_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")

    days = len(all_data)
    total_articles = sum(len(d["articles"]) for d in all_data.values())
    print(f"=== generated: {out_path} ===")
    print(f"=== {days} days, {total_articles} articles total ===")


if __name__ == "__main__":
    main()
