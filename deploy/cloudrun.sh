#!/usr/bin/env bash
# Builds the repo's Dockerfile with Cloud Build and deploys it as the opt-rag Cloud Run
# service. One-time setup (APIs, secrets, IAM) is in deploy/README.md.
# Usage: GCP_PROJECT=<project-id> deploy/cloudrun.sh
set -euo pipefail

: "${GCP_PROJECT:?set GCP_PROJECT to the Google Cloud project id}"

cd "$(dirname "$0")/.."

# --max-instances and --concurrency are a cost and connection cap, not a capacity choice:
# at most 10 requests at once, each holding one session-pooler connection and one Gemini call.
# --set-env-vars splits on commas: a second CORS origin needs gcloud's custom
# delimiter syntax, e.g. --set-env-vars "^@^CORS_ALLOWED_ORIGINS=a,b@RETRIEVAL_TOP_K=5".
gcloud run deploy opt-rag \
  --source . \
  --project "$GCP_PROJECT" \
  --region us-east1 \
  --min-instances 0 \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 1 \
  --concurrency 10 \
  --allow-unauthenticated \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,DATABASE_URL=DATABASE_URL:latest \
  --set-env-vars GEMINI_GENERATION_MODEL=gemini-3.6-flash,RETRIEVAL_TOP_K=5,CORS_ALLOWED_ORIGINS=https://opt-rag.vercel.app
