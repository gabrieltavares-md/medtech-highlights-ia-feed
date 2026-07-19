#!/usr/bin/env python3
"""
prune_episodes.py — Remove episódios do feed.xml + episodes.json por guid.

NÃO deleta o objeto no R2 (fica órfão, inofensivo). Idempotente: rodar 2x não
quebra. Rode APÓS `git pull` (para o local ter os itens que o add_episode.py
subiu via API). Depois revise com `git diff` e commite.

Uso:  python3 scripts/prune_episodes.py
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FEED = REPO / "feed.xml"
EPS = REPO / "episodes.json"

# Os 15 episódios antigos (curadoria diária personalizada, mai–jul, sem trilha)
# que subiram no destravamento do watcher. Recomeço limpo para o relançamento v2.
PRUNE_DATES = [
    "2026-05-27", "2026-05-29", "2026-06-01", "2026-06-03", "2026-06-08",
    "2026-06-12", "2026-06-15", "2026-06-19", "2026-06-24", "2026-06-26",
    "2026-07-01", "2026-07-06", "2026-07-13", "2026-07-15", "2026-07-17",
]
PRUNE = {f"episode-{d}" for d in PRUNE_DATES}


def main() -> int:
    # --- episodes.json ---
    eps = json.loads(EPS.read_text())
    before = len(eps.get("episodes", []))
    eps["episodes"] = [e for e in eps.get("episodes", []) if e.get("guid") not in PRUNE]
    removed_json = before - len(eps["episodes"])
    EPS.write_text(json.dumps(eps, indent=2, ensure_ascii=False) + "\n")

    # --- feed.xml ---
    feed = FEED.read_text()
    removed_xml = 0

    def drop(m):
        nonlocal removed_xml
        block = m.group(0)
        if any(g in block for g in PRUNE):
            removed_xml += 1
            return ""
        return block

    feed = re.sub(r"\s*<item>.*?</item>", drop, feed, flags=re.DOTALL)
    FEED.write_text(feed)

    print(f"episodes.json: removidos {removed_json} (restam {len(eps['episodes'])})")
    print(f"feed.xml:      removidos {removed_xml} <item>")
    if removed_json != len(PRUNE) or removed_xml != len(PRUNE):
        print(f"⚠️  Esperado remover {len(PRUNE)} de cada. "
              f"Se divergiu, confira o git diff antes de commitar "
              f"(pode ser que alguns já não estivessem, ou o local não fez pull).",
              file=sys.stderr)
    else:
        print(f"✅ OK: {len(PRUNE)} episódios removidos de ambos os arquivos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
