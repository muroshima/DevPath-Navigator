# DevPath Navigator

[English](./README.md) &nbsp;|&nbsp; **日本語**

![DevPath Navigator hero](./docs/hero.png)

エンジニアのキャリア軌跡をベクトル化して 2D マップ上に投影し、Gemini
エージェントが「似た軌跡を歩んだエンジニアの実際の次の一手」を根拠付きで
推薦するキャリアナビゲーター。

[**▶ ライブデモ**](https://devpath-frontend-430189693163.asia-northeast1.run.app)
&middot; [Agent API](https://devpath-agent-430189693163.asia-northeast1.run.app)
&middot; [Architecture](./ARCHITECTURE.ja.md)

![Career clusters](./docs/cluster_map.png)

## なぜ作ったか

エンジニアの多くは、次のキャリアを「先輩個人の経験談（n=1）」やリクルーターの
売り込みから決めている。本来は「自分と似た経歴を歩んだ何百人のエンジニアが
実際に次にどう進んだか」が判断材料になるべきだが、その情報は社内 HR
システムやばらばらのキャリアページに閉じ込められたまま、構造化されていない。

DevPath Navigator はキャリア履歴を role / tech / seniority のトークン列と
して扱い、合成データのコーパス上で埋め込みを学習し、その空間を会話で
クエリできるようにする。あなたが自分のキャリアを説明すると、エージェントは
マップ上の現在地を特定し、似た軌跡のエンジニアを見つけ、彼らが次に踏んだ
ステップを **実際の軌跡（例:「backend(4y) → ml(2y) → platform に進んだ
12 名」）を根拠として** 提示する。生の employee_id を会話に持ち込むのでは
なく、軌跡の形そのものを引用するので人間が読みやすい。ID 自体は推論ログ
パネルにツール出力として残るので、詳細を見たいときに辿れる。

## できること

- **会話型キャリアエージェント** — Gemini 2.5 Flash + Google Agent
  Development Kit + 7 ツール（プロフィール正規化 → 現在地特定 → 類似軌跡検索
  → ギャップ分析 → 次の一手推薦）の多段推論。質問に応じてエージェントが
  ツール連鎖を選ぶ様子は、フロントの推論ログパネルでリアルタイムに可視化される。
- **2 種類のプロフィール入力モード** — *シンプル*（デフォルト）は
  「backend を 5 年（Java/Postgres）、その後 ML を 2 年（PyTorch）。SRE に
  進みたい」のような自然言語入力で、`normalize_profile` ツールが taxonomy に
  整形する。*詳細* はステップごとに role + 経験年数 + 技術スタックを
  構造化入力できるパワーユーザー向けフォーム。バックエンドは両モードで
  共通で、シンプルは LLM に intake パースを任せるだけ。
- **インタラクティブな 2D キャリアマップ** — 純 SVG で実装した
  UMAP / HDBSCAN 散布図（〜1,500点）。あなたの現在地が黄色く脈動し、
  推薦された次の一手は近傍コーパス重心へ向かう曲線矢印として描かれる。
- **自己更新するモデル** — BigQuery に新しいキャリアデータが到着すると
  Cloud Build パイプラインが起動し、埋め込みを再学習、評価ゲート
  （Recall@10 + archetype 被覆）が指標劣化を弾けば自動で新リビジョンを
  リリース。再学習履歴は `/dashboard` で確認できる。
- **再現可能な合成コーパス** — `data-gen/` が決定的シードから 1,500 件の
  キャリア軌跡を生成（多重ロール + 各ロール年数 + 横断ノイズ）。実在の
  人事データは一切不要。
- **本番品質のデプロイ** — Cloud Run でフロント・エージェントの両サービスを
  公開、インフラは Terraform でコード化。CI に gitleaks（履歴含むシークレット
  スキャン）、公開エンドポイントはレート制限 + CORS 制限 +
  入力長 cap、IAM はデータセット単位スコープ、月額予算アラートを設定済み。

## スタック

| レイヤ | 技術 |
|---|---|
| エージェント | FastAPI · Google Agent Development Kit · Vertex AI 上の Gemini 2.5 Flash |
| フロントエンド | Next.js 15 (App Router) · React 19 · TypeScript · Tailwind CSS · SVG |
| 埋め込み | Word2Vec (gensim) · UMAP · HDBSCAN |
| データ | BigQuery (`VECTOR_SEARCH`) · 合成コーパス |
| 再学習 | Cloud Build · Cloud Run リビジョンロールアウト · BigQuery `eval_results` |
| ホスティング | Cloud Run（エージェント + フロントエンド）· Terraform 管理 |

## アーキテクチャ

![システムアーキテクチャ](./docs/architecture.ja.drawio.svg)

図のソースは [`docs/architecture.ja.drawio`](./docs/architecture.ja.drawio)
で、ファイルをダブルクリックすれば draw.io デスクトップアプリで開いて
編集できる（[diagrams.net](https://app.diagrams.net) のブラウザ版でも可。
SVG 自体にも同じ XML が埋め込まれているので、SVG を直接 draw.io に
ドロップしても編集できる）。
各サブシステムの設計判断は [ARCHITECTURE.ja.md](./ARCHITECTURE.ja.md)
を参照。

## クイックスタート

### 前提

- macOS または Linux
- Python 3.12 以上（`uv` で自動管理）
- Node.js 22 以上
- 対象 GCP プロジェクトへの権限を持つ `gcloud` CLI

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project ai-agent-hackathon-499013

uv sync
```

### コーパス生成とモデル学習

```bash
# 合成コーパス → BigQuery
uv run python data-gen/generate.py   --batch initial
uv run python data-gen/load_to_bq.py --batch initial --recreate-table
uv run python data-gen/generate.py   --batch drift
uv run python data-gen/load_to_bq.py --batch drift

# 埋め込み + クラスタリング
uv run python embedding/train_w2v.py    --batches initial drift
uv run python embedding/umap_cluster.py --batches initial drift
uv run python embedding/plot.py
```

### エージェントとフロントをローカル起動

```bash
# ターミナル 1 — エージェントを :8088 で起動（〜3秒で BQ から W2V 学習）
AGENT_BATCHES=initial,drift uv run uvicorn agent.server:app \
  --host 127.0.0.1 --port 8088

# ターミナル 2 — フロントを :3000 で起動
cd frontend && npm install
AGENT_URL=http://127.0.0.1:8088 npm run dev
```

ブラウザで `http://127.0.0.1:3000` を開く。

### コマンドラインからエージェントを叩く

```bash
curl -sS http://127.0.0.1:8088/chat \
  -H 'content-type: application/json' \
  -d '{
    "user_id": "alice",
    "message": "backend を5年（Java / Postgres、その後 Go と Kubernetes）やってきた mid level です。SRE に進むなら何が足りませんか？"
  }' | jq .
```

## デモシナリオ — 再学習ループ

本プロジェクトの中核となる「まわす」軸のストーリー。状態が 2 つ:

1. **ベースライン:** initial コーパス（5 archetype、1,200 名）のみで学習。
   `genai_engineer` への遷移は含まれていないので、エージェントに「ML
   エンジニアの次の一手は？」と聞くと、データエンジニア系のパスしか
   返らない。
2. **ドリフト注入後:** ml_engineer → genai_engineer の 300 名を追加投入。
   Cloud Build が自動で再学習を回し、評価ゲートが指標劣化を弾けば
   エージェントが新リビジョンに切り替わる。同じ質問への応答には
   `genai_engineer` への遷移が含まれ、ドリフトコホートの軌跡（例:
   「ml_engineer(2y) → genai_engineer」）が根拠として引用される。

```bash
# 1) ベースラインを記録
uv run python eval/run.py --batches initial --notes baseline

# 2) ドリフトを注入 — Cloud Build が自動起動して再学習。ゲートが pass
#    なら自動デプロイ、fail なら理由付きでブロック
pipelines/inject-drift.sh
```

再学習ごとの判定履歴は
[`/dashboard`](https://devpath-frontend-430189693163.asia-northeast1.run.app/dashboard)
か、BigQuery で直接確認できる:

```sql
SELECT run_at, batches, recall_at_10, n_clusters, archetypes_covered, decision
FROM `ai-agent-hackathon-499013.devpath.eval_results`
ORDER BY run_at DESC;
```

## 合成データ前提

本リポジトリには **合成データのみ** が含まれる。実在の従業員・採用候補者・
第三者の人事データは一切使われていない。コーパスは
`data-gen/generate.py` が固定シードから生成するので、クローンすれば
誰でも同じ 1,500 件の軌跡を再現できる（生成スクリプト自体が正本）。

コーパスは構造を持つ: 6 種類のキャリアアーキタイプ、現実的な多重ロール
ステップ（例「backend を 4 年やりつつ、最後の 1.5 年はテックリードも兼任」）、
埋め込みの重みに反映される per-role tenure、そしてアーキタイプ間の横断
detour を制御された割合で混入させ、HDBSCAN クラスタが「合成データ臭く
ない程度に曖昧」になるよう設計してある。

## ドキュメント

- [ARCHITECTURE.ja.md](./ARCHITECTURE.ja.md) — システム、データモデル、
  埋め込み、エージェント、再学習ループ、評価、セキュリティの設計詳細
- [infra/README.ja.md](./infra/README.ja.md) — Terraform 設定（API 有効化 /
  IAM / BigQuery dataset / Cloud Run サービス）の運用ドキュメント

## ライセンス

Apache License 2.0。詳細は [LICENSE](./LICENSE) を参照。
