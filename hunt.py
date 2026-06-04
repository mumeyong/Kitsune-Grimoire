import os
import sys
import json
import argparse
import subprocess
import threading
import time
import re
import random
import markdown
from pathlib import Path
from datetime import datetime

# ── Load .env ─────────────────────────────────────────────────────────────────
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            # Strip comments from the value
            v = v.split("#")[0].strip()
            os.environ.setdefault(k.strip(), v)

# ── Config ────────────────────────────────────────────────────────────────────
SKILLS_DIR = Path(__file__).parent / ".claude" / "skills"
SESSIONS_DIR = Path(__file__).parent / "sessions"
REPORTS_DIR = Path(__file__).parent / "reports"

SESSIONS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
]

STEALTH_HEADERS = [
    "X-Forwarded-For: 127.0.0.1",
    "X-Originating-IP: 127.0.0.1",
    "X-Remote-IP: 127.0.0.1",
    "X-Remote-Addr: 127.0.0.1",
    "X-Client-IP: 127.0.0.1",
    "X-Host: localhost",
    "X-Forwarded-Host: localhost"
]

# ── LLM Client ────────────────────────────────────────────────────────────────

def call_llm(prompt: str, system_prompt: str = "You are a senior security researcher.") -> str:
    try:
        from openai import OpenAI
    except ImportError:
        print("[!] pip install openai")
        sys.exit(1)

    model = os.environ.get("LLM_MODEL", "qwen2.5-coder:7b")
    base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "ollama")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
    
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000
        )
        content = resp.choices[0].message.content
        
        # Aggressive JSON extraction
        json_match = re.search(r"(\[.*\]|\{.*\})", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        # FIX: Escape problematic backslashes that are NOT part of a valid escape sequence
        content = re.sub(r'\\(?![/u"\\bfnrt])', r'\\\\', content)

        # Simple fix for truncated JSON
        if content.count("[") > content.count("]"): content = content.rstrip(", \n") + "]"
        elif content.count("{") > content.count("}"): content = content.rstrip(", \n") + "}"
            
        return content
    except Exception as e:
        return f"DEBUG_ERROR: {str(e)}"

# ── Stealth Helpers ──────────────────────────────────────────────────────────

def tamper_payload(cmd):
    """Automatically applies WAF bypass techniques to curl commands."""
    # 1. SQLi space tampering
    if "SELECT" in cmd.upper() or "UNION" in cmd.upper():
        cmd = cmd.replace(" ", "/**/")
    
    # 2. Add random stealth headers
    h = random.choice(STEALTH_HEADERS)
    cmd = cmd.replace("curl ", f"curl -H '{h}' ")
    
    # 3. Add 'jitter' parameter to confuse WAF
    junk = f"nocache={random.randint(1000, 9999)}"
    if "?" in cmd: cmd = cmd.replace("?", f"?{junk}&")
    else: 
        # If it's a simple URL, add the junk param
        cmd = re.sub(r"(https?://[^\s\"']+)", r"\1?" + junk, cmd)
        
    return cmd

# ── Core Engine ───────────────────────────────────────────────────────────────

class HunterEngine:
    def __init__(self, target, types=None, wide_scope=False, scan_only=False, raw=False, cookie=None, user_agent=None, extra_paths=None):
        self.base_target = target
        self.domain = re.sub(r'^https?://', '', target).split('/')[0]
        self.types = types or ["idor", "sqli", "xss", "auth", "rce", "ssrf", "insecure"]
        self.wide_scope = wide_scope
        self.scan_only = scan_only
        self.raw = raw
        self.cookie = cookie
        self.user_agent = user_agent
        self.extra_paths = extra_paths or []
        self.targets_to_hunt = [target]
        self.recon_data = {}
        self.findings = []
        self.validated_findings = []
        self.final_analysis_text = ""

    def discover_subdomains(self):
        print(f"[*] Phase 0: Wide-Scope Discovery (Subfinder)...")
        try:
            cmd = f"subfinder -d {self.domain} -silent"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            subs = [s.strip() for s in res.stdout.splitlines() if s.strip()]
            if subs:
                print(f"  [+] Found {len(subs)} subdomains. Picking 3 for AI audit...")
                prompt = f"Pick 3 most interesting subdomains for security audit: {', '.join(subs[:40])}. Return ONLY JSON array: [\"sub1\", \"sub2\"]"
                selected = json.loads(call_llm(prompt))
                for s in selected: self.targets_to_hunt.append(f"https://{s}")
        except: pass

    def run_recon(self, target):
        domain = re.sub(r'^https?://', '', target).split('/')[0]
        print(f"[*] Phase 1: Deep Stealth Recon on {target}...")
        recon = {"endpoints": [], "params": [], "tech": []}
        
        # 1. Fetch homepage and extract parameters/links
        ua = random.choice(USER_AGENTS)
        try:
            res = subprocess.run(f"curl -L -s -m 20 -H 'User-Agent: {ua}' {target}", shell=True, capture_output=True, text=True, timeout=30)
            html = res.stdout
            
            # Extract links with parameters (improved regex)
            links = re.findall(r'href=["\']([^"\'>]+)["\']', html)
            for link in links:
                if "?" in link:
                    if not link.startswith("http"): link = f"{target.rstrip('/')}/{link.lstrip('/')}"
                    recon["endpoints"].append({"url": link, "type": "discovered"})
                    # Extract parameter names
                    params = re.findall(r'([\w-]+)=', link)
                    recon["params"].extend(params)
            
            # Extract forms
            forms = re.findall(r'<form[^>]+action=["\']([^"\']+)["\']', html)
            for form in forms[:5]:
                if not form.startswith("http"): form = f"{target.rstrip('/')}/{form.lstrip('/')}"
                recon["endpoints"].append({"url": form, "type": "form"})
                
        except Exception as e:
            print(f"  [!] Recon error: {e}")

        # 2. Directory probing (refined)
        paths = ["/api/v1", "/admin", "/.env", "/.git", "/graphql", "/v1/user", "/robots.txt", "/sitemap.xml"]
        paths.extend(self.extra_paths)
        
        for p in paths:
            url = f"{target.rstrip('/')}{p}"
            ua = self.user_agent or random.choice(USER_AGENTS)
            time.sleep(random.uniform(0.1, 0.3))
            
            # Construct curl command for probing
            cmd = f"curl -L -o /dev/null -s -w '%{{http_code}}' -m 10 -H 'User-Agent: {ua}' "
            if self.cookie:
                cmd += f"-H 'Cookie: {self.cookie}' "
            cmd += f"'{url}'"
            
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                code = res.stdout.strip()
                if code in ["200", "403", "500", "401"]:
                    recon["endpoints"].append({"url": url, "code": code, "type": "probe"})
                    print(f"  [+] Found probe endpoint: {url} (Code: {code})")
            except: pass
            
        recon["params"] = list(set(recon["params"]))
        self.recon_data[target] = recon

    def launch_hunter(self, target, h_type):
        print(f"[*] Launching {h_type.upper()} Hunter on {target}...")
        skill_path = SKILLS_DIR / f"find-{h_type}" / "SKILL.md"
        skill = skill_path.read_text() if skill_path.exists() else "Standard security hunting."
        
        recon = self.recon_data.get(target, {"endpoints": [], "params": []})
        if not recon["endpoints"] and not recon["params"]:
            print(f"  [!] No attack surface found for {h_type}")
            return

        prompt = f"""
        Role: Senior Penetration Tester
        Target: {target}
        Type: {h_type}
        Attack Surface: {json.dumps(recon['endpoints'][:8])}
        
        Task: Generate 2-3 specific curl commands to test for {h_type}.
        - Use discovered parameters.
        - Use single quotes for the curl command to avoid escape issues.
        - Return ONLY a JSON array of test objects.
        
        Format Example:
        [
          {{"name": "Test Name", "curl_command": "curl -X GET '...' ", "description": "..."}}
        ]
        """
        try:
            raw_response = call_llm(prompt)
            if not raw_response or "DEBUG_ERROR" in raw_response:
                print(f"  [!] AI failed for {h_type}: {raw_response}")
                return
            
            # Clean up potential truncation
            if raw_response.strip().endswith(",") or not raw_response.strip().endswith("]"):
                if "[" in raw_response and "]" not in raw_response: raw_response += "]"
            
            data = json.loads(raw_response)
            tests = data.get("tests", data) if isinstance(data, dict) else data
            
            if not isinstance(tests, list):
                print(f"  [!] AI returned invalid format for {h_type}")
                return

            for test in tests:
                if isinstance(test, dict) and "curl_command" in test:
                    test["curl_command"] = tamper_payload(test["curl_command"])
                    self.execute_test(h_type, test)
        except Exception as e:
            print(f"  [!] AI Planning error for {h_type}: {e}")

    def execute_test(self, h_type, test):
        cmd = test.get("curl_command")
        if not cmd: return
        print(f"  [~] Testing {h_type}: {test.get('name')}")
        
        # Extract URL from curl command to verify domain
        url_match = re.search(r"https?://[^\s\"']+", cmd)
        cmd_url = url_match.group(0) if url_match else ""
        
        # Ensure we don't accidentally attack the wrong domain if the AI hallucinated
        # We check the URL specifically, and allow localhost/127.0.0.1 for SSRF tests
        if self.domain not in cmd_url and "localhost" not in cmd_url and "127.0.0.1" not in cmd_url:
            print(f"    [!] Skipping command on wrong domain URL: {cmd_url[:50]}...")
            return

        ua = self.user_agent or random.choice(USER_AGENTS)
        if " -H " not in cmd: cmd += f" -H 'User-Agent: {ua}'"
        else: cmd = re.sub(r"-H 'User-Agent: [^']*'", f"-H 'User-Agent: {ua}'", cmd)
        
        # Add Cookie header if provided
        if self.cookie:
            if " -H 'Cookie:" not in cmd:
                cmd += f" -H 'Cookie: {self.cookie}'"

        # Add -i for headers if raw mode is on
        if self.raw:
            if " -i" not in cmd: cmd = cmd.replace("curl ", "curl -i ")

        time.sleep(random.uniform(0.5, 1.5)) 
        
        cmd_with_code = cmd.replace("curl ", "curl -L -s -w ' HTTP_CODE:%{http_code}' ")
        try:
            res = subprocess.run(cmd_with_code, shell=True, capture_output=True, text=True, timeout=20)
            output = res.stdout
            code = "Unknown"
            if " HTTP_CODE:" in output:
                output, code = output.rsplit(" HTTP_CODE:", 1)
                code = code.strip()

            # More generous detection for debug
            is_vuln = False
            if code in ["200", "500"]: 
                # Check for common error indicators
                low_out = output.lower()
                indicators = ["mysql", "sql syntax", "error", "warning", "<script>alert", "uid="]
                if any(ind in low_out for ind in indicators):
                    is_vuln = True
                
            if is_vuln or code == "200" or self.scan_only:
                if is_vuln or code == "200":
                    print(f"    [+] Response received. Code: {code}")
                
                evidence_limit = 50000 if self.raw else 800
                self.findings.append({
                    "type": h_type, 
                    "test": test.get("name"), 
                    "curl_command": cmd, 
                    "evidence": output[:evidence_limit], 
                    "code": code,
                    "is_potential_vuln": is_vuln
                })
        except Exception as e:
            print(f"    [!] Execution error: {e}")

    def validate_findings(self):
        if not self.findings: return
        print(f"[*] Phase 3: Skeptical Validation of {len(self.findings)} findings...")
        for i in range(0, len(self.findings), 5):
            batch = self.findings[i:i+5]
            prompt = f"""
            Analyze these security findings and determine if they represent a real vulnerability.
            
            Findings Batch: {json.dumps(batch)}
            
            CRITERIA:
            - If the 'evidence' contains a database error (MySQL, SQL syntax), it is CONFIRMED SQLi.
            - If the 'evidence' contains script tags or payloads reflected, it is CONFIRMED XSS.
            - If the 'evidence' shows a successful login or bypass, it is CONFIRMED AUTH.
            - If the response is a 403 WAF block, mark as FALSE_POSITIVE.
            - If the response is generic 200 without evidence of the payload working, mark as UNLIKELY.
            
            Return ONLY JSON array of objects:
            [{{"type", "status": "CONFIRMED|LIKELY|UNLIKELY|FALSE_POSITIVE", "severity", "reproduction", "impact", "remediation"}}]
            """
            try:
                raw_response = call_llm(prompt)
                results = json.loads(raw_response)
                self.validated_findings.extend(results)
            except Exception as e:
                print(f"  [!] Validation parsing error: {e}")

    def generate_final_analysis(self):
        confirmed = [f for f in self.validated_findings if f.get("status") == "CONFIRMED"]
        print("\n" + "═" * 60 + "\n 🧠 KITSUNE INTELLIGENT ANALYSIS\n" + "═" * 60 + "\n")
        if not confirmed:
            print("No confirmed vulnerabilities. The target is likely protected by a strong WAF (CloudFront/AWS).")
            self.final_analysis_text = "No confirmed vulnerabilities."
            return
        
        summary_parts = ["### Summary of CONFIRMED Findings for " + self.base_target]
        for f in confirmed:
            summary_parts.append(f"#### {f['type'].upper()} - {f.get('severity', 'UNKNOWN')}")
            summary_parts.append(f"- **Reproduction:** `{f.get('reproduction', 'N/A')}`")
            summary_parts.append(f"- **Impact:** {f.get('impact', 'N/A')}")
            summary_parts.append(f"- **Remediation:** {f.get('remediation', 'N/A')}")
            summary_parts.append("")
            
        self.final_analysis_text = "\n".join(summary_parts)
        print(self.final_analysis_text)

    def save_results(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = REPORTS_DIR / self.domain
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Save Markdown
        md_content = f"# Kitsune-Grimoire Audit: {self.domain}\n\n{self.final_analysis_text}"
        with open(target_dir / f"report_{ts}.md", "w") as f:
            f.write(md_content)
        
        # 2. Save HTML for Browser
        html_content = markdown.markdown(md_content)
        full_html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Kitsune Audit: {self.domain}</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0d1117; color: #c9d1d9; line-height: 1.6; padding: 40px; }}
                .container {{ max-width: 900px; margin: auto; background: #161b22; padding: 30px; border-radius: 12px; border: 1px solid #30363d; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
                h1 {{ color: #58a6ff; border-bottom: 2px solid #30363d; padding-bottom: 10px; font-size: 2.5em; }}
                h2 {{ color: #ff7b72; margin-top: 30px; }}
                code {{ background-color: rgba(110,118,129,0.4); padding: 0.2em 0.4em; border-radius: 6px; font-family: monospace; }}
                pre {{ background: #010409; padding: 20px; border-radius: 8px; border: 1px solid #30363d; overflow-x: auto; color: #79c0ff; }}
                blockquote {{ border-left: 4px solid #8b949e; color: #8b949e; padding-left: 20px; margin: 20px 0; }}
                a {{ color: #58a6ff; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
                .footer {{ text-align: center; margin-top: 50px; color: #8b949e; font-size: 0.8em; }}
            </style>
        </head>
        <body>
            <div class="container">
                {html_content}
                <div class="footer">
                    Generated by Kitsune-Grimoire Local Edition • {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                </div>
            </div>
        </body>
        </html>
        """
        with open(target_dir / f"report_{ts}.html", "w") as f:
            f.write(full_html)

        # 3. Save JSON Session for Resonance (Gemini Analysis)
        session_data = {
            "target": self.base_target,
            "timestamp": ts,
            "recon_data": self.recon_data,
            "findings": self.findings,
            "validated_findings": self.validated_findings,
            "scan_only": self.scan_only,
            "raw": self.raw
        }
        json_path = SESSIONS_DIR / f"session_{self.domain}_{ts}.json"
        with open(json_path, "w") as f:
            json.dump(session_data, f, indent=2)
            
        print(f"[*] Report saved to {target_dir}")
        print(f"[*] JSON session saved to {json_path} (Use this for Gemini analysis)")

    def run(self):
        if self.wide_scope: self.discover_subdomains()
        for t in self.targets_to_hunt:
            self.run_recon(t)
            for h in self.types: self.launch_hunter(t, h)
        
        if not self.scan_only:
            self.validate_findings()
            self.generate_final_analysis()
        else:
            print(f"\n[*] Scan complete. Found {len(self.findings)} potential resonance points.")
            self.final_analysis_text = f"Scan-only mode. {len(self.findings)} findings collected for Gemini analysis."
            
        self.save_results()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="Target URL (e.g., https://example.com)")
    parser.add_argument("--wide", action="store_true", help="Enable wide-scope discovery (subdomains)")
    parser.add_argument("--scan-only", action="store_true", help="Skip LLM validation/analysis (faster, saves Ollama tokens)")
    parser.add_argument("--raw", action="store_true", help="Capture full HTTP responses and headers")
    parser.add_argument("--types", help="Comma-separated list of hunter types to run (e.g., sqli,xss)")
    parser.add_argument("--cookie", help="Custom Cookie header to bypass WAF challenges")
    parser.add_argument("--user-agent", help="Custom User-Agent header for exact browser impersonation")
    parser.add_argument("--extra-paths", help="Comma-separated list of extra paths to probe (e.g., /admin,/actuator/env)")
    
    args = parser.parse_args()
    
    selected_types = None
    if args.types:
        selected_types = [t.strip().lower() for t in args.types.split(",")]

    extra_paths_list = []
    if args.extra_paths:
        extra_paths_list = [p.strip() for p in args.extra_paths.split(",")]

    print("\n╔══════════════════════════════════════════╗")
    print("║     Kitsune-Grimoire — Stealth Hunter    ║")
    print("╚══════════════════════════════════════════╝\n")
    
    engine = HunterEngine(
        args.target, 
        types=selected_types, 
        wide_scope=args.wide, 
        scan_only=args.scan_only, 
        raw=args.raw,
        cookie=args.cookie,
        user_agent=args.user_agent,
        extra_paths=extra_paths_list
    )
    engine.run()
