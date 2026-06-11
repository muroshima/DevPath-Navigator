# infra — DevPath Navigator の Terraform

[English](./README.md) &nbsp;|&nbsp; **日本語**

ライブデモを動かしている GCP 環境をコード化したもの。手書きの
`gcloud` コマンドを思い出さなくても、別のプロジェクトで同じ構成を立ち
上げ直せる。

**Terraform で管理しているもの**
- 動作に必要な 12 個の GCP API（Cloud Run、BigQuery、Vertex AI、
  Cloud Build、Artifact Registry、Secret Manager、Storage、IAM、
  IAM Credentials、Cloud Resource Manager、Logging、Monitoring）
- エージェントの実行サービスアカウント `devpath-agent-sa`、その
  プロジェクトレベルの 3 ロール（`aiplatform.user`、`bigquery.jobUser`、
  `logging.logWriter`）、`devpath` データセットスコープの
  `bigquery.dataViewer`、そしてデプロイ実行者向けの
  `iam.serviceAccountUser` バインディング（`deployer_principal` を
  設定したときだけ作られる）
- `asia-northeast1` の BigQuery データセット `devpath`
- Cloud Run サービス `devpath-agent` と `devpath-frontend`（環境変数、
  ランタイム SA との結線、public-invoker の IAM バインディングを含む）

**意図的に Terraform で管理していないもの**
- BigQuery テーブルのスキーマ — `data-gen/load_to_bq.py`、
  `embedding/umap_cluster.py`、`eval/store.py` 側で定義し、コード変更と
  一緒に進化させる（plan/apply のサイクルを介在させない）
- 合成データそのもの — `data-gen/generate.py` が真のソース
- コンテナイメージ — `gcloud run deploy --source .` でビルド/プッシュ
  する。Terraform はサービスの「殻」だけを所有する

## クイックスタート（新規プロジェクトに立ち上げる場合）

```bash
cd infra
terraform init
terraform plan -out=plan.out
terraform apply plan.out
```

初回デプロイでは `agent_image` / `frontend_image` 変数は
`gcloud run deploy --source .` が書き込む Artifact Registry のパスを
デフォルト値として持っている。初回ビルド後はイミュータブルな SHA 固定の
イメージ参照に差し替えるとリビジョンが固定できる。

## 既に稼働しているデモを Terraform に取り込む（state import）

既に動いているリソースを Terraform 管理下に置きたい場合は、最初の
`apply` を行う前に state へ import する:

```bash
cd infra
terraform init

PROJECT=ai-agent-hackathon-499013
REGION=asia-northeast1

# 1) API サービス
for svc in run bigquery aiplatform cloudbuild artifactregistry secretmanager \
           storage iam iamcredentials cloudresourcemanager logging monitoring; do
  terraform import "google_project_service.this[\"$svc.googleapis.com\"]" \
    "$PROJECT/$svc.googleapis.com"
done

# 2) サービスアカウントとプロジェクトレベルのロールバインディング
terraform import google_service_account.agent \
  "projects/$PROJECT/serviceAccounts/devpath-agent-sa@$PROJECT.iam.gserviceaccount.com"

for role in roles/aiplatform.user roles/bigquery.jobUser roles/logging.logWriter; do
  terraform import "google_project_iam_member.agent_runtime_project_roles[\"$role\"]" \
    "$PROJECT $role serviceAccount:devpath-agent-sa@$PROJECT.iam.gserviceaccount.com"
done

# 3) データセットスコープの bigquery.dataViewer は、データセットの import
#    （ステップ 4）後にやる必要があるので一旦飛ばす。ここでは何もしない。

# オプション: terraform.tfvars で `deployer_principal` を設定している場合のみ。
# 設定していない場合は iam.tf 側で count = 0 となりこのリソースは作られない
# ので、import も不要。実行する場合は <deployer_principal> を tfvars と
# 同じ値（例: `user:foo@example.com` / `serviceAccount:builder@…`）に
# 置き換えてコメントアウトを外す。
#
# DEPLOYER='user:foo@example.com'
# terraform import 'google_service_account_iam_member.deployer_act_as_agent[0]' \
#   "projects/$PROJECT/serviceAccounts/devpath-agent-sa@$PROJECT.iam.gserviceaccount.com roles/iam.serviceAccountUser $DEPLOYER"

# 4) BigQuery データセット
terraform import google_bigquery_dataset.devpath "projects/$PROJECT/datasets/devpath"

# 5) データセットスコープの bigquery.dataViewer（ステップ 3 から繰り越し）
terraform import google_bigquery_dataset_iam_member.agent_devpath_reader \
  "projects/$PROJECT/datasets/devpath roles/bigquery.dataViewer serviceAccount:devpath-agent-sa@$PROJECT.iam.gserviceaccount.com"

# 6) Cloud Run サービス + public-invoker バインディング
terraform import google_cloud_run_v2_service.agent \
  "projects/$PROJECT/locations/$REGION/services/devpath-agent"
terraform import google_cloud_run_v2_service.frontend \
  "projects/$PROJECT/locations/$REGION/services/devpath-frontend"

terraform import "google_cloud_run_v2_service_iam_member.agent_public" \
  "projects/$PROJECT/locations/$REGION/services/devpath-agent roles/run.invoker allUsers"
terraform import "google_cloud_run_v2_service_iam_member.frontend_public" \
  "projects/$PROJECT/locations/$REGION/services/devpath-frontend roles/run.invoker allUsers"

# import で想定外の差分が出ていないか確認:
terraform plan
```

import 直後の `terraform plan` は、ほぼ確実に Cloud Run の env 変数や
ラベルの一部に差分を出してくる。`apply` する前に内容を確認すること。
特に `agent_image` 変数は、現在動いているイメージの SHA を指すよう
明示的に設定する必要がある
（`gcloud run services describe devpath-agent --format="value(spec.template.spec.containers[0].image)"`
で確認できる）。

## バックエンド

ハッカソン用途では state はローカルに置いている。共有運用に移行する前に
GCS バックエンドに切り替えること:

```hcl
# versions.tf
backend "gcs" {
  bucket = "devpath-tfstate"
  prefix = "infra"
}
```

```bash
gcloud storage buckets create gs://devpath-tfstate --location=asia-northeast1
terraform init -migrate-state
```
