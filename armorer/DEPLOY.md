# The Armorer — AWS Deployment Guide

## Prerequisites
- Ubuntu 22.04+ EC2 instance (t3.small minimum)
- Python 3.11+
- Domain pointed to the instance (or use the public IP)
- DeepSeek API key

## Quick Deploy

### 1. Clone and install
```bash
git clone <your-repo> /opt/armorer
cd /opt/armorer/armorer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
sudo mkdir -p /etc/armorer
sudo tee /etc/armorer/env << 'EOF'
DEEPSEEK_API_KEY=sk-your-key-here
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
NOTIFY_EMAIL=info@armoryforgesystems.com
EOF
```

### 3. Systemd service
```bash
sudo tee /etc/systemd/system/armorer.service << 'EOF'
[Unit]
Description=The Armorer — AI Receptionist
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/armorer/armorer
EnvironmentFile=/etc/armorer/env
ExecStart=/opt/armorer/armorer/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now armorer
```

### 4. Nginx reverse proxy
```bash
sudo tee /etc/nginx/sites-available/armorer << 'EOF'
server {
    listen 80;
    server_name armorer.yourdomain.com;

    # Serve the static website
    root /opt/armorer/website;
    index index.html;

    # Proxy API calls to the Python backend
    location /armorer/api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Health check
    location /armorer/health {
        proxy_pass http://127.0.0.1:8000;
    }

    # Static files
    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/armorer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5. SSL (optional but recommended)
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d armorer.yourdomain.com
```

## Local Development
```bash
# Terminal 1: Backend
cd armorer
ARMORER_DEV_MODE=true python server.py

# Terminal 2: Frontend (just open in browser)
open website/armorer.html
```

The `ARMORER_DEV_MODE=true` flag enables mock AI responses so you don't need a DeepSeek API key for local testing.

## API Endpoints
- `POST /armorer/api/chat` — Send a message, get AI reply
- `GET /armorer/health` — Health check

## Monitoring
```bash
# Check service status
sudo systemctl status armorer

# View logs
sudo journalctl -u armorer -f

# Test the API
curl -X POST http://localhost:8000/armorer/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Hi, I run a dental practice with 5 employees"}'
```
