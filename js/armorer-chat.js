/**
 * Armory Forge Systems — The Armorer Chat Client
 * Handles message sending, display, typing indicator, and API communication.
 */

(function () {
  'use strict';

  // ── Configuration ────────────────────────────────────────
  const API_URL = 'https://api.armoryforgesystems.com/armorer/api/chat';
  const HEALTH_URL = 'https://api.armoryforgesystems.com/armorer/health';
  const DEV_MODE = false;  // set true for local testing without server
  let currentSessionId = null;  // tracks conversation session

  // ── DOM refs ─────────────────────────────────────────────
  const messagesEl = document.getElementById('chat-messages');
  const inputEl = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');
  const typingEl = document.getElementById('typing-indicator');
  const statusEl = document.getElementById('armorer-status');

  let isWaiting = false;

  async function updateServiceStatus() {
    if (!statusEl) return;
    const statusText = statusEl.querySelector('strong');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(HEALTH_URL, {
        method: 'GET',
        cache: 'no-store',
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
      statusEl.dataset.state = 'online';
      statusText.textContent = 'online';
    } catch (error) {
      statusEl.dataset.state = 'offline';
      statusText.textContent = 'offline';
      console.warn('Armorer health check failed:', error);
    } finally {
      clearTimeout(timeout);
    }
  }

  // ── Helpers ──────────────────────────────────────────────

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addMessage(text, sender) {
    const div = document.createElement('div');
    div.className = `message message--${sender}`;
    div.innerHTML = `
      <div class="message-avatar">${sender === 'armorer' ? '⚒️' : '👤'}</div>
      <div class="message-bubble"><p>${escapeHtml(text)}</p></div>
    `;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function addArmorerHtml(html) {
    const div = document.createElement('div');
    div.className = 'message message--armorer';
    div.innerHTML = `
      <div class="message-avatar">⚒️</div>
      <div class="message-bubble">${html}</div>
    `;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML.replace(/\n/g, '<br>');
  }

  function showTyping() {
    typingEl.style.display = 'flex';
    scrollToBottom();
  }

  function hideTyping() {
    typingEl.style.display = 'none';
  }

  function setSending(state) {
    isWaiting = state;
    sendBtn.disabled = state;
    inputEl.disabled = state;
    if (state) {
      showTyping();
    } else {
      hideTyping();
    }
  }

  // ── Auto-resize textarea ─────────────────────────────────
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  });

  // ── Send message ─────────────────────────────────────────
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isWaiting) return;

    // Display user message
    addMessage(text, 'user');
    inputEl.value = '';
    inputEl.style.height = 'auto';
    setSending(true);

    try {
      const response = await callArmorer(text);
      hideTyping();
      addArmorerHtml(formatResponse(response));
    } catch (err) {
      hideTyping();
      addMessage('The forge is cooling down. Please try again in a moment. If this persists, email us at info@armoryforgesystems.com.', 'armorer');
      console.error('Armorer error:', err);
    } finally {
      setSending(false);
    }
  }

  // ── API call ─────────────────────────────────────────────
  async function callArmorer(message) {
    if (DEV_MODE || !API_URL) {
      // Mock for local testing
      await new Promise(r => setTimeout(r, 1000 + Math.random() * 1500));
      return mockResponse(message);
    }

    const res = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        session_id: currentSessionId
      })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }

    const data = await res.json();
    // Store the session ID for continuity
    if (data.session_id) {
      currentSessionId = data.session_id;
    }
    return data;
  }

  // ── Format response ──────────────────────────────────────
  function formatResponse(data) {
    let text = data.reply || data.response || '';

    // Convert markdown-style formatting
    text = text
      // Bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // Line breaks to paragraphs
      .split('\n\n')
      .map(p => p.trim() ? `<p>${p.replace(/\n/g, '<br>')}</p>` : '')
      .join('');

    // If lead captured, add a subtle note
    if (data.lead_captured) {
      text += '<p style="font-size:.8rem;color:#888;margin-top:8px;">✓ Your information has been logged. Our team will follow up.</p>';
    }

    return text;
  }

  // ── Mock responses (for dev without backend) ─────────────
  // State machine: discovery → recommendation → name → company → email → phone → done
  let mockState = 'greet';

  function mockResponse(msg) {
    const lower = msg.toLowerCase();
    let reply = '';
    let leadCaptured = false;

    // Detect interest keywords to advance from recommendation to lead capture
    const interestWords = ['yes', 'interested', 'please', 'sure', 'go ahead', 'sounds good', 'let\'s do it', 'ok', 'okay', 'absolutely', 'definitely'];

    switch (mockState) {
      case 'greet':
        reply = "Thanks for reaching out. Can you tell me what industry you're in and roughly how many employees you have?";
        mockState = 'needs';
        break;

      case 'needs':
        reply = "Got it. And what specific tasks are you looking to automate or improve? For example — customer calls, appointment scheduling, data entry, something else?";
        mockState = 'recommend';
        break;

      case 'recommend':
        reply = "Based on what you've described, I'd recommend starting with a <strong>Forge Assessment</strong> (free) to map out your workflow. From there, a <strong>Forge Launch</strong> project in the $2,500–$5,000 range would likely cover what you need.<br><br>Would you like me to capture your details so our team can follow up with a personalized proposal?";
        mockState = 'check_interest';
        break;

      case 'check_interest':
        if (interestWords.some(w => lower.includes(w))) {
          reply = "Great. Let me grab a few details.<br><br>First — what's your full name?";
          mockState = 'name';
        } else {
          reply = "No problem at all. Feel free to browse our <a href='pricing.html'>pricing page</a> or <a href='signet.html'>The Signet</a> for more information. I'm here whenever you're ready.";
          // stay in check_interest
        }
        break;

      case 'name':
        reply = "Thanks. And what's the name of your company?";
        mockState = 'company';
        break;

      case 'company':
        reply = "Got it. What's the best email address to reach you at?";
        mockState = 'email';
        break;

      case 'email':
        reply = "Perfect. And a phone number? (This is optional — just if you'd prefer a call.)";
        mockState = 'phone';
        break;

      case 'phone':
        reply = "I've captured your information. Here's what I have:<br><br><strong>Your Needs:</strong> Automation assessment and potential implementation.<br><br>A member of our team will follow up within <strong>one business day</strong> with a personalized proposal. In the meantime, feel free to browse our <a href='pricing.html'>pricing page</a> or <a href='signet.html'>The Signet</a>.";
        leadCaptured = true;
        mockState = 'done';
        break;

      default:
        reply = "I've already captured your details. Our team will be in touch soon. Is there anything else about our services I can help with?";
        break;
    }

    return { reply, lead_captured: leadCaptured };
  }

  // ── Event listeners ──────────────────────────────────────
  updateServiceStatus();
  sendBtn.addEventListener('click', sendMessage);

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Focus input on load
  setTimeout(() => inputEl.focus(), 500);

})();
