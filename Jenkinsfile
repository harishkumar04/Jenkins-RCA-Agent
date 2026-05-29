pipeline {
    agent any

    environment {
        RCA_BACKEND_URL = 'http://127.0.0.1:8000/analyze'
        BUILD_LOG_FILE = 'build.log'
    }

    stages {
        stage('Setup Python On macOS') {
            steps {
                sh '''#!/bin/bash
                    python3 -m venv .venv
                    . .venv/bin/activate
                    python -m pip install --upgrade pip
                    pip install -r requirements.txt
                '''
            }
        }

        stage('Run Build') {
            steps {
                sh '''#!/bin/bash
                    set -o pipefail
                    {
                        echo "Running Jenkins build #${BUILD_NUMBER}"
                        .venv/bin/python -m py_compile main.py database.py models.py
                    } 2>&1 | tee "${BUILD_LOG_FILE}"
                '''
            }
        }
    }

    post {
        unsuccessful {
            sh '''#!/bin/bash
                if [ -f "${BUILD_LOG_FILE}" ]; then
                    python3 - <<'PY' || true
import json
import os
import urllib.error
import urllib.request

backend_url = os.environ.get("RCA_BACKEND_URL", "http://127.0.0.1:8000/analyze")
build_number = os.environ.get("BUILD_NUMBER", "")
log_file = os.environ.get("BUILD_LOG_FILE", "build.log")

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
                    echo "No build log file found, skipping RCA alert."
                fi
            '''
        }
    }
}
