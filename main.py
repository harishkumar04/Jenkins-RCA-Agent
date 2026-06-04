from datetime import datetime
import hashlib
import re
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import smtplib
from email.message import EmailMessage
from sqlalchemy import inspect, text

from database import SessionLocal, engine
from models import Incident
from database import Base

# Load environment variables
load_dotenv()

# Create database tables
Base.metadata.create_all(bind=engine)

def ensure_database_columns():
    inspector = inspect(engine)

    if "incidents" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("incidents")
    }

    column_definitions = {
        "created_at": "DATETIME",
        "build_number": "VARCHAR",
        "build_url": "VARCHAR",
        "category": "VARCHAR",
        "severity": "VARCHAR",
        "failure_type": "VARCHAR",
        "root_cause": "VARCHAR",
        "fingerprint": "VARCHAR",
        "recurrence_count": "INTEGER DEFAULT 1",
        "recurring": "VARCHAR DEFAULT 'No'",
        "recurrence_memory": "VARCHAR",
        "resolution_playbook": "VARCHAR",
        "code_context": "VARCHAR",
    }

    with engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name not in columns:
                connection.execute(
                    text(f"ALTER TABLE incidents ADD COLUMN {column_name} {column_type}")
                )

ensure_database_columns()

# Initialize FastAPI app
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI client
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

# Request model
class LogInput(BaseModel):
    logs: str
    build_number: str | None = None
    build_url: str | None = None

def parse_field(text_value: str, field_name: str) -> str:
    pattern = rf"{re.escape(field_name)}:\s*([\s\S]*?)(?=\n[A-Za-z ]+:|$)"
    match = re.search(pattern, text_value or "", re.IGNORECASE)
    return match.group(1).strip() if match else ""

def normalize_value(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")

def build_fingerprint(category: str, failure_type: str) -> str:
    def clean_term(term: str) -> str:
        cleaned = normalize_value(term)
        fillers = {"daemon", "error", "failed", "failure", "issue", "problem", "server", "status", "state"}
        words = [w for w in cleaned.split("-") if w not in fillers and w]
        return "-".join(sorted(words))

    source = "|".join([
        clean_term(category),
        clean_term(failure_type),
    ])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

def extract_base_job_url(build_url: str | None) -> str | None:
    """Extract the base job URL from a build URL like http://jenkins/job/my-job/123/."""
    if not build_url:
        return None

    prefix, separator, remainder = build_url.rpartition("/job/")
    if not separator:
        return None

    job_name, slash, remainder = remainder.partition("/")
    if not slash or not job_name:
        return None

    build_number, _, _ = remainder.partition("/")
    if not build_number.isdigit():
        return None

    return f"{prefix}/job/{job_name}/"

def build_recurrence_memory(previous_incidents: list[Incident], current_build_url: str | None = None) -> str:
    if not previous_incidents:
        return "No previous matching incidents found."

    latest = previous_incidents[0]
    
    # Try to find a base build URL to reconstruct missing ones
    base_url = extract_base_job_url(current_build_url)
            
    if not base_url:
        for p in previous_incidents:
            if p.build_url:
                base_url = extract_base_job_url(p.build_url)
                if base_url:
                    break
    
    build_lines = []
    for incident in previous_incidents[:5]:
        build_url = incident.build_url
        if not build_url and incident.build_number and base_url:
            build_url = f"{base_url}{incident.build_number}/"
        
        build_str = f"Build {incident.build_number or 'N/A'}"
        if build_url:
            build_str += f" ({build_url})"
        build_lines.append(f"  - {build_str}")

    previous_fix = parse_field(latest.analysis, "Suggested Fix") or "No previous fix captured."

    last_seen_url = latest.build_url
    if not last_seen_url and latest.build_number and base_url:
        last_seen_url = f"{base_url}{latest.build_number}/"

    last_seen_str = f"Build {latest.build_number or 'N/A'}"
    if last_seen_url:
        last_seen_str += f" ({last_seen_url})"

    memory_text = (
        "Matched previous incidents:\n"
        + "\n".join(build_lines) + "\n"
        + f"Last seen in: {last_seen_str}\n"
        + f"Previous fix/action: {previous_fix}"
    )
    return memory_text

def get_read_only_code_context() -> str:
    if os.getenv("ENABLE_CODE_CONTEXT", "false").lower() != "true":
        return "Code context disabled."

    root_value = os.getenv("APP_READONLY_DIR")

    if not root_value:
        return "Code context not configured."

    root = Path(root_value).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        return f"Code context directory not found: {root}"

    allowed_extensions = {".js", ".ts", ".json", ".yml", ".yaml", ".dockerfile"}
    allowed_names = {"Dockerfile", "Jenkinsfile", "package.json", "package-lock.json", "docker-compose.yml"}
    ignored_dirs = {"node_modules", ".git", "dist", "build", "coverage", ".next"}
    snippets = []

    for path in sorted(root.rglob("*")):
        if len(snippets) >= 8:
            break

        if any(part in ignored_dirs for part in path.parts):
            continue

        if not path.is_file():
            continue

        if path.name not in allowed_names and path.suffix.lower() not in allowed_extensions:
            continue

        try:
            relative = path.relative_to(root)
            text_value = path.read_text(encoding="utf-8", errors="replace")[:1200]
            snippets.append(f"File: {relative}\n{text_value}")
        except OSError:
            continue

    if not snippets:
        return "No readable source files found in allowlisted directory."

    return "\n\n---\n\n".join(snippets)

def enrich_analysis(
    analysis: str,
    recurrence_count: int,
    fingerprint: str,
    recurrence_memory: str,
    build_url: str | None,
    code_context: str,
) -> str:
    recurring = "Yes" if recurrence_count > 1 else "No"
    build_url_text = build_url or "Not provided"

    return f"""{analysis}

Build URL:
{build_url_text}

Recurring Incident:
{recurring}

Similar Incident Count:
{recurrence_count}

Incident Fingerprint:
{fingerprint}

Recurrence Memory:
{recurrence_memory}

Read-Only Code Context:
{code_context}"""

def incident_to_dict(incident: Incident) -> dict:
    return {
        "id": incident.id,
        "created_at": incident.created_at,
        "build_number": incident.build_number,
        "build_url": incident.build_url,
        "category": incident.category,
        "severity": incident.severity,
        "failure_type": incident.failure_type,
        "root_cause": incident.root_cause,
        "fingerprint": incident.fingerprint,
        "recurrence_count": incident.recurrence_count,
        "recurring": incident.recurring,
        "recurrence_memory": incident.recurrence_memory,
        "resolution_playbook": incident.resolution_playbook,
        "code_context": incident.code_context,
        "logs": incident.logs,
        "analysis": incident.analysis,
    }

def generate_rca_report_text(build_number: str | None, logs: str, incident: Incident) -> str:
    return f"""AI RCA Alert

Build Number: {build_number or "N/A"}
Generated At: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

RCA Details:
{incident.analysis}

Logs:
{logs}
"""

def send_email_alert(build_number: str | None, logs: str, incident: Incident):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    smtp_to = os.getenv("SMTP_TO")
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not all([smtp_host, smtp_from, smtp_to]):
        print("SMTP alert skipped: SMTP_HOST, SMTP_FROM/SMTP_USER, or SMTP_TO missing")
        return

    subject_build = f"Build #{build_number}" if build_number else "Jenkins Build"
    subject_recurrence = "Recurring" if incident.recurring == "Yes" else "New"
    message = EmailMessage()
    message["Subject"] = f"[{incident.severity or 'Unknown'}] {subject_recurrence} RCA - {subject_build} - {incident.category or 'Unknown'}"
    message["From"] = smtp_from
    message["To"] = smtp_to
    
    report_text = generate_rca_report_text(build_number, logs, incident)
    message.set_content(report_text)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        if smtp_use_tls:
            server.starttls()

        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)

        server.send_message(message)

    print(f"SMTP alert sent to: {smtp_to}")

# Analyze logs endpoint
@app.post("/analyze")
def analyze_logs(request: LogInput):
    code_context = get_read_only_code_context()

    prompt = f"""
You are an expert DevOps and Jenkins CI/CD troubleshooting assistant.

Analyze the logs and STRICTLY return output ONLY in this exact format.

Category:
<Jenkins/Kubernetes/Helm/Docker/Git/Maven/Gradle/npm/Python/Network/Cloud/Database/Security/Other>

Failure Type:
<short standardized failure type (1-3 words max), e.g., 'Docker Paused', 'Clone Failed', 'OOMKilled', 'Syntax Error', 'Missing Dependency', 'Auth Failed', 'Port In Use'>

Root Cause:
<short root cause>

Severity:
<Low/Medium/High>

Suggested Fix:
<short fix>

Resolution Playbook:
<step-by-step numbered steps to completely resolve the issue, formatted as 'Step 1: ... Step 2: ...'>

Troubleshooting Commands:
<commands only>

Prevention:
<one preventive control or Jenkins preflight check>

Do NOT give explanations.
Do NOT use markdown.
Do NOT use bullet points.
Do NOT use paragraphs.
Keep output concise and clean.

Logs:
{request.logs}

Read-only application code context:
{code_context}
"""

    try:

        # Send request to OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        # Extract AI response
        analysis = response.choices[0].message.content.strip()


        # Print RCA in terminal
        print("\n===========================================")
        print("         AI RCA GENERATED")
        print("===========================================\n")

        print(analysis)

        print("\n===========================================\n")

        category = parse_field(analysis, "Category") or "Other"
        severity = parse_field(analysis, "Severity") or "Medium"
        failure_type = parse_field(analysis, "Failure Type") or "Unknown"
        root_cause = parse_field(analysis, "Root Cause") or "Unknown"
        resolution_playbook = parse_field(analysis, "Resolution Playbook") or "No resolution playbook generated."
        fingerprint = build_fingerprint(category, failure_type)
        db = SessionLocal()
        previous_incidents = (
            db.query(Incident)
            .filter(Incident.fingerprint == fingerprint)
            .order_by(Incident.id.desc())
            .limit(5)
            .all()
        )

        recurrence_count = (
            db.query(Incident)
            .filter(Incident.fingerprint == fingerprint)
            .count()
        ) + 1
        recurrence_memory = build_recurrence_memory(previous_incidents, current_build_url=request.build_url)

        analysis = enrich_analysis(
            analysis=analysis,
            recurrence_count=recurrence_count,
            fingerprint=fingerprint,
            recurrence_memory=recurrence_memory,
            build_url=request.build_url,
            code_context=code_context,
        )

        # Create incident database object
        incident = Incident(
            build_number=request.build_number,
            build_url=request.build_url,
            category=category,
            severity=severity,
            failure_type=failure_type,
            root_cause=root_cause,
            fingerprint=fingerprint,
            recurrence_count=recurrence_count,
            recurring="Yes" if recurrence_count > 1 else "No",
            recurrence_memory=recurrence_memory,
            resolution_playbook=resolution_playbook,
            code_context=code_context,
            logs=request.logs,
            analysis=analysis,
        )

        # Save RCA into file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rca_{timestamp}.txt"
        report_text = generate_rca_report_text(request.build_number, request.logs, incident)

        with open(filename, "w") as file:
            file.write(report_text)

        print(f"RCA saved to file: {filename}")

        # Save incident into database
        db.add(incident)
        db.commit()
        db.refresh(incident)
        db.close()

        # Send RCA alert by email when SMTP is configured
        try:
            send_email_alert(
                build_number=request.build_number,
                logs=request.logs,
                incident=incident
            )
        except Exception as email_error:
            print("EMAIL ERROR:", str(email_error))

        # Return clean text response
        return PlainTextResponse(content=analysis)

    except Exception as e:

        print("ERROR:", str(e))

        return PlainTextResponse(
            content="Error occurred.",
            status_code=500
        )

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/incidents")
def get_incidents():
    db = SessionLocal()

    incidents = (
        db.query(Incident)
        .order_by(Incident.id.desc())
        .limit(50)
        .all()
    )

    data = [
        {
            **incident_to_dict(incident),
        }
        for incident in incidents
    ]

    db.close()

    return jsonable_encoder(data)

@app.get("/incidents/build/{build_number}")
def get_incident_by_build_number(build_number: str):
    db = SessionLocal()

    incidents = (
        db.query(Incident)
        .filter(Incident.build_number == build_number)
        .order_by(Incident.id.desc())
        .all()
    )

    if not incidents:
        db.close()
        return {"found": False}

    jenkins_marker = f"Running Jenkins build #{build_number}"

    incident = next(
        (
            item
            for item in incidents
            if item.logs and (
                jenkins_marker in item.logs
                or "Stage: Setup Python On macOS" in item.logs
                or "Stage: Run Build" in item.logs
            )
        ),
        incidents[0]
    )

    data = {"found": True, **incident_to_dict(incident)}

    db.close()

    return jsonable_encoder(data)

@app.get("/insights")
def get_insights():
    db = SessionLocal()
    incidents = db.query(Incident).order_by(Incident.id.desc()).limit(200).all()

    by_category = {}
    recurring = []

    for incident in incidents:
        category = incident.category or parse_field(incident.analysis, "Category") or "Other"
        by_category[category] = by_category.get(category, 0) + 1

        if (incident.recurrence_count or 1) > 1:
            recurring.append(incident_to_dict(incident))

    data = {
        "total": len(incidents),
        "by_category": by_category,
        "recurring": recurring[:10],
    }

    db.close()
    return jsonable_encoder(data)

@app.get("/code/context")
def get_code_context():
    return {
        "mode": "read-only",
        "enabled": os.getenv("ENABLE_CODE_CONTEXT", "false").lower() == "true",
        "root": os.getenv("APP_READONLY_DIR"),
        "context": get_read_only_code_context(),
    }
