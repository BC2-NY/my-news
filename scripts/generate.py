"""
generate.py  ―  JSON データから Jinja2 テンプレートで index.html を生成
"""

import json
import shutil
from datetime import date
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TODAY = date.today().isoformat()
ROOT = Path(__file__).parent.parent
DATA_DIR    = ROOT / "data"
TMPL_DIR    = ROOT / "templates"
OUTPUT_DIR  = ROOT / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)


def main():
    target = DATA_DIR / f"{TODAY}.json"
    if not target.exists():
        # フォールバック：最新のJSONを使う
        files = sorted(DATA_DIR.glob("*.json"), reverse=True)
        if not files:
            print("[error] No data files found. Run crawler.py first.")
            return
        target = files[0]
        print(f"[warn] Today's data not found, using {target.name}")

    data = json.loads(target.read_text(encoding="utf-8"))

    # スコアが高い順にソート（すでにソート済みのはずだが念のため）
    data["articles"].sort(key=lambda x: x.get("score", 0), reverse=True)

    env = Environment(loader=FileSystemLoader(TMPL_DIR))
    tmpl = env.get_template("index.html.j2")
    html = tmpl.render(**data)

    out_path = OUTPUT_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"=== generated: {out_path} ({len(data['articles'])} articles) ===")

    # アーカイブ用に日付ファイルも保存
    archive_path = OUTPUT_DIR / f"{data['date']}.html"
    shutil.copy(out_path, archive_path)
    print(f"=== archived: {archive_path} ===")


if __name__ == "__main__":
    main()
