"""
Ethical-hacking / security-learning tools (Phase 34).

A small security-lab on JARVIS's desktop, scoped to legitimate,
authorised security work:

    * network_scan    - ping sweep + TCP port check on hosts/networks you
                        control (never sends payloads, connect-only)
    * web_recon       - passive recon on a web target: response headers,
                        missing security headers, robots.txt, TLS cert info
    * cve_lookup      - look up a product/version against public CVE data
    * hash_identify   - recognise the algorithm of a hash (local only)
    * password_audit  - local strength estimate + k-anonymity HaveIBeenPwned
                        check (only the first 5 hash chars ever leave)
    * learn_security  - save security notes into a persistent knowledge
                        bank that is injected into the conversation

Ethics note (kept in every description so the model behaves):
these tools analyse and test - they never attack. They are meant for the
user's own machines, networks and accounts, or anything they have written
authorisation to test. Exploitation against third parties is out of scope.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import ssl
import subprocess
from typing import Any
from urllib.parse import quote, urljoin

import requests

from config import settings
from tools.base import Tool, ToolError

_MAX_SCAN_HOSTS = 32
_MAX_PORT_SCAN_TIMEOUT = 2.0
_SCAN_TIMEOUT = 1.0

#: Common ports worth a quick connect check during a port scan.
COMMON_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993, 995,
    1433, 1521, 3306, 3389, 5432, 6379, 8080, 8443, 9200, 27017,
]

#: Headers that tell a lot about a web target's security posture.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "HSTS (forces HTTPS)",
    "Content-Security-Policy": "CSP (blocks injected content)",
    "X-Frame-Options": "clickjacking protection",
    "X-Content-Type-Options": "MIME-sniffing protection",
    "Referrer-Policy": "referrer leakage control",
    "Permissions-Policy": "browser feature restriction",
    "Cross-Origin-Opener-Policy": "cross-origin isolation",
}

#: Baseline knowledge shipped with JARVIS so the security lab works before
#: the user has taught it anything. Merged with user-added notes.
_OWASP_SEED: dict[str, str] = {
    "sql injection": (
        "Never trust input in database queries. Parameterised queries or an "
        "ORM prevent it; string-concatenated SQL is vulnerable. Test on your "
        "own lab only: string vs parameterised, boolean-blind, union and "
        "time-based payload techniques."
    ),
    "xss": (
        "Cross-site scripting: unescaped user input rendered into HTML/JS. "
        "Reflected, stored and DOM variants. Escape on output, sanitise input, "
        "set a Content-Security-Policy."
    ),
    "authentication bypass": (
        "Weak password/credential checks, default creds, missing rate "
        "limiting, predictable reset tokens. Check auth for: rate limiting, "
        "session fixation, token expiry and MFA bypass paths."
    ),
    "csrf": (
        "Cross-site request forgery: state-changing requests without an "
        "unpredictable token. Defend with anti-CSRF tokens + SameSite cookies."
    ),
    "path traversal": (
        "../ sequences and encoded variants in file parameters. Canonicalise "
        "paths and ensure the result stays inside the allowed root."
    ),
    "command injection": (
        "User input passed into shell commands. Never build shell strings "
        "from input; use argument lists. Look for ; | && and similar when "
        "reviewing code."
    ),
    "ssrf": (
        "Server-side request forgery: the server fetches a URL you control. "
        "Restrict outbound targets, block loopback/link-local ranges."
    ),
    "idor": (
        "Insecure direct object references: guessing ids in URLs/APIs. Check "
        "authorisation on every object access, not just the endpoint."
    ),
    "security headers": (
        "A quick win checklist: HSTS, CSP, X-Frame-Options, "
        "X-Content-Type-Options, Referrer-Policy, Permissions-Policy. Missing "
        "headers are found with web_recon."
    ),
    "recon methodology": (
        "Recon before anything else: identify scope, subdomains, tech stack, "
        "then passive info gathering, then connect-only scans. Never move to "
        "exploitation without written authorisation."
    ),
    "port scanning": (
        "Connect to each port, read the banner, note service + version, then "
        "look the version up in CVE databases. Connect-only (no payloads) is "
        "the safe baseline for authorised testing."
    ),
    "password cracking": (
        "Offline only: extract a hash you own, identify it with hash_identify, "
        "then try dictionary/rule-based attacks against the copy you hold. "
        "Never target someone else's account."
    ),
    "report writing": (
        "End every assessment with a report: what was tested, findings with "
        "severity and proof, remediation steps, and what was out of scope."
    ),
}


# -- Persistence (security_notes.json, gitignored data dir) --------------

def _security_notes_file():
    return settings.data_dir / "security_notes.json"


def load_security_notes() -> dict[str, str]:
    """User-taught security notes merged over the built-in OWASP seed."""
    notes = dict(_OWASP_SEED)
    path = _security_notes_file()
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                notes.update({str(k): str(v) for k, v in saved.items()})
        except (OSError, ValueError):
            pass
    return notes


def _save_security_notes(notes: dict[str, str]) -> None:
    path = _security_notes_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(notes, path.open("w", encoding="utf-8"), indent=2, ensure_ascii=False)


def security_knowledge_block() -> str:
    """Prompt block (like memories/glasses) so the model can use the lab."""
    notes = load_security_notes()
    if not notes:
        return ""
    lines = [
        "Security knowledge you have learned (use it when relevant):",
    ]
    for topic, text in notes.items():
        short = text if len(text) <= 220 else text[:220].rstrip() + "..."
        lines.append(f"- {topic}: {short}")
    return "\n".join(lines)


# -- Shared helpers --------------------------------------------------------

def _tcp_open(host: str, port: int, timeout: float = _SCAN_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ping_alive(host: str) -> bool:
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1500", host],
            capture_output=True,
            timeout=6,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _parse_ports(raw: str) -> list[int]:
    """Accept '80', '80,443' or '20-25' (and mixes)."""
    if not raw:
        return list(COMMON_PORTS)
    ports: list[int] = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            try:
                start, end = (int(p) for p in token.split("-", 1))
            except ValueError:
                raise ToolError(f"Invalid port range: {token!r}")
            if not (0 < start <= end <= 65535):
                raise ToolError(f"Ports out of range in {token!r}.")
            ports.extend(range(start, end + 1))
        else:
            try:
                port = int(token)
            except ValueError:
                raise ToolError(f"Invalid port: {token!r}")
            if not (0 < port <= 65535):
                raise ToolError(f"Port out of range: {port}.")
            ports.append(port)
    return ports


def _normalise_target(raw: str) -> str:
    """A host must look like a hostname or IP; allow host:port split."""
    target = (raw or "").strip().lower()
    if not target:
        raise ToolError("Specify a host or network to scan.")
    return target


# -- network_scan ---------------------------------------------------------

class NetworkScanTool(Tool):
    name = "network_scan"
    description = (
        "Scans a host or network you own (or are authorised to test) with "
        "connect-only probes: a ping check and a TCP connect on common ports. "
        "It sends no payloads and runs nothing. Examples: host='192.168.1.10', "
        "host='127.0.0.1', ports='22,80,443' or '20-25'. For a subnet like "
        "host='192.168.1.0/24' it ping-sweeps and checks the most common ports. "
        "Requires your approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "A hostname, IP, or CIDR network to scan.",
            },
            "ports": {
                "type": "string",
                "description": (
                    "Optional ports to check, e.g. '80,443' or '20-25'. "
                    "Defaults to common ports."
                ),
            },
            "timeout": {
                "type": "number",
                "description": "Seconds to wait per port (default 1).",
            },
        },
        "required": ["host"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        host_raw = _normalise_target(self._arg(args, "host", ""))
        ports = _parse_ports(self._arg(args, "ports", ""))
        timeout = min(
            _MAX_PORT_SCAN_TIMEOUT,
            max(0.2, float(self._arg(args, "timeout", _SCAN_TIMEOUT))),
        )

        if "/" in host_raw:
            return self._scan_network(host_raw, ports, timeout)
        return self._scan_host(host_raw, ports, timeout)

    def _scan_host(self, host: str, ports: list[int], timeout: float) -> str:
        alive = _ping_alive(host)
        open_ports = [p for p in ports if _tcp_open(host, p, timeout)]
        lines = [f"Scan of {host} (connect-only):"]
        lines.append(f"ping: {'alive' if alive else 'no reply'}")
        if open_ports:
            lines.append("open ports: " + ", ".join(str(p) for p in open_ports))
        else:
            lines.append("open ports: none found")
        return "\n".join(lines)

    def _scan_network(self, network: str, ports: list[int], timeout: float) -> str:
        try:
            net = ipaddress.ip_network(network, strict=False)
        except ValueError:
            raise ToolError(f"Invalid network: {network!r}.")
        hosts = list(net.hosts())
        if len(hosts) > _MAX_SCAN_HOSTS:
            hosts = hosts[:_MAX_SCAN_HOSTS]
            truncated = True
        else:
            truncated = False

        lines = [f"Ping-sweep of {net} (first {len(hosts)} addresses, connect-only):"]
        alive_hosts = []
        for host in hosts:
            if _ping_alive(str(host)):
                alive_hosts.append(str(host))
        if not alive_hosts:
            lines.append("no hosts responded to ping")
        for host in alive_hosts:
            open_ports = [p for p in ports if _tcp_open(host, p, timeout)]
            status = f"{host}: alive"
            if open_ports:
                status += " (open: " + ", ".join(str(p) for p in open_ports[:10]) + ")"
            lines.append(status)
        if truncated:
            lines.append(f"(sweep capped at {_MAX_SCAN_HOSTS} addresses)")
        return "\n".join(lines)


# -- web_recon ------------------------------------------------------------

class WebReconTool(Tool):
    name = "web_recon"
    description = (
        "Passive recon on a website you are allowed to assess: HTTP status, "
        "server header, which important security headers are missing, "
        "robots.txt entries and TLS certificate details. Read-only, sends no "
        "payloads. Example url='https://example.com'. Requires your approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The web address to inspect (http/https).",
            }
        },
        "required": ["url"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        url = (self._arg(args, "url", "") or "").strip()
        parsed = requests.utils.urlparse(url)
        if parsed.scheme:
            if parsed.scheme not in ("http", "https"):
                raise ToolError("Only http/https targets are supported.")
        else:
            url = "https://" + url
        try:
            response = requests.get(
                url,
                timeout=15,
                allow_redirects=True,
                headers={"User-Agent": "JARVIS-security-recon/1.0"},
            )
        except requests.RequestException as exc:
            raise ToolError(f"Could not reach {url}: {exc}") from exc

        lines = [
            f"web_recon for {url}",
            f"status: {response.status_code}",
            f"server: {(response.headers.get('server') or 'not advertised')}",
            f"content-type: {response.headers.get('content-type', 'n/a')}",
        ]

        missing = [
            f"{name} ({purpose})"
            for name, purpose in SECURITY_HEADERS.items()
            if name not in response.headers
        ]
        if missing:
            lines.append("missing security headers: " + "; ".join(missing))
        else:
            lines.append("security headers: all common ones present")

        lines.append(self._robots(parsed.scheme, parsed.netloc))
        tls = self._tls(parsed.netloc)
        if tls:
            lines.append(tls)
        return "\n".join(lines)

    @staticmethod
    def _robots(scheme: str, netloc: str) -> str:
        try:
            resp = requests.get(
                f"{scheme}://{netloc}/robots.txt",
                timeout=10,
                headers={"User-Agent": "JARVIS-security-recon/1.0"},
            )
        except requests.RequestException:
            return "robots.txt: unreachable"
        if resp.status_code != 200:
            return "robots.txt: not present"
        disallow = re.findall(r"(?i)^\s*Disallow:\s*(\S+)", resp.text)
        if not disallow:
            return "robots.txt: present, no disallowed paths"
        return "robots.txt disallows: " + ", ".join(disallow[:10])

    @staticmethod
    def _tls(netloc: str) -> str:
        host = netloc.rsplit(":", 1)[0]
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=8) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    cert = tls.getpeercert()
                    if not cert:
                        return "TLS: certificate details unavailable"
                    subject = dict(x[0] for x in cert.get("subject", ()))
                    cn = subject.get("commonName", "?")
                    return f"TLS cert: CN={cn}, expires {cert.get('notAfter', '?')}"
        except (OSError, ssl.SSLError):
            return "TLS: no HTTPS certificate on 443"


# -- cve_lookup -----------------------------------------------------------

class CveLookupTool(Tool):
    name = "cve_lookup"
    description = (
        "Looks up public vulnerabilities for a product and version (e.g. "
        "'nginx 1.18.0' or 'wordpress 6.0') using public CVE data. Returns "
        "the top matches with severity and a short summary. Free, no key needed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Software name and optional version, e.g. 'openssh 9.0'.",
            }
        },
        "required": ["query"],
    }

    _API = "https://cve.circl.lu/api/search/"

    def execute(self, args: dict[str, Any]) -> str:
        query = (self._arg(args, "query", "") or "").strip()
        if not query:
            raise ToolError("Specify a product and version to look up.")
        try:
            response = requests.get(
                self._API + quote(query), timeout=20,
                headers={"User-Agent": "JARVIS-security-recon/1.0"},
            )
            if response.status_code != 200:
                raise ToolError(
                    f"CVE lookup service returned HTTP {response.status_code}."
                )
            data = response.json()
        except requests.RequestException as exc:
            raise ToolError(f"CVE lookup failed: {exc}") from exc

        if not isinstance(data, list) or not data:
            return f"No public CVEs found for {query!r}."
        lines = [f"CVEs for {query!r} (top {min(8, len(data))}):"]
        for item in data[:8]:
            cve_id = item.get("id") or "CVE-????"
            cvss = item.get("cvss")
            summary = (item.get("summary") or "").strip()
            if len(summary) > 220:
                summary = summary[:220].rstrip() + "..."
            score = f"{cvss:.1f}" if isinstance(cvss, (int, float)) else "n/a"
            lines.append(f"- {cve_id} (cvss {score}): {summary}" if summary
                         else f"- {cve_id} (cvss {score})")
        return "\n".join(lines)


# -- hash_identify ---------------------------------------------------------

class HashIdentifyTool(Tool):
    name = "hash_identify"
    description = (
        "Identifies the algorithm of a hash from its format and length "
        "(MD5/SHA-1/SHA-2 family, bcrypt, MD5-crypt, SHA-crypt, argon2, "
        "WordPress/Drupal hashes). Local only, nothing leaves the machine."
    )
    parameters = {
        "type": "object",
        "properties": {
            "hash": {
                "type": "string",
                "description": "The hash to identify.",
            }
        },
        "required": ["hash"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        value = (self._arg(args, "hash", "") or "").strip()
        if not value:
            raise ToolError("Provide a hash to identify.")
        candidates = _identify_hash(value)
        if not candidates:
            return "No algorithm matched. Could be a custom or non-standard hash."
        return "Candidates: " + ", ".join(candidates) + "."


def _identify_hash(value: str) -> list[str]:
    v = value.strip()
    lower = v.lower()
    if v.startswith("$2"):  # $2a$/$2b$/$2y$/$2x$
        return ["bcrypt"]
    if v.startswith("$argon2"):  # $argon2i$ / $argon2id$
        return ["argon2"]
    if v.startswith("$1$"):
        return ["md5-crypt (Unix $1$)"]
    if v.startswith("$5$"):
        return ["sha256-crypt (Unix $5$)"]
    if v.startswith("$6$"):
        return ["sha512-crypt (Unix $6$)"]
    if v.startswith("$apr1$"):
        return ["Apache MD5 (htpasswd $apr1$)"]
    if v.startswith("$P$") or v.startswith("$H$"):
        return ["WordPress / phpBB phpass (MD5-based)"]
    if lower.startswith("sha1$"):
        return ["Django salted SHA-1"]
    if lower.startswith("sha256$"):
        return ["Django salted SHA-256"]
    if lower.startswith("{sha}"):
        return ["Base64 SHA-1 (Unix {SHA})"]
    if lower.startswith("{ssha}"):
        return ["Base64 salted SHA-1 (Unix {SSHA})"]
    if v.startswith("pbkdf2_sha256$"):
        return ["Django PBKDF2-SHA256"]
    if not re.fullmatch(r"[0-9a-fA-F]+", v):
        return []
    length = len(v)
    if length == 32:
        return ["MD5", "MD4", "NTLM", "MySQL 4.1+ password hash"]
    if length == 40:
        return ["SHA-1", "RIPEMD-160", "MySQL 3.x password hash"]
    if length == 56:
        return ["SHA-224"]
    if length == 64:
        return ["SHA-256"]
    if length == 96:
        return ["SHA-384"]
    if length == 128:
        return ["SHA-512"]
    return []


# -- password_audit --------------------------------------------------------

class PasswordAuditTool(Tool):
    name = "password_audit"
    description = (
        "Audits a password for strength (length, character variety, estimated "
        "guessing effort) and checks it against known breaches using the "
        "HaveIBeenPwned k-anonymity API - only the first 5 characters of the "
        "hash ever leave this machine; the password itself is never sent or "
        "echoed back. Requires your approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "password": {
                "type": "string",
                "description": "The password to check.",
            }
        },
        "required": ["password"],
    }

    _HIBP = "https://api.pwnedpasswords.com/range/"

    def execute(self, args: dict[str, Any]) -> str:
        password = self._arg(args, "password", "") or ""
        if not password:
            raise ToolError("Provide a password to audit.")

        length = len(password)
        classes = 0
        if re.search(r"[a-z]", password):
            classes += 1
        if re.search(r"[A-Z]", password):
            classes += 1
        if re.search(r"[0-9]", password):
            classes += 1
        if re.search(r"[^a-zA-Z0-9]", password):
            classes += 1
        charset = (26, 52, 62, 95)[max(0, classes - 1)]
        guesses = charset ** length
        if guesses >= 1e21:
            label = "very strong"
        elif guesses >= 1e15:
            label = "strong"
        elif guesses >= 1e9:
            label = "fair"
        elif guesses >= 1e6:
            label = "weak"
        else:
            label = "very weak"

        lines = [
            f"length: {length}",
            f"character classes used: {classes}",
            f"estimated guessing effort: ~{guesses:.2e} combinations ({label})",
        ]

        try:
            sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
            response = requests.get(
                self._HIBP + sha1[:5],
                timeout=10,
                headers={
                    "User-Agent": "JARVIS-security-recon/1.0",
                    "Add-Padding": "true",
                },
            )
            response.raise_for_status()
            suffix = sha1[5:]
            breaches = 0
            for line in response.text.splitlines():
                candidate, _, count = line.partition(":")
                if candidate == suffix:
                    breaches = int(count)
                    break
            if breaches:
                lines.append(f"found in {breaches} public breach(es) - change it")
            else:
                lines.append("not found in known public breaches")
        except requests.RequestException:
            lines.append("breach check unavailable (HaveIBeenPwned unreachable)")

        return "\n".join(lines)


# -- learn_security --------------------------------------------------------

class LearnSecurityTool(Tool):
    name = "learn_security"
    description = (
        "Saves a security note under a topic (e.g. topic='csrf', "
        "notes='...') into JARVIS's persistent security knowledge bank. "
        "The notes are injected into every future conversation so JARVIS "
        "remembers what it has learned. Use when the user teaches a new "
        "technique or wants a reference stored."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "A short topic name, e.g. 'sql injection'.",
            },
            "notes": {
                "type": "string",
                "description": "The technique/notes to remember.",
            },
        },
        "required": ["topic", "notes"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        topic = (self._arg(args, "topic", "") or "").strip().lower()
        notes = (self._arg(args, "notes", "") or "").strip()
        if not topic or not notes:
            raise ToolError("Provide both a topic and notes to learn.")
        current = load_security_notes()
        current[topic] = notes
        _save_security_notes(current)
        return f"Learned: {topic} - stored in the security knowledge bank."


# -- Registration ----------------------------------------------------------

def register_security_lab_tools(registry) -> None:
    """Register the Phase 34 ethical-hacking tools on a registry."""
    registry.register(NetworkScanTool())
    registry.register(WebReconTool())
    registry.register(CveLookupTool())
    registry.register(HashIdentifyTool())
    registry.register(PasswordAuditTool())
    registry.register(LearnSecurityTool())
