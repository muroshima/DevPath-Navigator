# DevPath Navigator

[English](./README.md) &nbsp;|&nbsp; **日本語**

エンジニアのキャリアの軌跡をベクトル化して 2D マップ上に投影し、
Gemini エージェントが「似た軌跡を歩んだエンジニアの実際の次の一手」
を根拠付きで推薦するキャリアナビゲーター。

[**▶ ライブデモ**](https://devpath-frontend-430189693163.asia-northeast1.run.app)
&middot; [Agent API (Swagger)](https://devpath-agent-430189693163.asia-northeast1.run.app/docs)
&middot; [アーキテクチャ](./ARCHITECTURE.ja.md)

## 30 秒ツアー

[![サムネイルをクリックして 30 秒の概要を再生](./docs/demo-30s-thumb.jpg)](./docs/demo-30s.mp4)

> GitHub の README は `<video>` タグを strip するのでサムネイル
> クリックで MP4 を再生する形式に。再学習ダッシュボードまで含む
> 90 秒のサブミッション動画は
> [`docs/demo-90s.mp4`](./docs/demo-90s.mp4)。

## なぜ作ったか

エンジニアの多くは、次のキャリアを「先輩個人の経験談 (n=1)」や
リクルーターの売り込みから決めている。本来は「自分と似た経歴を歩んだ
何百人のエンジニアが実際に次にどう進んだか」が判断材料になるべきだが、
その情報は社内 HR システムやばらばらのキャリアページに閉じ込められた
まま、構造化されていない。

DevPath Navigator はキャリア履歴を role / tech / seniority のトークン列
として扱い、合成データのコーパス上で埋め込みを学習し、その空間を会話
でクエリできるようにする。エージェントが現在地を特定し、似た軌跡の
エンジニアを見つけ、彼らが次に踏んだステップを **実際の軌跡**（例:
「backend(4y) → ml(2y) → platform に進んだ 12 名」）で提示する。

## できること

- **会話型エージェント** — Gemini 2.5 Flash + Google ADK、7 ツール
  （プロフィール正規化 → 現在地特定 → 類似軌跡検索 → ギャップ分析 →
  次の一手推薦）の多段推論。ツール呼び出しはフロントで即時可視化
- **2 種類の入力モード** — *シンプル*（自然言語の textarea）と
  *詳細*（構造化ステップフォーム）。バックエンドは両モード共通
- **インタラクティブな 2D マップ** — 純 SVG UMAP / HDBSCAN 散布図。
  現在地が脈動し、推薦経路が近傍コーパス重心へ曲線矢印で伸びる
- **自己更新するモデル** — 新データで Cloud Build が再学習を起動、
  評価ゲート（Recall@10 + archetype 別最小値）が指標劣化を弾けば
  自動でリビジョン入れ替え。履歴は `/dashboard`
- **本番品質のデプロイ** — Cloud Run + Terraform + 公開エンドポイントの
  レート制限 + データセットスコープ IAM + 月額予算アラート

## スタック

| レイヤ | 技術 |
|---|---|
| エージェント | FastAPI · Google Agent Development Kit · Vertex AI 上の Gemini 2.5 Flash |
| フロントエンド | Next.js 15 · React 19 · TypeScript · Tailwind CSS |
| 埋め込み | Word2Vec (gensim) · UMAP · HDBSCAN |
| データ | BigQuery (`VECTOR_SEARCH`) · 合成コーパス |
| 再学習 | Cloud Build · Cloud Run リビジョン · `eval_results` |
| ホスティング | Cloud Run · Terraform 管理 |

**Vertex AI 接続** — `google-genai` SDK の `vertexai=True` 経由で
`gemini-2.5-flash` を呼び出し（[`agent/agent.py`](./agent/agent.py)、
[`agent/server.py:38`](./agent/server.py)、
[`infra/cloudrun.tf`](./infra/cloudrun.tf)）。エージェント SA は
`roles/aiplatform.user`（[`infra/iam.tf`](./infra/iam.tf)）。
embedding は Vertex AI ではなく Word2Vec をローカル算出 —
〜1,500 件と小規模なため `workers=1` で 〜3 秒、決定論的・無料。

## アーキテクチャ

![システムアーキテクチャ](./docs/architecture.ja.drawio.svg)

編集可能なソース:
[`docs/architecture.ja.drawio`](./docs/architecture.ja.drawio)。
各サブシステムの設計判断は
[ARCHITECTURE.ja.md](./ARCHITECTURE.ja.md) を参照。

## クイックスタート

### 前提

- macOS または Linux、Python 3.12+（`uv` で管理）、Node.js 22+
- 対象 GCP プロジェクトへ認証済みの `gcloud`

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <your-project-id>
uv sync
```

### コーパス生成 → 埋め込み学習

```bash
uv run python data-gen/generate.py   --batch initial
uv run python data-gen/load_to_bq.py --batch initial --recreate-table
uv run python data-gen/generate.py   --batch drift
uv run python data-gen/load_to_bq.py --batch drift

uv run python embedding/train_w2v.py    --batches initial drift
uv run python embedding/umap_cluster.py --batches initial drift
```

### ローカル起動

```bash
# ターミナル 1 — エージェントを :8088 で（〜3 秒で BQ から W2V 学習）
AGENT_BATCHES=initial,drift uv run uvicorn agent.server:app \
  --host 127.0.0.1 --port 8088

# ターミナル 2 — フロントを :3000 で
cd frontend && npm install
AGENT_URL=http://127.0.0.1:8088 npm run dev
```

### ライブエージェントを直接叩く

```bash
curl -sS https://devpath-agent-430189693163.asia-northeast1.run.app/health
# → {"status":"ok"}

# レート制限あり（IP 単位で 5 burst / 0.25 rps）
curl -sS https://devpath-agent-430189693163.asia-northeast1.run.app/chat \
  -H 'content-type: application/json' \
  -d '{"user_id":"demo","message":"backend を 5 年。SRE に進むなら何が足りませんか？"}' | jq .
```

エンドポイント一覧は
[`/docs`](https://devpath-agent-430189693163.asia-northeast1.run.app/docs)
（FastAPI Swagger）。

## デモシナリオ — 再学習ループ

1. **ベースライン:** initial コーパスのみで学習。「ML エンジニアの次の
   一手は？」と聞くと data-engineering 系のパスが返る（コーパスに
   `genai_engineer` への遷移がまだないため）。
2. **ドリフト注入:** ml_engineer → genai_engineer の 300 名を追加投入。
   Cloud Build が自動で再学習を回し、評価ゲートが指標劣化を弾けば
   新リビジョンへ自動切替。同じ質問の応答に `genai_engineer` が
   入り、ドリフトコホートの実軌跡が根拠として引用される。

```bash
uv run python eval/run.py --batches initial --notes baseline
pipelines/inject-drift.sh   # → Cloud Build → ゲート → pass なら deploy
```

各再学習の判定理由付き履歴は
[`/dashboard`](https://devpath-frontend-430189693163.asia-northeast1.run.app/dashboard)。

## 合成データ前提

本リポジトリは **合成データのみ** を含む。実在の従業員・候補者・
第三者の人事データは一切使われていない。コーパスは
`data-gen/generate.py` が固定シードから 1,500 件の軌跡を再現
（生成スクリプト自体が正本）。6 archetype、多重ロール、ロール別
経験年数、横断ノイズで現実的なクラスタ形状に。

## ドキュメント

- [ARCHITECTURE.ja.md](./ARCHITECTURE.ja.md) — 設計判断と理由
- [infra/README.ja.md](./infra/README.ja.md) — Terraform セットアップ
- [CONTRIBUTING.md](./CONTRIBUTING.md) — ブランチ / コミット / レビュー
- [scripts/demo/README.md](./scripts/demo/README.md) — デモ動画の生成方法

## ライセンス

Apache License 2.0。詳細は [LICENSE](./LICENSE) を参照。
