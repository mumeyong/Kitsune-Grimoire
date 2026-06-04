# 🦊 Kitsune-Grimoire: Local Edition
**Fully Autonomous AI Security Agents — Powered by your GPU**

Kitsune-Grimoire has been evolved to run **100% locally** using Ollama and your own hardware (optimized for high-end GPUs like the RTX 5070 Ti). No more Gemini rate limits, no more Claude subscription fees—just unlimited, private bug hunting.

---

## 🚀 Why Kitsune-Grimoire Local?

- **💰 Zero Cost**: Unlimited tokens via Ollama.
- **🛡️ 100% Private**: Your targets and findings never leave your machine.
- **⚡ GPU Accelerated**: Orchestrates 18 parallel hunters using your local VRAM.
- **🧠 Expert Skills**: Uses the same high-quality vulnerability patterns extracted from real HackerOne disclosures.

---

## 🛠️ Setup (Kali WSL / Linux)

### 1. Install Ollama & Models
Kitsune-Grimoire runs 100% locally. You'll need Ollama to host the models:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start the service
ollama serve &

# Pull the high-performance coder models
ollama pull qwen2.5-coder:7b
```

### 2. Fast Installation
Clone and run the automated installer:
```bash
git clone https://github.com/mumeyong/Kitsune-Grimoire.git
cd Kitsune-Grimoire
chmod +x install.sh
./install.sh
```

### 3. Configure `.env`
The installer creates a `.env` template. Open it and add your keys:

```bash
# Required for generating/updating skills
HF_TOKEN=hf_your_token_here

# LLM Provider (Default: Local Ollama)
LLM_PROVIDER=openai-compat
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=qwen2.5-coder:7b
```

### 4. Required Tools
For wide-scope subdomain discovery, ensure `subfinder` is installed:
```bash
# Install subfinder
sudo apt install subfinder  # Or go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
```

---

## 🧬 Hybrid "Resonance" Mode (Gemini + Ollama)

Maximize token efficiency by delegating raw scanning to Ollama and expert analysis to Gemini CLI.

### 1. Perform a "Resonance Scan" with Ollama
Use Ollama to perform the high-volume, token-intensive scanning. The `--raw` flag ensures full response headers and bodies are captured for later analysis.

```bash
python3 hunt.py https://target.com --scan-only --raw
```

### 2. Expert Analysis with Gemini CLI
Once the scan is complete, Gemini CLI can read the session JSON and provide a high-fidelity "Resonance Report" with WAF bypass techniques and exploit chains.

**Benefits:**
- **Zero Token Cost** for the initial 100+ requests.
- **Deep Analysis**: Gemini uses its 2M context window to look for patterns Ollama 7b might miss.
- **Headers Analysis**: Captured headers allow for finding subtle cache poisoning or security misconfigurations.

### 1. The "All-In" Hunt
Launch all 18 specialized hunters simultaneously on a target:
```bash
source .venv/bin/activate
python3 hunt.py https://target.com
```

### 2. Targeted Hunting (Low & Slow)
For real-world targets, it's better to run specific hunters to avoid WAF detection:
```bash
# Hunt for Injection bugs only
python3 hunt.py https://target.com --types sqli,xss,rce,ssti

# Hunt for Logic & Auth bugs
python3 hunt.py https://target.com --types idor,auth,bizlogic

# Hunt for All types
python3 hunt.py https://target.com --types idor,ssrf,sqli,xss,auth,rce,xxe,ssti,secrets,otp,pii,bizlogic,callback,enumerable,insecure,referer,checksum
```
---

## 🧬 Dynamic Skill Generator (Dataset Integration)

Kitsune-Grimoire doesn't just use static rules. You can "train" your agents on the absolute latest public bug reports from HackerOne. This uses the **HackerOne Transparency Dataset** to update your agents' specialized skills.

### 1. Configure HuggingFace
To fetch the latest reports, get a free token from [HuggingFace](https://huggingface.co/settings/tokens) and add it to your `.env`:
```bash
HF_TOKEN=hf_your_token_here
```

### 2. Upgrade your Agents
Use the `generate-skill.py` tool to refresh an agent's knowledge with the latest $N$ reports:

```bash
# Enhance the XSS agent with patterns from the last 50 public reports
python3 generate-skill.py xss --max 50

# Rebuild ALL agents simultaneously with new data
python3 generate-skill.py --all --max 20
```

### 3. Use your own Writeups
You can also feed your own private bug reports (Markdown/Text) to your agents so they learn your personal techniques:
```bash
python3 generate-skill.py rce --extra ./my-private-writeups/
```

---

## 🦠 The 18 Specialized Hunters

| 🕵️ Agent | 🎯 Primary Target | 🕵️ Agent | 🎯 Primary Target |
| :--- | :--- | :--- | :--- |
| **`IDOR`** | BOLA, Privilege Escalation | **`SSRF`** | Metadata, Internal networks |
| **`SQLi`** | Blind, Error, Time-based | **`XSS`** | Stored, Reflected, DOM |
| **`Auth`** | Session hijacking, MFA | **`RCE`** | Command/Code Injection |
| **`XXE`** | Entity Injection, LFI | **`SSTI`** | Template Engine Injection |
| **`Secrets`**| Exposed API Keys, .env | **`OTP`** | Brute force, Flow bypass |
| **`PII`** | Data leaks, Privacy | **`BizLogic`**| Price/Race conditions |
| **`Callback`**| Open Redirects | **`Recon`** | Path mapping, Tech stacks |
| **`Insecure`**| CORS, Security Headers | **`Referer`** | Header Token Leaks |
| **`Checksum`**| Integrity bypassing | **`Enumerable`**| Sequential ID leakage |

---

## 📂 Results & Reports

Every hunt generates a timestamped JSON report in the `sessions/` directory.

- **Check Findings**: `cat sessions/latest_report.json | jq`
- **Confirmed Bugs**: Findings marked as `CONFIRMED` have been automatically verified by the Lead Validator agent using `curl`.

---

## ⚖️ Rules of Engagement

> 🛑 **WARNING**: Unauthorized hacking is illegal.
> Kitsune-Grimoire is designed **strictly** for authorized Bug Bounty programs, your own infrastructure, or contracted penetration tests. Always respect program rules and rate limits.
