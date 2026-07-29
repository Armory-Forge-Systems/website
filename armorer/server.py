"""
The Armorer — FastAPI Backend Server
Handles chat, DeepSeek API integration, lead capture, and email notifications.

Usage:
    python server.py
    # or: uvicorn server:app --host 0.0.0.0 --port 8000

Environment variables:
    DEEPSEEK_API_KEY   — DeepSeek API key (required)
    SMTP_HOST          — SMTP server for lead notifications (default: localhost)
    SMTP_PORT          — SMTP port (default: 587)
    SMTP_USER          — SMTP username
    SMTP_PASS          — SMTP password
    NOTIFY_EMAIL       — Where to send lead notifications
    ARMORER_DEV_MODE   — Set to 'true' to use mock AI (no API key needed)
"""

import os
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from prompt import ARMORER_SYSTEM_PROMPT

# ── Logging ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('armorer')

# ── Config ──────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'
DEEPSEEK_MODEL = 'deepseek-chat'

SMTP_HOST = os.getenv('SMTP_HOST', 'localhost')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')
NOTIFY_EMAIL = os.getenv('NOTIFY_EMAIL', 'info@armoryforgesystems.com')

DEV_MODE = os.getenv('ARMORER_DEV_MODE', '').lower() in ('true', '1', 'yes')

# ── Conversation store (in-memory — use Redis/DB in production) ──
conversations: dict[str, list[dict]] = {}

# ── App ─────────────────────────────────────────────────────
app = FastAPI(
    title='The Armorer API',
    description='AI receptionist for Armory Forge Systems',
    version='1.0.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# ── Models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    lead_captured: bool = False
    session_id: str

# ── Lead detection ──────────────────────────────────────────

LEAD_TRIGGER = 'LEAD_CAPTURE_COMPLETE'

def extract_lead_info(reply: str) -> Optional[dict]:
    """Extract lead fields from the AI response if LEAD_CAPTURE_COMPLETE is present."""
    if LEAD_TRIGGER not in reply:
        return None

    fields = {}
    patterns = {
        'name': r'(?:Name|Full name)[:\s]+(.+?)(?:\n|$)',
        'company': r'(?:Company|Company name|Business)[:\s]+(.+?)(?:\n|$)',
        'email': r'(?:Email|Email address)[:\s]+([\w.+-]+@[\w-]+\.[\w.-]+)',
        'phone': r'(?:Phone|Phone number)[:\s]+(.+?)(?:\n|$)',
        'summary': r'(?:Summary|Needs|Requirements)[:\s]+(.+?)(?:\n|LEAD_CAPTURE|$)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, reply, re.IGNORECASE)
        if match:
            fields[key] = match.group(1).strip()

    return fields if fields else None


def send_lead_email(lead: dict):
    """Send lead notification email."""
    if not SMTP_HOST or SMTP_HOST == 'localhost':
        log.info(f'[LEAD] Would send email: {json.dumps(lead, indent=2)}')
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'New Lead: {lead.get("name", "Unknown")} — {lead.get("company", "No Company")}'
        msg['From'] = SMTP_USER or 'armorer@armoryforgesystems.com'
        msg['To'] = NOTIFY_EMAIL

        text = f"""New Armorer Lead

Name: {lead.get('name', '—')}
Company: {lead.get('company', '—')}
Email: {lead.get('email', '—')}
Phone: {lead.get('phone', '—')}

Summary:
{lead.get('summary', '—')}

Captured: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
"""

        html = f"""<html><body style="font-family:Arial,sans-serif;color:#333">
<h2 style="color:#ff6b00">⚒️ New Armorer Lead</h2>
<table style="border-collapse:collapse">
<tr><td style="padding:6px 12px 6px 0;font-weight:bold;color:#666">Name</td><td>{lead.get('name', '—')}</td></tr>
<tr><td style="padding:6px 12px 6px 0;font-weight:bold;color:#666">Company</td><td>{lead.get('company', '—')}</td></tr>
<tr><td style="padding:6px 12px 6px 0;font-weight:bold;color:#666">Email</td><td>{lead.get('email', '—')}</td></tr>
<tr><td style="padding:6px 12px 6px 0;font-weight:bold;color:#666">Phone</td><td>{lead.get('phone', '—')}</td></tr>
<tr><td style="padding:6px 12px 6px 0;font-weight:bold;color:#666">Summary</td><td>{lead.get('summary', '—')}</td></tr>
</table>
<p style="color:#999;font-size:12px">Captured {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""

        msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        log.info(f'[LEAD] Email sent for {lead.get("name")} at {lead.get("company")}')

    except Exception as e:
        log.error(f'[LEAD] Failed to send email: {e}')
        # Log the lead so it's not lost
        log.info(f'[LEAD] Fallback log: {json.dumps(lead, indent=2)}')


# ── AI call ─────────────────────────────────────────────────

async def call_deepseek(messages: list[dict]) -> str:
    """Call DeepSeek API with conversation history."""
    if DEV_MODE or not DEEPSEEK_API_KEY:
        log.warning('[AI] DEV MODE — using mock response')
        return mock_ai_response(messages)

    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': messages,
        'temperature': 0.7,
        'max_tokens': 800,
        'stream': False,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f'{DEEPSEEK_BASE_URL}/chat/completions',
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content']


def mock_ai_response(messages: list[dict]) -> str:
    """Mock responses for dev/testing without API key."""
    user_msgs = [m['content'] for m in messages if m['role'] == 'user']
    count = len(user_msgs)

    if count == 1:
        return "Thanks for reaching out. To help match you with the right solution, could you tell me what industry you're in and roughly how many employees you have?"
    elif count == 2:
        return "Got it. And what specific tasks are you looking to automate or improve? For example — handling customer calls, scheduling appointments, managing data entry, something else?"
    elif count == 3:
        return "Based on what you've described, I'd recommend starting with a **Forge Assessment** — it's completely free and takes about 30-60 minutes. You'll leave with a clear automation roadmap. Would you like me to capture your details so our team can reach out?\n\nIf you'd prefer to skip straight to a proposal, I can outline which tier fits your needs."
    else:
        return "I've captured your requirements. To move forward, I'll just need a few details:\n\nName: \nCompany: \nEmail: \nPhone (optional): \n\nOnce you share those, I'll log everything and our team will follow up within one business day.\n\nLEAD_CAPTURE_COMPLETE"


# ── Routes ──────────────────────────────────────────────────

@app.get('/armorer/health')
async def health():
    return {
        'status': 'ok',
        'service': 'The Armorer',
        'dev_mode': DEV_MODE,
        'model': DEEPSEEK_MODEL,
    }


@app.post('/armorer/api/chat', response_model=ChatResponse)
async def chat(req: ChatRequest):
    # Get or create session
    session_id = req.session_id or f'session_{datetime.now().timestamp()}'

    if session_id not in conversations:
        conversations[session_id] = [
            {'role': 'system', 'content': ARMORER_SYSTEM_PROMPT}
        ]

    # Add user message
    conversations[session_id].append({'role': 'user', 'content': req.message})

    # Trim history if too long (keep system prompt + last 12 messages)
    if len(conversations[session_id]) > 15:
        conversations[session_id] = [
            conversations[session_id][0],  # system prompt
            *conversations[session_id][-12:]  # last 12 messages
        ]

    # Get AI response
    try:
        reply = await call_deepseek(conversations[session_id])
    except Exception as e:
        log.error(f'[AI] DeepSeek error: {e}')
        raise HTTPException(status_code=502, detail='AI service temporarily unavailable. Please try again.')

    # Add assistant reply to history
    conversations[session_id].append({'role': 'assistant', 'content': reply})

    # Check for lead capture
    lead_captured = LEAD_TRIGGER in reply
    if lead_captured:
        lead = extract_lead_info(reply)
        if lead:
            send_lead_email(lead)
            # Clean reply — remove the trigger line
            reply = reply.replace(LEAD_TRIGGER, '').strip()

    # Clean up old sessions (keep last 500)
    if len(conversations) > 500:
        oldest = sorted(conversations.keys())[:100]
        for k in oldest:
            del conversations[k]

    return ChatResponse(
        reply=reply,
        lead_captured=lead_captured,
        session_id=session_id,
    )


# ── Main ────────────────────────────────────────────────────
if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', '8000'))
    log.info(f'⚒️  The Armorer starting on port {port}...')
    log.info(f'   Dev mode: {DEV_MODE}')
    log.info(f'   Model: {DEEPSEEK_MODEL}')
    uvicorn.run(app, host='0.0.0.0', port=port)
