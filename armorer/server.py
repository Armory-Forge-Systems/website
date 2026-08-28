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
from collections import defaultdict
from datetime import datetime, timezone
from time import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
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

# ── Rate Limiter ────────────────────────────────────────────
rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_PER_MINUTE = 20
RATE_LIMIT_PER_HOUR = 100

def check_rate_limit(ip: str) -> bool:
    now = time()
    minute_ago = now - 60
    hour_ago = now - 3600
    # Prune old entries
    rate_limit_store[ip] = [t for t in rate_limit_store[ip] if t > hour_ago]
    per_minute = sum(1 for t in rate_limit_store[ip] if t > minute_ago)
    per_hour = len(rate_limit_store[ip])
    if per_minute >= RATE_LIMIT_PER_MINUTE or per_hour >= RATE_LIMIT_PER_HOUR:
        return False
    rate_limit_store[ip].append(now)
    return True

# ── Secrets Manager ─────────────────────────────────────────
def load_secrets() -> dict:
    """Load config from AWS Secrets Manager. Falls back to env vars for local dev."""
    secret_name = os.getenv('AWS_SECRET_NAME', 'armorer/production')
    region = os.getenv('AWS_REGION', 'us-east-1')

    # Try AWS Secrets Manager first
    try:
        import boto3
        client = boto3.client('secretsmanager', region_name=region)
        resp = client.get_secret_value(SecretId=secret_name)
        secrets = json.loads(resp['SecretString'])
        log.info(f'[SECRETS] Loaded from AWS Secrets Manager: {secret_name}')
        return secrets
    except Exception as e:
        log.warning(f'[SECRETS] AWS Secrets Manager unavailable ({e}), falling back to env vars')

    # Fallback to environment variables (local dev)
    return {
        'DEEPSEEK_API_KEY': os.getenv('DEEPSEEK_API_KEY', ''),
        'SMTP_HOST': os.getenv('SMTP_HOST', 'localhost'),
        'SMTP_PORT': os.getenv('SMTP_PORT', '587'),
        'SMTP_USER': os.getenv('SMTP_USER', ''),
        'SMTP_PASS': os.getenv('SMTP_PASS', ''),
        'NOTIFY_EMAIL': os.getenv('NOTIFY_EMAIL', 'info@armoryforgesystems.com'),
    }

# ── Config ──────────────────────────────────────────────────
_secrets = load_secrets()

DEEPSEEK_API_KEY = _secrets.get('DEEPSEEK_API_KEY', '')
DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'
DEEPSEEK_MODEL = 'deepseek-chat'
DEEPSEEK_REASONER_MODEL = 'deepseek-reasoner'

SMTP_HOST = _secrets.get('SMTP_HOST', 'localhost')
SMTP_PORT = int(_secrets.get('SMTP_PORT', '587'))
SMTP_USER = _secrets.get('SMTP_USER', '')
SMTP_PASS = _secrets.get('SMTP_PASS', '')
NOTIFY_EMAIL = _secrets.get('NOTIFY_EMAIL', 'info@armoryforgesystems.com')

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
    support_intent: bool = False
    session_id: str


class SupportRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    your_name: str = Field(..., min_length=1, max_length=200)
    contact_number: str = Field('', max_length=50)
    email: str = Field(..., min_length=3, max_length=200)
    session_id: Optional[str] = None

# ── Lead detection ──────────────────────────────────────────

LEAD_TRIGGER = 'LEAD_CAPTURE_COMPLETE'

# ── Support intent (persona switch) ──────────────────────
SUPPORT_TRIGGERS = [
    'support', 'issue', 'problem', 'billing', 'invoice', 'refund',
    'my account', 'my subscription', 'existing customer', 'customer support',
    'not working', 'error', 'bug', 'broken', 'password', 'login',
    'talk to a human', 'talk to someone', 'complaint', 'outage', 'down',
]

def detect_support_intent(message: str) -> bool:
    """True when a visitor sounds like an existing customer needing support
    (routes to the support intake form) rather than a new prospect (routes to The Armorer)."""
    lower = message.lower()
    return any(trigger in lower for trigger in SUPPORT_TRIGGERS)

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


# ── Support email ──────────────────────────────────────────

def send_support_email(company_name, your_name, contact_number, email, issue):
    """Email the team when a customer submits a support intake form."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    NL = chr(10)

    lines = ['New support request from the website.', '',
             'Company Name: ' + company_name,
             'Your Name: ' + your_name,
             'Best contact number: ' + (contact_number or '—'),
             'Email: ' + email]
    if issue:
        lines += ['', 'What they said:', issue]
    lines += ['', 'Captured: ' + now]
    body = NL.join(lines)

    if not SMTP_HOST or SMTP_HOST == 'localhost':
        log.info('[SUPPORT] Would send email:' + NL + body[:300])
        return

    try:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = 'New Support Request — ' + company_name
        msg['From'] = SMTP_USER or 'armorer@armoryforgesystems.com'
        msg['To'] = NOTIFY_EMAIL
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        log.info('[SUPPORT] Support email sent')
    except Exception as e:
        log.error('[SUPPORT] Failed to send email: ' + str(e))


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


async def call_deepseek_reasoner(messages: list[dict]) -> str:
    """Call DeepSeek Reasoner for complex/off-script queries."""
    if DEV_MODE or not DEEPSEEK_API_KEY:
        return mock_ai_response(messages)

    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': DEEPSEEK_REASONER_MODEL,
        'messages': messages,
        'stream': False,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f'{DEEPSEEK_BASE_URL}/chat/completions',
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content']


def detect_complexity(message: str) -> bool:
    """Detect if a message needs higher-tier reasoning."""
    triggers = [
        'why', 'how does', 'explain', 'compare', 'difference',
        'what if', 'should i', 'recommend', 'which one',
        'is it worth', 'cost vs', 'pros and cons',
        'not sure', 'confused', 'don\'t understand',
        'custom', 'specific', 'unique', 'complicated',
    ]
    lower = message.lower()
    return any(t in lower for t in triggers)


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
async def chat(req: ChatRequest, request: Request):
    # ── Rate limiting ──
    client_ip = request.client.host if request.client else 'unknown'
    if not check_rate_limit(client_ip):
        log.warning(f'[RATE] Blocked {client_ip}')
        raise HTTPException(status_code=429, detail='Too many requests. Please slow down.')

    # ── Session ──
    session_id = req.session_id or f'session_{datetime.now().timestamp()}'
    is_new = session_id not in conversations

    if is_new:
        conversations[session_id] = [
            {'role': 'system', 'content': ARMORER_SYSTEM_PROMPT}
        ]
        log.info(f'[SESSION] New session: {session_id[:20]}... from {client_ip}')
    else:
        log.info(f'[SESSION] Existing: {session_id[:20]}... ({len(conversations[session_id])} msgs)')

    # Add user message
    conversations[session_id].append({'role': 'user', 'content': req.message})

    # Support intent — route existing customers to the intake form (no AI needed)
    if detect_support_intent(req.message):
        reply = ("I'll get our support team on it. Leave your details below and "
                 "someone will reach out to you soon.")
        conversations[session_id].append({'role': 'assistant', 'content': reply})
        log.info(f'[SUPPORT] Routed {session_id[:20]}... to intake form')
        return ChatResponse(reply=reply, support_intent=True, session_id=session_id)

    # Trim history
    if len(conversations[session_id]) > 35:
        conversations[session_id] = [
            conversations[session_id][0],
            *conversations[session_id][-30:]
        ]

    # ── Choose model based on complexity ──
    use_reasoner = detect_complexity(req.message)
    model_name = DEEPSEEK_REASONER_MODEL if use_reasoner else DEEPSEEK_MODEL
    log.info(f'[AI] Using {model_name} (complexity={"high" if use_reasoner else "standard"})')

    # Get AI response
    try:
        if use_reasoner:
            reply = await call_deepseek_reasoner(conversations[session_id])
        else:
            reply = await call_deepseek(conversations[session_id])
    except Exception as e:
        log.error(f'[AI] Error: {e}')
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


@app.post('/armorer/api/support')
async def submit_support(req: SupportRequest, request: Request):
    client_ip = request.client.host if request.client else 'unknown'
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail='Too many requests. Please slow down.')

    email = req.email.strip()
    if '@' not in email or '.' not in email:
        raise HTTPException(status_code=400, detail='Please enter a valid email address.')

    issue = ''
    if req.session_id and req.session_id in conversations:
        user_msgs = [m['content'] for m in conversations[req.session_id] if m['role'] == 'user']
        issue = user_msgs[-1] if user_msgs else ''

    send_support_email(
        company_name=req.company_name.strip(),
        your_name=req.your_name.strip(),
        contact_number=req.contact_number.strip(),
        email=email,
        issue=issue,
    )
    return {'status': 'received', 'message': 'Someone from our team will reach out to you soon.'}


# ═══════════════════════════════════════════════════════════════
# PHONE CALL ENDPOINT — Twilio Webhook
# ═══════════════════════════════════════════════════════════════

VOICE_SYSTEM_PROMPT = """You are The Armorer — AI receptionist for Armory Forge Systems. You are speaking on a phone call. Keep every response under 20 seconds when spoken aloud. Be warm but efficient. No markdown, no lists, no emojis. Just natural speech. Follow the same intake flow: greet, ask business name, ask type, ask employees, ask needs, ask contact, close."""

# Phone call session store: caller_number -> conversation history
phone_sessions: dict[str, list[dict]] = {}

async def get_voice_reply(transcript: str, caller: str) -> str:
    """Get AI reply for a phone call transcript."""
    if caller not in phone_sessions:
        phone_sessions[caller] = [
            {'role': 'system', 'content': VOICE_SYSTEM_PROMPT}
        ]

    phone_sessions[caller].append({'role': 'user', 'content': transcript})

    # Trim if too long
    if len(phone_sessions[caller]) > 25:
        phone_sessions[caller] = [
            phone_sessions[caller][0],
            *phone_sessions[caller][-20:]
        ]

    if DEV_MODE or not DEEPSEEK_API_KEY:
        msgs = [m['content'] for m in phone_sessions[caller] if m['role'] == 'user']
        count = len(msgs)
        if count == 1:
            return "Welcome to Armory Forge Systems. I'm The Armorer. What's the name of your business?"
        replies = [
            "Got it. What type of business?",
            "And how many employees?",
            "What tools or software do you use day to day?",
            "What's your name and the best email to reach you?",
            "Got everything. Our team will follow up within one business day. Thanks for calling.",
        ]
        idx = min(count - 2, len(replies) - 1)
        if idx >= 0:
            return replies[idx]
        return "Thanks. We'll be in touch."

    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': DEEPSEEK_MODEL,
        'messages': phone_sessions[caller],
        'temperature': 0.7,
        'max_tokens': 200,  # short for voice
        'stream': False,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f'{DEEPSEEK_BASE_URL}/chat/completions',
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data['choices'][0]['message']['content']
        phone_sessions[caller].append({'role': 'assistant', 'content': reply})
        return reply


from fastapi.responses import Response

@app.api_route('/armorer/call', methods=['GET', 'POST'])
async def phone_call(request: Request):
    """Handle Twilio voice calls. GET for health, POST for webhook."""
    if request.method == 'GET':
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Armory Forge Systems phone endpoint is active.</Say></Response>',
            media_type='application/xml'
        )

    # Parse Twilio POST body
    body = await request.form()
    caller = body.get('From', 'unknown')
    speech_result = body.get('SpeechResult', '').strip()

    log.info(f'[CALL] From {caller}: SpeechResult="{speech_result[:80]}"')

    if not speech_result:
        # Initial call — greeting
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response>'
            '<Gather input="speech" action="/armorer/call" method="POST" '
            'speechTimeout="auto" language="en-US" enhanced="true">'
            '<Say voice="Polly.Joanna-Neural">Welcome to Armory Forge Systems. '
            'I am The Armorer, an AI receptionist. '
            'What is the name of your business?</Say>'
            '</Gather>'
            '<Say>I didn\'t catch that. Please call back or visit us at armoryforgeystems.com.</Say>'
            '</Response>'
        )
        return Response(twiml, media_type='application/xml')

    # Process speech through AI
    try:
        reply = await get_voice_reply(speech_result, caller)
    except Exception as e:
        log.error(f'[CALL] AI error: {e}')
        reply = "I'm sorry, I'm having trouble processing that. Could you repeat your answer?"

    # Clean reply for voice (strip markdown, keep it natural)
    reply = reply.replace('**', '').replace('*', '').replace('\n', ' ').strip()

    # Check if done
    if 'LEAD_CAPTURE_COMPLETE' in reply:
        reply = reply.replace('LEAD_CAPTURE_COMPLETE', '').strip()
        twiml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Response>'
            f'<Say voice="Polly.Joanna-Neural">{reply}</Say>'
            f'<Hangup/>'
            f'</Response>'
        )
        # Clean up session
        if caller in phone_sessions:
            del phone_sessions[caller]
    else:
        twiml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Response>'
            f'<Gather input="speech" action="/armorer/call" method="POST" '
            f'speechTimeout="auto" language="en-US" enhanced="true">'
            f'<Say voice="Polly.Joanna-Neural">{reply}</Say>'
            f'</Gather>'
            f'<Say>I didn\'t catch that. Please try again.</Say>'
            f'</Response>'
        )

    return Response(twiml, media_type='application/xml')


# ── Main ────────────────────────────────────────────────────
if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', '8000'))
    log.info(f'⚒️  The Armorer starting on port {port}...')
    log.info(f'   Dev mode: {DEV_MODE}')
    log.info(f'   Model: {DEEPSEEK_MODEL}')
    uvicorn.run(app, host='0.0.0.0', port=port)
