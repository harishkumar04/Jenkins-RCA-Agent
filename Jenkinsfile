pipeline {
    agent any

    environment {
        RCA_BACKEND_URL = 'http://127.0.0.1:8000/analyze'
        PIPELINE_LOG_FILE = 'pipeline.log'
        PROJECT_DIR = '/Users/harishkumarr/Downloads/jenkins-ai-agent 2'
    }

    stages {
        stage('Setup Python On macOS') {
            steps {
                sh '''#!/bin/bash
                    set -o pipefail
                    {
                        echo "Running Jenkins build #${BUILD_NUMBER}"
                        echo "Stage: Setup Python On macOS"
                        cd "${PROJECT_DIR}"
                        python3 -m venv .venv
                        . .venv/bin/activate
                        python -m pip install --upgrade pip
                        pip install -r requirements.txt
                    } 2>&1 | tee "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
            }
        }

        stage('Run Build') {
            steps {
                sh '''#!/bin/bash
                    set -o pipefail
                    {
                        echo "Stage: Run Build"
                        cd "${PROJECT_DIR}"
                        .venv/bin/python -m py_compile main.py database.py models.py
                    } 2>&1 | tee -a "${PROJECT_DIR}/${PIPELINE_LOG_FILE}"
                '''
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
import urllib.error
import urllib.request

backend_url = os.environ.get("RCA_BACKEND_URL", "http://127.0.0.1:8000/analyze")
build_number = os.environ.get("BUILD_NUMBER", "")
project_dir = os.environ.get("PROJECT_DIR", ".")
log_file = os.path.join(project_dir, os.environ.get("PIPELINE_LOG_FILE", "pipeline.log"))

with open(log_file, "r", encoding="utf-8", errors="replace") as file:
    logs = file.read()

payload = json.dumps({
    "build_number": build_number,
    "logs": logs
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
