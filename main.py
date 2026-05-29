from datetime import datetime
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

    if "build_number" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE incidents ADD COLUMN build_number VARCHAR")
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

def send_email_alert(build_number: str | None, logs: str, analysis: str):
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
    message = EmailMessage()
    message["Subject"] = f"AI RCA Alert - {subject_build}"
    message["From"] = smtp_from
    message["To"] = smtp_to
    message.set_content(
        f"""AI RCA Alert

Build Number: {build_number or "N/A"}
Generated At: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

RCA:
{analysis}

Logs:
{logs}
"""
    )

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

    prompt = f"""
You are an expert DevOps and Jenkins CI/CD troubleshooting assistant.

Analyze the logs and STRICTLY return output ONLY in this exact format.

Category:
<Jenkins/Kubernetes/Helm/Docker/Git/Maven/Gradle/npm/Python/Network/Cloud/Database/Security/Other>

Failure Type:
<short failure type>

Root Cause:
<short root cause>

Severity:
<Low/Medium/High>

Suggested Fix:
<short fix>

Troubleshooting Commands:
<commands only>

Do NOT give explanations.
Do NOT use markdown.
Do NOT use bullet points.
Do NOT use paragraphs.
Keep output concise and clean.

Logs:
{request.logs}
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

        # Save RCA into file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename = f"rca_{timestamp}.txt"

        with open(filename, "w") as file:
            file.write(analysis)

        print(f"RCA saved to file: {filename}")

        # Save incident into database
        db = SessionLocal()

        incident = Incident(
            build_number=request.build_number,
            logs=request.logs,
            analysis=analysis
        )

        db.add(incident)

        db.commit()

        db.refresh(incident)

        db.close()

        # Send RCA alert by email when SMTP is configured
        try:
            send_email_alert(
                build_number=request.build_number,
                logs=request.logs,
                analysis=analysis
            )
        except Exception as email_error:
            print("EMAIL ERROR:", str(email_error))

        # Return clean text response
        return PlainTextResponse(content=analysis)

    except Exception as e:

        print("ERROR:", str(e))

        return PlainTextResponse(
            content=f"Error occurred: {str(e)}",
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
            "id": incident.id,
            "build_number": incident.build_number,
            "logs": incident.logs,
            "analysis": incident.analysis,
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

    data = {
        "found": True,
        "id": incident.id,
        "build_number": incident.build_number,
        "logs": incident.logs,
        "analysis": incident.analysis,
    }

    db.close()

    return jsonable_encoder(data)
