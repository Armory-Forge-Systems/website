# SECURITY.md — Armory Forge Systems

> "You imagine. We build. We protect."
>
> Security is a first-class deliverable for every AFS engagement — not an afterthought.

_Last updated: 2026-08-02_

---

## Security Highlights

- **Secrets are stored in AWS Secrets Manager.** Application secrets (API keys, SMTP credentials, tokens) are pulled from AWS Secrets Manager at runtime. Local development falls back to environment variables only — never committed files.
- **No API keys are committed to the repository.** Secret material never enters version control. Terraform variables use `.tfvars.example` templates; real values live in local/secret stores.
- **IAM follows least-privilege principles.** Identities and roles are scoped to the minimum permissions required for their function. No shared root credentials; access is role-based and granular.
- **User input is validated before invoking tools.** All external input is validated, length-limited, and rate-limited before any processing or tool invocation.
- **Security events are logged for auditing.** Sensitive operations are recorded in the audit log (CloudWatch + `audit_log` schema) for review and incident reconstruction.
- **The Armorer's input is sanitized and scanned by Threat Intelligence.** The public-facing AI receptionist runs a strict structured-intake protocol: input is validated, capped, rate-limited per IP, and screened for malicious or off-task content before any action is taken.

---

## Operational Security Procedures

### 1. Secret Management
- Secrets stored in **AWS Secrets Manager** (`armorer/production` etc.), fetched server-side at startup.
- Environment-variable fallback exists for **local development only** — never for production deployments.
- API keys, app passwords, tokens, and credentials are **never revealed in chat responses** (secrets-gate policy enforced).
- `.tfvars.example` files document required variables; real `.tfvars` files are never committed.

### 2. Infrastructure Security (Client Onboarding)
Every client environment is provisioned from the Terraform onboarding template with isolation baked in:
- **Dedicated VPC** per client with public/private subnet separation.
- **RDS in private subnets only** — no public database endpoints.
- **Bastion-host-only SSH access** — no direct public SSH to application instances; access is restricted to allowlisted CIDRs.
- **Encryption at rest** on databases (`storage_encrypted = true`).
- **Automated backups** with configurable retention; optional Multi-AZ for high availability.
- Security groups scoped per tier (bastion ↔ database ↔ application), never wide open.

### 3. Application Security (The Armorer)
- **Strict conversation protocol** — the Armorer is a structured intake system, not an open chatbot. It does not engage in off-task conversation, which eliminates a whole class of abuse.
- **Input validation** — messages validated on length (1–2000 chars) and content before processing.
- **Rate limiting** — per-IP request limits with blocking and logging on abuse.
- **Session caps** — conversation length, concurrent session, and phone-session limits enforced; overflow is rejected.
- **Lead data is captured and emailed** to the AFS team via secured SMTP credentials from Secrets Manager — the public machine never stores CRM data.

### 4. AI Agent & Prompt-Injection Defense
- **Prompt-injection alerting** — attempts to hijack agents (prompt injection, malicious code uploads, "forget all previous instructions" style attacks) trigger automated **security alert emails**.
- **Second set of eyes** — security alerts are reviewed and triaged by a dedicated monitoring agent: real attacks flagged and escalated fast, noise discarded. Purpose: keep customer CRM data off public-facing machines.
- **Identity verification challenge** — suspicious requests (bulk extraction, account compromise signals) are challenged with a private verification question. A wrong answer = shut down, don't engage, flag.
- **Threat intelligence scanning** — agent inputs screened against threat patterns before processing.

### 5. AI Threat Intelligence Stack (Armory / Email Guardian)
Three-tier AI security architecture for inbound communications:
- **Tier 1 — Gatekeeper:** cheap/fast pre-filter for every message — sender reputation, SPF/DKIM/DMARC, phishing language, suspicious links, attachment flags.
- **Tier 2 — Investigator:** reasoning model on elevated risk — conversation history, business context, invoice fraud, credential harvesting, Business Email Compromise (BEC) analysis. Produces risk + confidence scores with human-readable explanations.
- **Tier 3 — Thanos:** heavy analysis reserved for high-risk cases — threat intelligence lookup, attachment sandboxing, URL expansion, malware indicators, zero-day detection support, incident report generation.
- **Outcomes:** quarantine, user/IT notification, sender blocking, security reports.

### 6. Monitoring & Auditing
- **CloudWatch** for infrastructure and application monitoring, alerting, and log retention.
- **`audit_log` schema** in the core database records security-relevant events.
- **Security alerts** fire on injection attempts and malicious uploads — with a review process behind them, not just a mailbox.

### 7. Data Protection
- **Customer CRM data is never stored on public-facing machines** — public surfaces are lead-capture only; data flows to secured backends.
- **Encryption at rest** on managed databases; **TLS in transit** on public endpoints.
- **Least-privilege access** to customer environments via bastion + allowlisted SSH + scoped security groups.
- **Static public surface** (GitHub Pages) — no server-side processing exposed on the public web tier.

---

## Reporting a Vulnerability

Found a security issue in an AFS product or infrastructure? Report it to **info@armoryforgesystems.com**.

Include:
- Product / URL affected
- Steps to reproduce
- Impact description

We acknowledge reports promptly and keep reporters informed through remediation.

---

_© 2026 Armory Forge Systems. You imagine. We build. We protect._
