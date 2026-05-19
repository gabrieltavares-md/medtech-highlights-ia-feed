# Highlights IA — MedTech Community AI (Podcast Feed)

Feed RSS público do podcast diário **Highlights IA — MedTech Community AI**, apresentado por Gabriel Tavares.

- **Feed RSS (público):** `https://docgabtxsmed.github.io/medtech-highlights-ia-feed/feed.xml`
- **Hospedagem dos episódios:** GitHub Releases (assets) deste repo
- **Distribuição:** Spotify, Apple Podcasts, Amazon Music (via RSS)

## Estrutura

```
.
├── cover.png              ← capa 3000×3000 (servida via GitHub Pages)
├── feed.xml               ← RSS 2.0 + iTunes Podcast namespace
├── episodes.json          ← registro de episódios publicados
├── scripts/
│   └── add_episode.py     ← script chamado pela tarefa agendada
└── README.md
```

## Pipeline automatizado

Uma tarefa agendada (`highlights-ia-diario`) roda em segunda, quarta e sexta às 06:07 e:

1. Pesquisa novidades de IA das últimas 24h
2. Gera o DOCX dos highlights
3. Cria um Audio Overview no NotebookLM
4. Baixa o M4A localmente
5. **Chama `scripts/add_episode.py`** com o M4A, título e descrição
6. O script cria um GitHub Release, faz upload do M4A, atualiza `feed.xml` e `episodes.json`
7. Spotify puxa o novo episódio em ~10-30 min

## Variáveis de ambiente requeridas

| Variável | Descrição |
|---|---|
| `GITHUB_TOKEN` | Personal Access Token com escopo `repo` |
| `GITHUB_OWNER` | `Docgabtxsmed` |
| `GITHUB_REPO`  | `medtech-highlights-ia-feed` |
| `PODCAST_FEED_BASE` | (opcional) base URL pública. Default: `https://<owner>.github.io/<repo>` |

## Uso manual do script

```bash
export GITHUB_TOKEN=ghp_xxx
export GITHUB_OWNER=Docgabtxsmed
export GITHUB_REPO=medtech-highlights-ia-feed

python3 scripts/add_episode.py \
  --m4a /caminho/highlights-ia-2026-05-19-podcast.m4a \
  --title "Highlights IA — 19 de maio de 2026" \
  --description "Resumo dos 6 destaques do dia: Google I/O 2026, ..." \
  --date 2026-05-19
```

Para testar sem chamar o GitHub:

```bash
python3 scripts/add_episode.py --dry-run \
  --m4a ./test.m4a --title "Test" --description "Test ep" --date 2026-05-19
```

## Setup inicial (one-time)

1. **Criar o repo** no GitHub: `Docgabtxsmed/medtech-highlights-ia-feed` (público).
2. **Subir o conteúdo deste diretório** (cover.png, feed.xml, episodes.json, scripts/, README.md).
3. **Ativar GitHub Pages**: Settings → Pages → Source: `Deploy from branch` → branch `main`, folder `/ (root)`.
4. **Criar Personal Access Token (PAT)**: github.com/settings/tokens/new → escopo `repo` → copiar.
5. **Salvar o PAT em local seguro no Mac** (a tarefa agendada vai ler dali). Sugestão: `~/.medtech-secrets/github-pat` com `chmod 600`.
6. **Criar conta no Spotify for Podcasters**: podcasters.spotify.com → "Add via RSS" → colar URL do feed → claim show.
7. **Adicionar verification token do Spotify** ao `feed.xml` (apenas no setup): a Spotify dá um `<podcast:verification />` ou similar para colar no feed.

## Notas legais

Os áudios são gerados via Audio Overview do NotebookLM (Google). Cada episódio inclui na descrição a linha *"Áudio gerado com NotebookLM (Google)"* para transparência. Conforme os Termos de Uso do NotebookLM, o output gerado pertence ao usuário e pode ser distribuído.
