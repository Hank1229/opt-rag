# Deploy runbook

Backend on Google Cloud Run (us-east1), frontend on Vercel. Every command here is run
by hand from the repo root. Run "Local Docker check" at the bottom before any gcloud step.

Prerequisites:

- OPT-RAG (the Supabase project) holds the ingested corpus. The deployed service reads it
  and nothing else; an empty index makes every answer a refusal.
- `DATABASE_URL` is OPT-RAG's session pooler string (dashboard > Connect > Session pooler),
  with the password URL-encoded:
  `postgresql://postgres.<ref>:<password>@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require`

## 1. One-time Google Cloud setup

```sh
gcloud auth login
```
Signs gcloud in as you.

```sh
export GCP_PROJECT=<project-id>
gcloud config set project "$GCP_PROJECT"
```
Every later command and deploy/cloudrun.sh use this project.

```sh
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
```
Cloud Run serves the API, Cloud Build builds the Dockerfile, Artifact Registry stores the
image, Secret Manager holds the two secrets.

## 2. Secrets

Each value is read from the terminal without echo and piped in on stdin, so it never
lands in a file, the shell history, or the process list.

```sh
printf 'Gemini API key: '; read -rs SECRET; echo
printf '%s' "$SECRET" | gcloud secrets create GEMINI_API_KEY --replication-policy=automatic --data-file=-
```
The key /query uses for embedding and generation.

```sh
printf 'DATABASE_URL: '; read -rs SECRET; echo
printf '%s' "$SECRET" | gcloud secrets create DATABASE_URL --replication-policy=automatic --data-file=-
unset SECRET
```
The session pooler string from the prerequisites.

```sh
RUN_SA="$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
for name in GEMINI_API_KEY DATABASE_URL; do
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor
done
```
Cloud Run runs as the default compute service account; it can read these two secrets and
no others.

To rotate a secret later: `printf '%s' "$SECRET" | gcloud secrets versions add <name> --data-file=-`,
then redeploy (the service mounts `:latest` at instance start).

## 3. Deploy the backend

```sh
deploy/cloudrun.sh
```
Uploads the repo (filtered by .gcloudignore), builds the Dockerfile in Cloud Build, and
deploys service `opt-rag`. The first run asks to create the `cloud-run-source-deploy`
Artifact Registry repository: answer Y. If the build fails with a permission error on the
compute service account, grant it `roles/run.builder` on the project and rerun.

```sh
export API_URL="$(gcloud run services describe opt-rag --region us-east1 --format='value(status.url)')"
echo "$API_URL"
```
The service URL, for Vercel and the smoke tests.

## 4. Deploy the frontend (Vercel dashboard)

1. vercel.com/new: import this GitHub repo.
2. Root Directory: `frontend`. Vercel detects Vite; build command `npm run build`, output `dist`.
3. Environment variable `VITE_API_URL` = the `$API_URL` value, no trailing slash, for
   Production and Preview. Vite inlines it at build time, so a change needs a redeploy.
4. Deploy.
5. Check the production domain is exactly `https://opt-rag.vercel.app`. CORS allows only
   that origin; any other domain needs `CORS_ALLOWED_ORIGINS` changed in deploy/cloudrun.sh
   and a redeploy.

## 5. Verify the deployment

```sh
curl -i "$API_URL/health"
```
Expect `200` and `{"status":"ok"}`.

```sh
SMOKE_BASE_URL="$API_URL" uv run pytest tests/smoke -v
```
Expect 5 passed. The first line prints the first request's time; run this after the
service has been idle for about 15 minutes to record the cold-start number. The two
/query cases make two real Gemini generation calls.

Then open https://opt-rag.vercel.app, ask a question, and check the answer cites sources.

## Local Docker check (before any gcloud step)

```sh
docker build -t opt-rag .
```
Builds the same image Cloud Build will build.

```sh
docker run --rm -p 8080:8080 --env-file .env -e CORS_ALLOWED_ORIGINS=https://opt-rag.vercel.app opt-rag
```
Runs it with the values in .env. `DATABASE_URL` there is OPT-RAG's pooler string, so this
also checks the string Cloud Run will use. `-e` overrides the .env CORS value so the CORS
smoke cases match production. Docker reads .env values literally: quotes around a value
become part of it.

In a second terminal:

```sh
SMOKE_BASE_URL=http://localhost:8080 uv run pytest tests/smoke -v
```
Expect 5 passed.

Stop the container (Ctrl-C), then run it with no settings at all:

```sh
docker run --rm -p 8080:8080 opt-rag
```
A fresh container must start without any env vars.

```sh
curl -i http://localhost:8080/health
curl -i -X POST http://localhost:8080/query -H 'Content-Type: application/json' \
  -d '{"question": "How long is the OPT unemployment limit?"}'
```
Expect `200 {"status":"ok"}`, then `503 {"detail":"DATABASE_URL is not set"}`.
