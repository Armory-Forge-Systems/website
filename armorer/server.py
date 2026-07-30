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
    allow_origins=[
        'https://armoryforgesystems.com',
        'https://www.armoryforgesystems.com',
    ],
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
        'name': r'(?:Contact|Name|Full name)[:\s]+(.+?)(?:\n|$|,)',
        'company': r'(?:Business|Company)[:\s]+(.+?)(?:\n|$|,)',
        'email': r'(?:Email)[:\s]+([\w.+-]+@[\w-]+\.[\w.-]+)',
        'phone': r'(?:Phone)[:\s]+(.+?)(?:\n|$|,)',
        'type': r'(?:Type|Industry)[:\s]+(.+?)(?:\n|$|,)',
        'employees': r'(?:Employees|Employee count)[:\s]+(.+?)(?:\n|$|,)',
        'needs': r'(?:Needs|Details)[:\s]+(.+?)(?:\n|LEAD_CAPTURE|$)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, reply, re.IGNORECASE)
        if match:
            fields[key] = match.group(1).strip()

    return fields if fields else None


def build_transcript(conversation: list[dict]) -> str:
    """Build a readable transcript from conversation history."""
    lines = []
    for msg in conversation:
        role = msg.get('role', '')
        content = msg.get('content', '')
        if role == 'user':
            lines.append(f'Prospect: {content}')
        elif role == 'assistant':
            lines.append(f'Armorer: {content}')
    return '\n\n'.join(lines)


def send_lead_email(conversation: list[dict]):
    """Send full transcript to email."""
    if not SMTP_HOST or SMTP_HOST == 'localhost':
        log.info(f'[LEAD] Would send email with {len(conversation)} messages')
        return

    # Get summary from last assistant message (the confirmation)
    last_ai = ''
    for msg in reversed(conversation):
        if msg['role'] == 'assistant':
            last_ai = msg['content'].replace(LEAD_TRIGGER, '').strip()
            break

    transcript = build_transcript(conversation)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'New Armorer Intake — {now}'
        msg['From'] = SMTP_USER or 'armorer@armoryforgesystems.com'
        msg['To'] = NOTIFY_EMAIL

        text = f"""⚒️ New Armorer Intake

{last_ai}

──────────────────────────────
FULL TRANSCRIPT
──────────────────────────────

{transcript}

──────────────────────────────
Captured: {now}
"""

        html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:700px">
<h2 style="color:#ff6b00">⚒️ New Armorer Intake</h2>
<h3 style="color:#555;margin-top:0">Summary</h3>
<div style="background:#f9f9f9;padding:16px;border-radius:8px;border-left:3px solid #ff6b00;margin-bottom:24px;white-space:pre-wrap;line-height:1.6">
{last_ai.replace(chr(10), '<br>')}
</div>
<h3 style="color:#555">Full Transcript</h3>
<div style="background:#fafafa;padding:16px;border-radius:8px;font-size:13px;line-height:1.8;white-space:pre-wrap">
{transcript.replace(chr(10), '<br>')}
</div>
<p style="color:#999;font-size:11px;margin-top:24px">Captured {now} · Armory Forge Systems</p>
</body></html>"""

        msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        log.info(f'[LEAD] Email sent with full transcript')

    except Exception as e:
        log.error(f'[LEAD] Failed to send email: {e}')
        log.info(f'[LEAD] Fallback transcript:\n{transcript}')


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
    """Mock responses matching the v2 structured intake flow."""
    user_msgs = [m['content'] for m in messages if m['role'] == 'user']
    count = len(user_msgs)
    last = user_msgs[-1].lower() if user_msgs else ''

    # Step 1: Greeting
    if count == 1:
        return "Welcome to the forge. I'm The Armorer, the AI receptionist for Armory Forge Systems. I'll ask you a few quick questions to understand your business. This should take about two minutes.\n\nFirst — what's the name of your business?"

    # Step 2: Business name → ask type
    if count == 2:
        return "Got it. What type of business is it, and what industry are you in?"

    # Step 3: Business type → ask employee count
    if count == 3:
        return "And how many employees work there?"

    # Step 4: Employee count → ask important details
    if count == 4:
        return "Tell me a bit about your day-to-day. What tools or software do you use? What processes eat up the most time? Is there a particular bottleneck or frustration you're hoping to solve?"

    # Step 5: Details → ask contact name
    if count == 5:
        return "Who should we reach out to? Your full name, please."

    # Step 6: Contact name → ask email
    if count == 6:
        return "What's the best email address to send information to?"

    # Step 7: Email → ask phone + best time
    if count == 7:
        return "And a phone number? Also — what's the best time of day to reach you?"

    # Step 8: Done → confirm + close
    return "I've captured everything. Here's a quick summary:\n\n- Business: [from conversation]\n- Type: [from conversation]\n- Employees: [from conversation]\n- Needs: [from conversation]\n- Contact: [from conversation]\n- Email: [from conversation]\n- Phone: [from conversation]\n\nA member of our team will review this and follow up within one business day. In the meantime, feel free to browse our pricing page or The Signet for more information. Thanks for stopping by the forge.\n\nLEAD_CAPTURE_COMPLETE"


# ── Routes ──────────────────────────────────────────────────

@app.get('/armorer/health')
async def health():
    return {'status': 'ok'}


@app.post('/armorer/api/chat', response_model=ChatResponse)
async def chat(req: ChatRequest):
    # Get or create session
    session_id = req.session_id or f'session_{datetime.now().timestamp()}'
    is_new = session_id not in conversations

    if is_new:
        conversations[session_id] = [
            {'role': 'system', 'content': ARMORER_SYSTEM_PROMPT}
        ]
        log.info(f'[SESSION] New session: {session_id[:20]}...')
    else:
        log.info(f'[SESSION] Existing: {session_id[:20]}... ({len(conversations[session_id])} msgs)')

    # Add user message
    conversations[session_id].append({'role': 'user', 'content': req.message})

    # Trim history if too long (keep system prompt + last 30 messages)
    # 30 messages = ~15 full exchanges — enough for the full intake flow
    if len(conversations[session_id]) > 35:
        conversations[session_id] = [
            conversations[session_id][0],  # system prompt
            *conversations[session_id][-30:]  # last 30 messages
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
        # Send full transcript — every single message the user sent is in there
        send_lead_email(conversations[session_id])
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
