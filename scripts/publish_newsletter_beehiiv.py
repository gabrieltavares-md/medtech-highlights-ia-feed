#!/usr/bin/env python3
"""
publish_newsletter_beehiiv.py — Cria a newsletter semanal como RASCUNHO no beehiiv.

Regra de ouro: SEMPRE cria como `draft`. NUNCA dispara email para a lista —
a revisão e o envio são feitos por Gabriel no painel do beehiiv.

Fluxo:
  1. Lê o .md/.mdx da newsletter (gerado pelo hia-redator em outputs/).
  2. Separa o frontmatter (title, date, edition, excerpt) do corpo.
  3. Converte o corpo Markdown -> HTML.
  4. POST /v2/publications/{pub_id}/posts com body_content (HTML) e status=draft.

Credencial: ~/.medtech-secrets/beehiiv-api-key (chmod 600) — nunca no repo.

Uso:
  python3 scripts/publish_newsletter_beehiiv.py --md <caminho.md> [--dry-run]

Dependência: markdown  (pip3 install markdown --break-system-packages)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.beehiiv.com/v2"
PUBLICATION_ID = os.environ.get(
    "BEEHIIV_PUBLICATION_ID", "pub_ac6c3f93-8a7d-427d-9e59-d310e25e7b9d"
)
KEY_FILE = Path.home() / ".medtech-secrets" / "beehiiv-api-key"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Separa frontmatter YAML simples (key: value) do corpo. Sem dependência de pyyaml."""
    meta: dict = {}
    body = text
    if text.lstrip().startswith("---"):
        raw = text.lstrip()
        end = raw.find("\n---", 3)
        if end != -1:
            block = raw[3:end]
            body = raw[end + 4:].lstrip("\n")
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def md_to_html(md_body: str) -> str:
    try:
        import markdown  # type: ignore
    except ImportError:
        print("ERRO: falta a lib 'markdown'. Rode:\n"
              "  pip3 install markdown --break-system-packages", file=sys.stderr)
        sys.exit(2)
    return markdown.markdown(
        md_body, extensions=["extra", "sane_lists", "smarty"]
    )


def gh_post(url: str, token: str, payload: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, type=Path, help="Arquivo .md/.mdx da newsletter")
    ap.add_argument("--dry-run", action="store_true",
                    help="Mostra o payload e NÃO chama a API")
    ap.add_argument("--out-html", type=Path, default=None,
                    help="PLANO B: converte para HTML e salva no caminho dado, "
                         "sem chamar a API nem precisar de chave. Abra no navegador, "
                         "copie tudo e cole no editor do beehiiv.")
    args = ap.parse_args()

    if not args.md.exists():
        print(f"ERRO: arquivo não encontrado: {args.md}", file=sys.stderr)
        return 2

    meta, body_md = parse_frontmatter(args.md.read_text(encoding="utf-8"))
    title = meta.get("title") or args.md.stem
    subtitle = meta.get("excerpt") or ""
    html = md_to_html(body_md)

    # --- PLANO B: só gerar HTML para colar no editor (sem API, sem chave) ---
    if args.out_html:
        doc = (
            '<!doctype html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{title}</title>\n"
            "<style>body{max-width:720px;margin:40px auto;padding:0 20px;"
            "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
            "line-height:1.65;color:#1f2937}"
            "h1{font-size:1.75rem;line-height:1.25}h2{margin-top:2.2rem;font-size:1.25rem}"
            "a{color:#0d9488}li{margin:.3rem 0}"
            "blockquote{border-left:3px solid #e5e7eb;margin-left:0;padding-left:1rem;color:#4b5563}"
            "</style>\n</head>\n<body>\n"
            # evita título duplicado se o corpo já começa com um <h1>
            + ("" if html.lstrip().startswith("<h1") else f"<h1>{title}</h1>\n")
            + (f"<p><em>{subtitle}</em></p>\n" if subtitle else "")
            + html
            + "\n</body>\n</html>\n"
        )
        args.out_html.parent.mkdir(parents=True, exist_ok=True)
        args.out_html.write_text(doc, encoding="utf-8")
        print(f"Título: {title}")
        print(f"✅ HTML salvo em: {args.out_html}")
        print("Abra no navegador → Cmd+A → Cmd+C → cole no editor do beehiiv.")
        return 0

    payload = {
        "title": title,
        "body_content": html,
        "status": "draft",          # NUNCA publicar/enviar automaticamente
    }
    if subtitle:
        payload["subtitle"] = subtitle

    print(f"Publicação: {PUBLICATION_ID}")
    print(f"Título:     {title}")
    print(f"Subtítulo:  {subtitle or '(vazio)'}")
    print(f"HTML:       {len(html):,} chars")
    print(f"Status:     draft (revisão e envio manuais no painel)")

    if args.dry_run:
        print("\n[DRY-RUN] não chamei a API. Prévia do HTML (600 chars):\n")
        print(html[:600])
        return 0

    if not KEY_FILE.exists():
        print(f"ERRO: credencial ausente em {KEY_FILE}", file=sys.stderr)
        return 2
    token = KEY_FILE.read_text().strip()

    url = f"{API_BASE}/publications/{PUBLICATION_ID}/posts"
    status, resp = gh_post(url, token, payload)
    if status >= 300:
        print(f"ERRO {status} do beehiiv:\n{resp[:800]}", file=sys.stderr)
        print("\nDica: se reclamar de campo inválido, ajustar o payload conforme "
              "https://developers.beehiiv.com/api-reference/posts/create", file=sys.stderr)
        return 1

    try:
        data = json.loads(resp).get("data", {})
        print(f"\n✅ Rascunho criado. id={data.get('id','?')} status={data.get('status','?')}")
    except Exception:
        print(f"\n✅ Requisição aceita. Resposta:\n{resp[:400]}")
    print("Revise e envie manualmente no painel do beehiiv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
