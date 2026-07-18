#!/usr/bin/env python3
"""
podcast_watcher.py — Daemon executado pelo LaunchAgent a cada 5 minutos
no Mac. Detecta M4As novos gerados pela scheduled task highlights-ia-diario
e publica automaticamente no podcast "Highlights IA — MedTech Community AI".

Fluxo:
  1. git pull no repo local (atualiza episodes.json com publicações recentes)
  2. Vasculha ~/Library/Application Support/Claude/local-agent-mode-sessions
     procurando por arquivos `highlights-ia-YYYY-MM-DD-podcast.m4a`
  3. Para cada M4A encontrado:
     - Pula se a data ja foi publicada (cruza com episodes.json local)
     - Pula se hoje nao for seg/qua/sex
     - Le `highlights-ia-YYYY-MM-DD-meta.json` ao lado do M4A (se existir)
       para extrair titulo e descricao
     - Chama add_episode.py via subprocess
  4. Loga tudo em ~/.medtech-secrets/podcast-watcher.log

Como o script roda no Mac (nao no sandbox do Cowork), tem acesso direto a
`~/.medtech-secrets/` e ao repo local — o que resolve a limitacao de
sandbox isolado que a scheduled task tem.
"""

import os
import sys
import re
import json
import base64
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

HOME = Path.home()
WORKSPACE_BASE = HOME / "Library/Application Support/Claude/local-agent-mode-sessions"
REPO_DIR = HOME / "Documents/Claude/podcast/medtech-highlights-ia-feed"
EPISODES_JSON = REPO_DIR / "episodes.json"
ADD_EPISODE = REPO_DIR / "scripts/add_episode.py"
SECRETS_DIR = HOME / ".medtech-secrets"
GITHUB_PAT_FILE = SECRETS_DIR / "github-pat"
LOG_FILE = SECRETS_DIR / "podcast-watcher.log"

# Pastas extras varridas além de WORKSPACE_BASE (ex.: saídas do plugin no vault).
EXTRA_SCAN_DIRS = [
    HOME / "Obsidian/Agentes de IA/_highlights-ia-agentico/plugin/highlights-ia/outputs",
]

PUBLISH_WEEKDAYS = {0, 2, 4}  # 0=monday, 2=wed, 4=fri

# v2: aceita tanto o formato antigo (…-podcast.m4a) quanto o novo por trilha
# (…-medicina|tech|misc-podcast.m4a). group(1)=data, group(2)=trilha (ou None).
PIPELINE_M4A = re.compile(
    r"highlights-ia-(\d{4}-\d{2}-\d{2})(?:-(medicina|tech|misc))?-podcast\.m4a$"
)

# Rótulos de trilha para título/descrição fallback.
TRILHA_LABEL = {
    "medicina": "Medicina & Pesquisa",
    "tech": "Engenharia & Modelos",
    "misc": "Miscelânea",
}

# --- Coverage-bridge (v2): aplica coverage staged pela task headless ---
FEED_OWNER = "gabrieltavares-md"
FEED_REPO = "medtech-highlights-ia-feed"
COVERAGE_PATH = "coverage-history.json"
# Arquivos gerados pela task quando ela não tem credencial de escrita no sandbox:
# outputs/coverage-history-YYYY-MM-DD.staged.json
COVERAGE_STAGED = re.compile(r"coverage-history-(\d{4}-\d{2}-\d{2})\.staged\.json$")


def log(msg: str):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n"
    sys.stdout.write(line)
    try:
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as fh:
            fh.write(line)
    except Exception as exc:
        sys.stderr.write(f"[log error] {exc}\n")


def get_published_guids() -> set:
    """Le episodes.json local para saber o que ja foi publicado."""
    if not EPISODES_JSON.exists():
        log("episodes.json nao encontrado — assumindo vazio")
        return set()
    try:
        with open(EPISODES_JSON) as fh:
            data = json.load(fh)
        return {ep.get("guid") for ep in data.get("episodes", []) if ep.get("guid")}
    except Exception as exc:
        log(f"erro lendo episodes.json: {exc}")
        return set()


def git_pull_repo():
    """Atualiza o repo local para garantir que episodes.json esta fresco."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_DIR), "pull", "--ff-only", "origin", "main"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log(f"git pull warning: {result.stderr.strip()[:200]}")
    except subprocess.TimeoutExpired:
        log("git pull timeout")
    except Exception as exc:
        log(f"git pull erro: {exc}")


def find_pending_m4as() -> list:
    """Encontra M4As gerados pelo pipeline ainda nao publicados.

    Retorna lista de (date_str, (path, trilha)). `trilha` pode ser None
    (formato antigo …-podcast.m4a) ou 'medicina'/'tech'/'misc' (formato v2).
    """
    # Varre WORKSPACE_BASE + pastas extras (ex.: outputs do plugin no vault).
    scan_dirs = [WORKSPACE_BASE, *EXTRA_SCAN_DIRS]
    candidates: list[Path] = []
    for d in scan_dirs:
        if d.exists():
            candidates.extend(d.rglob("highlights-ia-*-podcast.m4a"))
        else:
            log(f"scan dir ausente (ok): {d}")
    if not candidates:
        return []

    published = get_published_guids()
    seen_dates: dict = {}
    for path in candidates:
        match = PIPELINE_M4A.search(path.name)
        if not match:
            continue
        date_str = match.group(1)
        trilha = match.group(2)  # None no formato antigo
        guid = f"episode-{date_str}"
        if guid in published:
            continue
        try:
            weekday = datetime.fromisoformat(date_str).weekday()
        except Exception:
            continue
        if weekday not in PUBLISH_WEEKDAYS:
            continue
        # Mantem apenas o M4A mais recente para cada data
        existing = seen_dates.get(date_str)
        if existing is None or path.stat().st_mtime > existing[0].stat().st_mtime:
            seen_dates[date_str] = (path, trilha)

    return sorted(seen_dates.items())


def format_date_pt(date_str: str) -> str:
    months = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ]
    try:
        d = datetime.fromisoformat(date_str).date()
        return f"{d.day} de {months[d.month - 1]} de {d.year}"
    except Exception:
        return date_str


def default_title(date_str: str, trilha: str | None) -> str:
    label = TRILHA_LABEL.get(trilha or "")
    if label:
        return f"Highlights IA — {label} — {format_date_pt(date_str)}"
    return f"Highlights IA — {format_date_pt(date_str)}"


def load_metadata(m4a_path: Path, date_str: str, trilha: str | None = None) -> tuple:
    """Le o sidecar -meta.json se existir.

    v2: procura primeiro highlights-ia-YYYY-MM-DD-<trilha>-meta.json; se nao
    houver (ou for formato antigo), cai para highlights-ia-YYYY-MM-DD-meta.json.
    """
    candidates = []
    if trilha:
        candidates.append(m4a_path.parent / f"highlights-ia-{date_str}-{trilha}-meta.json")
    candidates.append(m4a_path.parent / f"highlights-ia-{date_str}-meta.json")
    for meta_path in candidates:
        if meta_path.exists():
            try:
                with open(meta_path) as fh:
                    meta = json.load(fh)
                title = meta.get("title") or default_title(date_str, trilha)
                desc = meta.get("description") or default_description()
                return title, desc
            except Exception as exc:
                log(f"erro lendo {meta_path.name}: {exc}")
    log(f"  meta.json ausente para {date_str} ({trilha or 'sem trilha'}), usando fallback generico")
    return default_title(date_str, trilha), default_description()


def default_description() -> str:
    return (
        "Curadoria diaria de novidades em IA, agentes, dados e negocios. "
        "Audio gerado com NotebookLM (Google)."
    )


def publish(date_str: str, m4a_path: Path, trilha: str | None = None) -> bool:
    title, description = load_metadata(m4a_path, date_str, trilha)
    log(f"publicando {date_str} [{trilha or 'sem trilha'}]: {m4a_path.name} ({m4a_path.stat().st_size // (1024*1024)} MB)")
    log(f"  titulo: {title}")

    if not GITHUB_PAT_FILE.exists():
        log("  FAIL: github-pat ausente")
        return False
    if not ADD_EPISODE.exists():
        log(f"  FAIL: add_episode.py ausente em {ADD_EPISODE}")
        return False

    env = os.environ.copy()
    env["GITHUB_TOKEN"] = GITHUB_PAT_FILE.read_text().strip()
    env["GITHUB_OWNER"] = "gabrieltavares-md"
    env["GITHUB_REPO"] = "medtech-highlights-ia-feed"
    env["PODCAST_FEED_BASE"] = "https://docgabtxsmed.github.io/medtech-highlights-ia-feed"

    try:
        cmd = [
            "/usr/bin/env", "python3", str(ADD_EPISODE),
            "--m4a", str(m4a_path),
            "--title", title,
            "--description", description,
            "--date", date_str,
        ]
        if trilha:
            cmd += ["--trilha", trilha]
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        log("  FAIL: timeout no add_episode.py (5 min)")
        return False
    except Exception as exc:
        log(f"  FAIL: excecao no subprocess: {exc}")
        return False

    if result.returncode == 0:
        log(f"  SUCESSO: {date_str}")
        return True

    stderr_tail = (result.stderr or "")[-500:]
    log(f"  FAIL: returncode={result.returncode}")
    log(f"  stderr: {stderr_tail}")
    return False


def _gh(method: str, path: str, token: str, data: bytes | None = None):
    url = f"https://api.github.com/repos/{FEED_OWNER}/{FEED_REPO}/{path}"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "highlights-ia-watcher/2.1")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _ensure_v11(cov: dict) -> dict:
    cov = json.loads(json.dumps(cov))  # deep copy
    cov.setdefault("_window_days", 7)
    tr = cov.setdefault("tracks", {})
    for t in ("medicina", "tech", "misc"):
        tr.setdefault(t, {"last_report": None, "last_edition": 0})
    cov.setdefault("newsletter", {"last_edition": 0})
    cov.setdefault("history", [])
    return cov


def _merge_coverage(base: dict, staged: dict) -> dict:
    base = _ensure_v11(base)
    staged = _ensure_v11(staged)
    by_date = {h.get("date"): h for h in base["history"] if h.get("date")}
    for h in staged["history"]:
        if h.get("date"):
            by_date[h["date"]] = h  # staged vence por data
    base["history"] = sorted(by_date.values(), key=lambda h: h.get("date", ""))
    for t in ("medicina", "tech", "misc"):
        s, b = staged["tracks"].get(t, {}), base["tracks"].get(t, {})
        base["tracks"][t]["last_report"] = max(
            [x for x in (s.get("last_report"), b.get("last_report")) if x], default=None)
        base["tracks"][t]["last_edition"] = max(s.get("last_edition", 0), b.get("last_edition", 0))
    base["newsletter"]["last_edition"] = max(
        staged["newsletter"].get("last_edition", 0), base["newsletter"].get("last_edition", 0))
    return base


def find_staged_coverage() -> list:
    scan_dirs = [WORKSPACE_BASE, *EXTRA_SCAN_DIRS]
    found = []
    for d in scan_dirs:
        if d.exists():
            found.extend(d.rglob("coverage-history-*.staged.json"))
    uniq = {p.resolve(): p for p in found if COVERAGE_STAGED.search(p.name)}
    return sorted(uniq.values(), key=lambda p: COVERAGE_STAGED.search(p.name).group(1))


def apply_staged_coverage():
    """Aplica coverage-history-*.staged.json gerado pela task headless (que não tem
    credencial de escrita no sandbox). Roda TODO dia. Usa o github-pat local + Contents API."""
    staged_files = find_staged_coverage()
    if not staged_files:
        return
    if not GITHUB_PAT_FILE.exists():
        log("coverage: github-pat ausente — não aplico staged")
        return
    token = GITHUB_PAT_FILE.read_text().strip()

    status, body = _gh("GET", f"contents/{COVERAGE_PATH}", token)
    if status >= 300:
        log(f"coverage: GET falhou {status}: {body.decode()[:200]}")
        return
    meta = json.loads(body)
    sha = meta["sha"]
    try:
        remote = json.loads(base64.b64decode(meta["content"]).decode("utf-8"))
    except Exception as exc:
        log(f"coverage: parse do remoto falhou: {exc}")
        return

    remote_v11 = _ensure_v11(remote)
    merged = remote_v11
    applied = []
    for sp in staged_files:
        try:
            merged = _merge_coverage(merged, json.loads(sp.read_text()))
            applied.append(sp)
        except Exception as exc:
            log(f"coverage: staged inválido {sp.name}: {exc}")

    new_bytes = json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")
    old_bytes = json.dumps(remote_v11, ensure_ascii=False, indent=2).encode("utf-8")
    if new_bytes == old_bytes:
        log("coverage: nada novo; marcando staged como aplicados")
        for sp in applied:
            try: sp.rename(sp.with_suffix(".applied"))
            except Exception: pass
        return

    put_body = json.dumps({
        "message": f"chore(coverage): apply staged {datetime.now().date().isoformat()}",
        "content": base64.b64encode(new_bytes).decode(),
        "sha": sha,
        "committer": {"name": "highlights-ia-watcher", "email": "gabrieltavaresx@gmail.com"},
    }).encode()
    status, body = _gh("PUT", f"contents/{COVERAGE_PATH}", token, data=put_body)
    if status >= 300:
        log(f"coverage: PUT falhou {status}: {body.decode()[:200]}")
        return
    log(f"coverage: aplicado ({len(applied)} staged → {len(merged['history'])} entradas)")
    for sp in applied:
        try: sp.rename(sp.with_suffix(".applied"))
        except Exception as exc: log(f"coverage: não renomeei {sp.name}: {exc}")


def main() -> int:
    log("=== podcast-watcher start ===")

    if not REPO_DIR.exists():
        log(f"FATAL: repo nao encontrado em {REPO_DIR}")
        return 1
    if not ADD_EPISODE.exists():
        log(f"FATAL: add_episode.py nao encontrado em {ADD_EPISODE}")
        return 1
    if not GITHUB_PAT_FILE.exists():
        log(f"FATAL: github-pat nao encontrado em {GITHUB_PAT_FILE}")
        return 1

    git_pull_repo()

    # Coverage-bridge (v2): aplica coverage staged pela task headless — TODO dia.
    try:
        apply_staged_coverage()
    except Exception as exc:
        log(f"coverage: erro inesperado: {exc}")

    pending = find_pending_m4as()
    if not pending:
        log("nada para publicar")
        log("=== podcast-watcher end ===\n")
        return 0

    log(f"encontrados {len(pending)} episodio(s) pendente(s)")
    for date_str, (m4a_path, trilha) in pending:
        publish(date_str, m4a_path, trilha)

    log("=== podcast-watcher end ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
