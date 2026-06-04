pipeline {
    agent any

    environment {
        RCA_BACKEND_URL = 'http://127.0.0.1:8000/analyze'
        PIPELINE_LOG_FILE = 'pipeline.log'
        PROJECT_DIR = '/Users/harishkumarr/Downloads/jenkins-ai-agent 2/jenkins-ai-agent-value-edition'
        NODE_PROJECT_DIR = '/Users/harishkumarr/Desktop/justo-sample-app/node-postgres-app'
        NODE_APP_DIR = '/Users/harishkumarr/Desktop/justo-sample-app/node-postgres-app/app'
        DOCKER_IMAGE = 'harishkumar09/node-postgres-app-app'
        NVM_DIR = '/Users/harishkumarr/.nvm'
        NODE_VERSION = 'v22.17.0'
        PATH = '/Users/harishkumarr/.nvm/versions/node/v22.17.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    }

    stages {
        stage('Setup RCA Agent Dependencies') {
            steps {
                sh '''#!/bin/bash
                    set -euo pipefail
                    {
                        echo "Running Jenkins build #${BUILD_NUMBER}"
                        echo "@@RCA_STAGE_START@@ Setup RCA Agent Dependencies"
                        cd "${PROJECT_DIR}"
                        python3 -m venv .venv
                        . .venv/bin/activate
                        python -m pip install --upgrade pip
                        pip install -r requirements.txt
                        echo "@@RCA_STAGE_END@@ Setup RCA Agent Dependencies"
                    } 2>&1 | tee "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
            }
        }

        stage('Validate RCA Backend Code') {
            steps {
                sh '''#!/bin/bash
                    set -euo pipefail
                    {
                        echo "@@RCA_STAGE_START@@ Validate RCA Backend Code"
                        cd "${PROJECT_DIR}"
                        .venv/bin/python -m py_compile main.py database.py models.py
                        echo "@@RCA_STAGE_END@@ Validate RCA Backend Code"
                    } 2>&1 | tee -a "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
            }
        }

        stage('Install Node App Dependencies') {
            steps {
                sh '''#!/bin/bash
                    set -euo pipefail
                    {
                        echo "@@RCA_STAGE_START@@ Install Node App Dependencies"
                        which node
                        which npm
                        node --version
                        npm --version
                        cd "${NODE_APP_DIR}"
                        pwd
                        ls -la
                        test -f package.json
                        npm install
                        echo "@@RCA_STAGE_END@@ Install Node App Dependencies"
                    } 2>&1 | tee -a "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
            }
        }

        stage('Test Node App') {
            steps {
                sh '''#!/bin/bash
                    set -euo pipefail
                    {
                        echo "@@RCA_STAGE_START@@ Test Node App"
                        which npm
                        cd "${NODE_APP_DIR}"
                        test -f package.json
                        npm test
                        echo "@@RCA_STAGE_END@@ Test Node App"
                    } 2>&1 | tee -a "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
            }
        }

        stage('Build Docker Image') {
            steps {
                sh '''#!/bin/bash
                    set -euo pipefail
                    {
                        echo "@@RCA_STAGE_START@@ Build Docker Image"
                        which docker
                        cd "${NODE_PROJECT_DIR}"
                        test -f app/Dockerfile
                        docker build -f app/Dockerfile -t "${DOCKER_IMAGE}:${BUILD_NUMBER}" -t "${DOCKER_IMAGE}:latest" .
                        echo "@@RCA_STAGE_END@@ Build Docker Image"
                    } 2>&1 | tee -a "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
            }
        }

        stage('Push Docker Image') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USERNAME', passwordVariable: 'DOCKER_PASSWORD')]) {
                    sh '''#!/bin/bash
                        set -euo pipefail
                        {
                            echo "@@RCA_STAGE_START@@ Push Docker Image"
                            echo "${DOCKER_PASSWORD}" | docker login -u "${DOCKER_USERNAME}" --password-stdin
                            docker push "${DOCKER_IMAGE}:${BUILD_NUMBER}"
                            docker push "${DOCKER_IMAGE}:latest"
                            docker logout
                            echo "@@RCA_STAGE_END@@ Push Docker Image"
                        } 2>&1 | tee -a "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                    '''
                }
            }
        }
    }

    post {
        unsuccessful {
            sh '''#!/bin/bash
                if [ -f "${PROJECT_DIR}/${PIPELINE_LOG_FILE}" ]; then
                    python3 - <<'PY' || true
import json
import os
import re
import urllib.request

backend_url = os.environ.get("RCA_BACKEND_URL", "http://127.0.0.1:8000/analyze")
build_number = os.environ.get("BUILD_NUMBER", "")
build_url = os.environ.get("BUILD_URL", "")
project_dir = os.environ.get("PROJECT_DIR", ".")
log_file = os.path.join(project_dir, os.environ.get("PIPELINE_LOG_FILE", "pipeline.log"))

with open(log_file, "r", encoding="utf-8", errors="replace") as file:
    full_logs = file.read()

lines = full_logs.splitlines()

stage_start_pattern = re.compile(r"@@RCA_STAGE_START@@\\s*(.+)")
stage_end_pattern = re.compile(r"@@RCA_STAGE_END@@\\s*(.+)")

current_stage = None
stage_lines = {}
stage_order = []

for line in lines:
    start_match = stage_start_pattern.search(line)
    end_match = stage_end_pattern.search(line)

    if start_match:
        current_stage = start_match.group(1).strip()
        stage_order.append(current_stage)
        stage_lines.setdefault(current_stage, [])
        stage_lines[current_stage].append(line)
        continue

    if current_stage:
        stage_lines.setdefault(current_stage, []).append(line)

    if end_match:
        ended_stage = end_match.group(1).strip()
        if current_stage == ended_stage:
            current_stage = None

failed_stage = current_stage or stage_order[-1] if stage_order else "Unknown"

if failed_stage == "Unknown":
    syntax_errors = [r"MultipleCompilationErrorsException", r"WorkflowScript", r"unexpected char", r"unexpected token"]
    if any(any(re.search(p, l, re.IGNORECASE) for p in syntax_errors) for l in lines[-200:]):
        failed_stage = "Pipeline Syntax Error"

focused_logs = "\\n".join(stage_lines.get(failed_stage, lines[-200:]))

payload = json.dumps({
    "build_number": build_number,
    "build_url": build_url,
    "logs": (
        f"Detected Failed Stage: {failed_stage}\\n\\n"
        f"Focused Failed Stage Logs:\\n{focused_logs}"
    )
}).encode("utf-8")

request = urllib.request.Request(
    backend_url,
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=60) as response:
        print(response.read().decode("utf-8", errors="replace"))
except Exception as error:
    print(f"RCA backend alert failed: {error}")
PY
                else
                    echo "No pipeline log file found, skipping RCA alert."
                fi
            '''
        }
    }
}
