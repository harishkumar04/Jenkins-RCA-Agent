# Jenkins AI RCA Agent - Value Edition

This is an upgraded copy of the original RCA demo. It keeps the same Jenkins-to-FastAPI flow, but adds incident intelligence features that make the project more valuable than a plain Jenkins email alert.

## What This Version Adds

- Recurring incident detection using a stable incident fingerprint.
- Owner routing by category, such as Docker to DevOps or npm to Application Team.
- Smarter RCA emails with severity, owner, recurrence count, and recommended action.
- Dashboard insights for top failure category, impacted owner, and recurring patterns.
- Build-number lookup through `GET /incidents/build/{build_number}`.
- Category, severity, owner, recurrence, and recommendation stored in SQLite.
- Jenkins build URL stored with each incident.
- Recurrence memory showing previous matching builds and prior fix/action.
- Optional read-only application code context through `ENABLE_CODE_CONTEXT=true`.

## Run Locally

```bash
cd "/Users/harishkumarr/Downloads/jenkins-ai-agent 2/jenkins-ai-agent-value-edition"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8001
```

Open the dashboard:

```bash
open "/Users/harishkumarr/Downloads/jenkins-ai-agent 2/jenkins-ai-agent-value-edition/index.html"
```

## Jenkins Setup

Use the `Jenkinsfile` in this folder. It posts failures to:

```text
http://127.0.0.1:8001/analyze
```

Make sure Docker Hub credentials exist in Jenkins with this ID:

```text
dockerhub-creds
```

## Read-Only Code Access

Set these in `.env` if you want the RCA prompt to include small snippets from your app code:

```env
ENABLE_CODE_CONTEXT=true
APP_READONLY_DIR=/Users/harishkumarr/Desktop/justo-sample-app/node-postgres-app
```

The backend only reads allowlisted files such as `package.json`, `Dockerfile`, `.js`, `.yaml`, and docker compose files. It ignores folders like `node_modules`, `.git`, `dist`, and `build`, and it does not write to the app directory.

## Presentation Pitch

Jenkins already tells us that a command failed. This agent turns raw CI/CD logs into incident intelligence: category, severity, owner, recurrence, previous pattern count, suggested fix, prevention step, and recommended action.
