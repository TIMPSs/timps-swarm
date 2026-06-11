"""
TIMPS Swarm — System-Level Tool Suite

All tools are READ-ONLY by default.
Destructive actions (delete, move, install) are only exposed through
explicit dry-run-first methods that return a script for user approval.

Classes:
  SystemScanner       — processes, startup items, CPU/memory/thermal
  FileScanner         — directory scan, duplicates, large files
  EnvironmentInspector — PATH, Python/Node/Docker/Git health
  BatteryMonitor      — battery status, top energy consumers
  NetworkDiagnostics  — ping, DNS, traceroute, open ports, WiFi
  LogReader           — crash logs, syslog, journalctl
  PrivacyAuditor      — browser cookies, macOS TCC permissions
  BackupChecker       — Time Machine, git uncommitted state
  UpdateChecker       — brew, npm, pip, OS updates
  MediaScanner        — photo/video metadata, naming suggestions
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PLATFORM = platform.system()   # "Darwin" | "Linux" | "Windows"
HOME = Path.home()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: str | List[str], timeout: int = 20) -> Tuple[str, bool]:
    """Run a command, return (output, success). Never raises."""
    try:
        kwargs: dict = {"capture_output": True, "text": True, "timeout": timeout}
        if isinstance(cmd, str):
            kwargs["shell"] = True
        result = subprocess.run(cmd, **kwargs)
        out = (result.stdout + result.stderr).strip()
        return out[:5000], result.returncode == 0
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]", False
    except Exception as exc:
        return f"[error: {exc}]", False


def _json_truncate(obj: Any, max_chars: int = 3000) -> str:
    s = json.dumps(obj, indent=2, default=str)
    return s[:max_chars] + ("…" if len(s) > max_chars else "")


# ---------------------------------------------------------------------------
# SystemScanner
# ---------------------------------------------------------------------------

class SystemScanner:
    """Read-only scan of running processes and system health."""

    def list_processes(self, top_n: int = 25) -> List[Dict]:
        """Top N processes by CPU usage."""
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
                try:
                    mi = p.info["memory_info"]
                    procs.append({
                        "pid": p.info["pid"],
                        "name": p.info["name"],
                        "cpu_pct": round(p.info["cpu_percent"] or 0.0, 1),
                        "mem_mb": round((mi.rss if mi else 0) / 1024 / 1024, 1),
                        "status": p.info["status"],
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
            return procs[:top_n]
        except ImportError:
            cmd = "ps aux -r | head -26" if PLATFORM == "Darwin" else "ps aux --sort=-%cpu | head -26"
            out, _ = _run(cmd)
            return [{"raw": line} for line in out.splitlines()]

    def get_startup_items(self) -> List[Dict]:
        """Items that auto-launch at boot/login."""
        items: List[Dict] = []
        if PLATFORM == "Darwin":
            for base in [
                HOME / "Library/LaunchAgents",
                Path("/Library/LaunchAgents"),
                Path("/Library/LaunchDaemons"),
                HOME / "Library/Application Support/com.apple.backgroundtaskmanagementagent/backgrounditems.btm",
            ]:
                if base.is_dir():
                    for f in base.iterdir():
                        if f.suffix in {".plist", ".btm"}:
                            items.append({"name": f.stem, "path": str(f), "scope": base.name})
            # Login Items via osascript (safe read)
            out, ok = _run(
                "osascript -e 'tell application \"System Events\" to get the name of every login item'"
            )
            if ok and out:
                for name in out.split(","):
                    items.append({"name": name.strip(), "scope": "LoginItems"})
        elif PLATFORM == "Linux":
            out, _ = _run("systemctl list-units --type=service --state=enabled --no-pager --plain 2>/dev/null")
            for line in out.splitlines()[1:]:
                parts = line.split()
                if parts:
                    items.append({"name": parts[0], "scope": "systemd"})
        return items

    def get_system_summary(self) -> Dict:
        """CPU/RAM/Disk snapshot."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(str(HOME))
            return {
                "cpu_pct": cpu,
                "cpu_count": psutil.cpu_count(),
                "mem_total_gb": round(mem.total / 1024 ** 3, 1),
                "mem_used_pct": mem.percent,
                "mem_available_gb": round(mem.available / 1024 ** 3, 1),
                "disk_total_gb": round(disk.total / 1024 ** 3, 1),
                "disk_used_pct": round(disk.percent, 1),
                "disk_free_gb": round(disk.free / 1024 ** 3, 1),
                "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
                "python": sys.version.split()[0],
            }
        except ImportError:
            out, _ = _run("df -h $HOME && uptime")
            return {"raw": out}

    def get_thermal_info(self) -> Dict:
        """CPU temperature if available."""
        try:
            import psutil
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    return {
                        k: [{"label": t.label, "current_c": t.current, "high_c": t.high}
                            for t in v]
                        for k, v in temps.items()
                    }
        except Exception:
            pass
        if PLATFORM == "Darwin":
            out, _ = _run("sudo powermetrics -n 1 --samplers cpu_power -i 1000 2>/dev/null | grep -i temp | head -5", timeout=5)
            return {"powermetrics": out or "unavailable — requires sudo"}
        return {"status": "thermal data unavailable"}

    def generate_cleanup_script(self, startup_items: List[Dict]) -> str:
        """Return a DRY-RUN shell script to disable startup bloat. User must review before running."""
        lines = ["#!/bin/bash", "# TIMPS System Optimizer — REVIEW BEFORE RUNNING", "# This script disables startup items identified as non-essential.", ""]
        if PLATFORM == "Darwin":
            for item in startup_items:
                if item.get("scope") == "LaunchAgents":
                    lines.append(f"# launchctl unload -w {item['path']}")
                elif item.get("scope") == "LoginItems":
                    name = item["name"]
                    lines.append(f"# osascript -e 'tell application \"System Events\" to delete login item \"{name}\"'")
        elif PLATFORM == "Linux":
            for item in startup_items:
                lines.append(f"# sudo systemctl disable {item['name']}")
        lines.append("")
        lines.append("echo 'Remove the # comment prefix from lines you want to execute.'")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FileScanner
# ---------------------------------------------------------------------------

class FileScanner:
    """Read-only filesystem analysis."""

    MAX_FILES = 50_000

    def scan_directory_summary(self, path: str) -> Dict:
        """File type breakdown for a directory (one level deep)."""
        stats: Dict[str, Any] = {"total_files": 0, "total_dirs": 0, "total_size_mb": 0.0, "by_extension": {}}
        try:
            for entry in Path(path).iterdir():
                try:
                    if entry.is_dir():
                        stats["total_dirs"] += 1
                    elif entry.is_file():
                        stats["total_files"] += 1
                        size_mb = entry.stat().st_size / 1024 / 1024
                        stats["total_size_mb"] = round(stats["total_size_mb"] + size_mb, 2)
                        ext = entry.suffix.lower() or "(none)"
                        bucket = stats["by_extension"].setdefault(ext, {"count": 0, "size_mb": 0.0})
                        bucket["count"] += 1
                        bucket["size_mb"] = round(bucket["size_mb"] + size_mb, 2)
                except (PermissionError, OSError):
                    pass
        except Exception:
            pass
        stats["by_extension"] = dict(
            sorted(stats["by_extension"].items(), key=lambda x: x[1]["size_mb"], reverse=True)[:20]
        )
        return stats

    def get_large_files(self, path: str, min_size_mb: float = 50.0, max_results: int = 30) -> List[Dict]:
        """Recursively find large files."""
        results: List[Dict] = []
        count = 0
        try:
            for entry in Path(path).rglob("*"):
                if count > self.MAX_FILES:
                    break
                count += 1
                try:
                    if entry.is_file():
                        size_mb = entry.stat().st_size / 1024 / 1024
                        if size_mb >= min_size_mb:
                            results.append({"path": str(entry), "size_mb": round(size_mb, 1), "name": entry.name})
                except (PermissionError, OSError):
                    pass
        except Exception:
            pass
        results.sort(key=lambda x: x["size_mb"], reverse=True)
        return results[:max_results]

    def find_duplicates(self, path: str, min_size_kb: int = 50) -> Dict[str, List[str]]:
        """Find duplicate files by SHA-256 hash (read-only)."""
        hashes: Dict[str, List[str]] = {}
        count = 0
        try:
            for entry in Path(path).rglob("*"):
                if count > self.MAX_FILES:
                    break
                try:
                    if entry.is_file():
                        size = entry.stat().st_size
                        if size < min_size_kb * 1024:
                            continue
                        count += 1
                        h = hashlib.sha256(entry.read_bytes()).hexdigest()
                        hashes.setdefault(h, []).append(str(entry))
                except (PermissionError, OSError, MemoryError):
                    pass
        except Exception:
            pass
        return {h: paths for h, paths in hashes.items() if len(paths) > 1}

    def generate_organizer_preview(self, path: str) -> Dict[str, List[str]]:
        """
        Suggest where files should move (DRY RUN — no files are moved).
        Returns a mapping of {destination_folder: [source_paths]}.
        """
        ext_to_folder = {
            # Documents
            ".pdf": "Documents/PDFs", ".doc": "Documents/Word", ".docx": "Documents/Word",
            ".xls": "Documents/Spreadsheets", ".xlsx": "Documents/Spreadsheets",
            ".ppt": "Documents/Presentations", ".pptx": "Documents/Presentations",
            ".txt": "Documents/Text", ".md": "Documents/Text",
            # Code
            ".py": "Code/Python", ".js": "Code/JavaScript", ".ts": "Code/TypeScript",
            ".html": "Code/Web", ".css": "Code/Web", ".java": "Code/Java",
            ".go": "Code/Go", ".rs": "Code/Rust", ".sh": "Code/Shell",
            # Images
            ".jpg": "Media/Photos", ".jpeg": "Media/Photos", ".png": "Media/Photos",
            ".gif": "Media/GIFs", ".webp": "Media/Photos", ".heic": "Media/Photos",
            ".svg": "Media/Vector",
            # Video
            ".mp4": "Media/Videos", ".mov": "Media/Videos", ".avi": "Media/Videos",
            ".mkv": "Media/Videos",
            # Audio
            ".mp3": "Media/Audio", ".wav": "Media/Audio", ".flac": "Media/Audio",
            # Archives
            ".zip": "Archives", ".tar": "Archives", ".gz": "Archives", ".7z": "Archives",
            # Apps / Installers
            ".dmg": "Installers", ".pkg": "Installers", ".exe": "Installers",
        }
        plan: Dict[str, List[str]] = {}
        try:
            for entry in Path(path).iterdir():
                if entry.is_file():
                    folder = ext_to_folder.get(entry.suffix.lower(), "Misc")
                    plan.setdefault(folder, []).append(str(entry))
        except Exception:
            pass
        return plan

    def generate_move_script(self, plan: Dict[str, List[str]], base_dir: str) -> str:
        """Generate a shell script from the organizer plan (DRY RUN — commented out)."""
        lines = ["#!/bin/bash", "# TIMPS File Organizer — DRY RUN", "# Remove the '#' prefix from lines you want to execute.", ""]
        for folder, paths in plan.items():
            dest = os.path.join(base_dir, folder)
            lines.append(f"# mkdir -p '{dest}'")
            for p in paths:
                lines.append(f"# mv '{p}' '{dest}/'")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# EnvironmentInspector
# ---------------------------------------------------------------------------

class EnvironmentInspector:
    """Diagnose broken development environments."""

    def _check_tool(self, name: str, version_flag: str = "--version") -> Dict:
        out, ok = _run(f"{name} {version_flag} 2>&1")
        return {"available": ok, "version": out.split("\n")[0][:120] if ok else None, "error": out[:100] if not ok else None}

    def check_python(self) -> Dict:
        result = {
            "python3": self._check_tool("python3"),
            "pip3": self._check_tool("pip3"),
            "active_venv": os.environ.get("VIRTUAL_ENV"),
            "which_python": _run("which python3")[0],
            "pyenv": self._check_tool("pyenv"),
        }
        # Check for common venv issues
        issues = []
        if not result["python3"]["available"]:
            issues.append("python3 not found on PATH")
        if result["active_venv"] and not Path(result["active_venv"]).exists():
            issues.append(f"Active VIRTUAL_ENV {result['active_venv']} does not exist — stale activation")
        result["issues"] = issues
        return result

    def check_node(self) -> Dict:
        result = {
            "node": self._check_tool("node"),
            "npm": self._check_tool("npm"),
            "npx": self._check_tool("npx"),
            "nvm": self._check_tool("nvm", ""),
            "yarn": self._check_tool("yarn"),
            "pnpm": self._check_tool("pnpm"),
        }
        issues = []
        if result["node"]["available"] and result["npm"]["available"]:
            node_v = result["node"]["version"] or ""
            npm_v = result["npm"]["version"] or ""
            # Detect very old Node
            m = re.search(r"v(\d+)", node_v)
            if m and int(m.group(1)) < 16:
                issues.append(f"Node {node_v} is EOL — upgrade to Node 20+")
        result["issues"] = issues
        return result

    def check_docker(self) -> Dict:
        status, ok = _run("docker info 2>&1 | head -6")
        return {
            "docker": self._check_tool("docker"),
            "docker_compose": self._check_tool("docker", "compose version"),
            "daemon_running": ok and "Server Version" in status,
            "status_snippet": status[:300],
            "issues": [] if ok else ["Docker daemon is not running — run: open /Applications/Docker.app" if PLATFORM == "Darwin" else "sudo systemctl start docker"],
        }

    def check_git(self) -> Dict:
        return {
            "git": self._check_tool("git"),
            "user_name": _run("git config user.name")[0],
            "user_email": _run("git config user.email")[0],
            "default_branch": _run("git config init.defaultBranch")[0],
        }

    def inspect_path(self) -> Dict:
        entries = os.environ.get("PATH", "").split(":")
        missing = [p for p in entries if p and not Path(p).exists()]
        seen: set = set()
        dupes = []
        for p in entries:
            if p in seen and p not in dupes:
                dupes.append(p)
            seen.add(p)
        issues = []
        if missing:
            issues.append(f"{len(missing)} PATH directories do not exist: {missing[:5]}")
        if dupes:
            issues.append(f"Duplicate PATH entries: {dupes[:3]}")
        return {"entries": entries, "missing_dirs": missing, "duplicates": dupes, "issues": issues}

    def check_common_configs(self) -> Dict:
        """Check for conflicting shell configs."""
        results = {}
        for f in [HOME / ".bashrc", HOME / ".zshrc", HOME / ".bash_profile", HOME / ".profile"]:
            if f.exists():
                try:
                    content = f.read_text(errors="replace")[:3000]
                    results[f.name] = {"exists": True, "lines": len(content.splitlines()), "snippet": content[:500]}
                except Exception:
                    results[f.name] = {"exists": True, "readable": False}
        return results

    def full_diagnosis(self) -> Dict:
        """Complete environment health report."""
        return {
            "python": self.check_python(),
            "node": self.check_node(),
            "docker": self.check_docker(),
            "git": self.check_git(),
            "path": self.inspect_path(),
            "configs": self.check_common_configs(),
            "shell": os.environ.get("SHELL", "unknown"),
            "home": str(HOME),
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        }

    def generate_fix_commands(self, diagnosis: Dict) -> List[str]:
        """Extract all issues and suggest exact terminal commands to fix them."""
        cmds = []
        for section, data in diagnosis.items():
            if isinstance(data, dict):
                for issue in data.get("issues", []):
                    cmds.append(f"# Issue [{section}]: {issue}")
        return cmds


# ---------------------------------------------------------------------------
# BatteryMonitor
# ---------------------------------------------------------------------------

class BatteryMonitor:
    """Battery and power consumption analysis."""

    def get_battery_status(self) -> Dict:
        try:
            import psutil
            b = psutil.sensors_battery()
            if b:
                return {
                    "percent": b.percent,
                    "plugged_in": b.power_plugged,
                    "hours_left": round(b.secsleft / 3600, 1) if b.secsleft and b.secsleft > 0 and not b.power_plugged else None,
                    "status": "charging" if b.power_plugged else "discharging",
                }
        except Exception:
            pass
        if PLATFORM == "Darwin":
            out, ok = _run("pmset -g batt")
            return {"raw": out, "available": ok}
        return {"available": False, "note": "Battery info not available on this platform"}

    def get_top_energy_consumers(self, n: int = 10) -> List[Dict]:
        """Processes consuming most CPU = most energy (proxy)."""
        try:
            import psutil
            procs = []
            # Two passes to get stable cpu_percent
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    p.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            import time; time.sleep(0.5)
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    mi = p.info["memory_info"]
                    procs.append({
                        "pid": p.info["pid"],
                        "name": p.info["name"],
                        "cpu_pct": round(p.info["cpu_percent"] or 0.0, 1),
                        "mem_mb": round((mi.rss if mi else 0) / 1024 / 1024, 1),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
            return procs[:n]
        except ImportError:
            if PLATFORM == "Darwin":
                out, _ = _run("top -l 2 -n 10 -stats pid,command,cpu,mem | tail -11")
                return [{"raw": out}]
            return []

    def get_macos_battery_history(self) -> str:
        """Read macOS battery cycle count and health."""
        if PLATFORM != "Darwin":
            return "macOS only"
        out, _ = _run("system_profiler SPPowerDataType 2>/dev/null | grep -E 'Cycle Count|Condition|Maximum Capacity'")
        return out or "unavailable — run: system_profiler SPPowerDataType"


# ---------------------------------------------------------------------------
# NetworkDiagnostics
# ---------------------------------------------------------------------------

class NetworkDiagnostics:
    """Network health checks."""

    def ping(self, host: str = "8.8.8.8", count: int = 4) -> Dict:
        cmd = f"ping -c {count} -W 2 {host}" if PLATFORM in ("Darwin", "Linux") else f"ping -n {count} {host}"
        out, ok = _run(cmd, timeout=20)
        # Extract packet loss and avg RTT
        loss_m = re.search(r"(\d+(?:\.\d+)?)%\s+packet loss", out)
        rtt_m = re.search(r"min/avg/max.*?=\s+[\d.]+/([\d.]+)/", out)
        return {
            "host": host,
            "reachable": ok,
            "packet_loss_pct": float(loss_m.group(1)) if loss_m else None,
            "avg_rtt_ms": float(rtt_m.group(1)) if rtt_m else None,
            "output": out[:500],
        }

    def check_dns(self, domain: str = "google.com") -> Dict:
        out, ok = _run(f"nslookup {domain}")
        return {"domain": domain, "resolves": ok, "output": out[:400]}

    def get_open_ports(self) -> List[Dict]:
        if PLATFORM == "Darwin":
            out, _ = _run("netstat -an | grep LISTEN | head -40")
        else:
            out, _ = _run("ss -tlnp 2>/dev/null | head -40")
        ports = []
        for line in out.splitlines():
            if "LISTEN" in line:
                ports.append({"raw": line.strip()})
        return ports or [{"raw": out[:500]}]

    def run_traceroute(self, host: str = "8.8.8.8") -> str:
        cmd = f"traceroute -m 15 -w 2 {host}" if PLATFORM in ("Darwin", "Linux") else f"tracert -h 15 {host}"
        out, _ = _run(cmd, timeout=45)
        return out[:3000]

    def check_wifi_info(self) -> Dict:
        if PLATFORM == "Darwin":
            out, ok = _run(
                "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I 2>/dev/null"
            )
            if not ok:
                out, ok = _run("networksetup -getinfo Wi-Fi 2>/dev/null")
            return {"output": out, "available": ok}
        elif PLATFORM == "Linux":
            out, ok = _run("nmcli -t -f ACTIVE,SSID,SIGNAL,SECURITY dev wifi 2>/dev/null || iwconfig 2>/dev/null")
            return {"output": out, "available": ok}
        return {"available": False}

    def full_diagnosis(self, target: str = "8.8.8.8") -> Dict:
        """Run all network checks and return a structured report."""
        return {
            "internet_ping": self.ping(target),
            "dns": self.check_dns(),
            "localhost_ping": self.ping("127.0.0.1", count=2),
            "wifi": self.check_wifi_info(),
            "open_ports": self.get_open_ports()[:20],
        }


# ---------------------------------------------------------------------------
# LogReader
# ---------------------------------------------------------------------------

class LogReader:
    """Read and parse crash/system logs."""

    def read_crash_logs(self, max_logs: int = 3) -> List[Dict]:
        """Find the most recent crash reports."""
        logs: List[Dict] = []
        crash_dirs: List[Path] = []
        if PLATFORM == "Darwin":
            crash_dirs = [
                HOME / "Library/Logs/DiagnosticReports",
                Path("/Library/Logs/DiagnosticReports"),
            ]
        elif PLATFORM == "Linux":
            crash_dirs = [Path("/var/crash"), Path("/var/log")]

        for d in crash_dirs:
            if not d.exists():
                continue
            try:
                files = sorted(d.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
                for f in files[:max_logs]:
                    try:
                        content = f.read_text(errors="replace")[:4000]
                        logs.append({
                            "file": f.name,
                            "path": str(f),
                            "content": content,
                            "size_kb": round(f.stat().st_size / 1024, 1),
                        })
                    except (PermissionError, OSError):
                        pass
            except (PermissionError, OSError):
                pass
        return logs

    def read_system_log(self, lines: int = 80) -> str:
        if PLATFORM == "Darwin":
            out, ok = _run(f"log show --last 15m --style compact 2>/dev/null | grep -E 'error|fault|crash' | tail -{lines}", timeout=15)
            if not out:
                out, _ = _run(f"tail -{lines} /var/log/system.log 2>/dev/null")
        elif PLATFORM == "Linux":
            out, _ = _run(f"journalctl -n {lines} --no-pager -p 3 2>/dev/null", timeout=10)
        else:
            out = "System log not accessible"
        return out[:4000]

    def read_log_file(self, path: str, tail_lines: int = 100) -> str:
        out, _ = _run(f"tail -{tail_lines} {path}")
        return out[:4000]

    def extract_stack_traces(self, log_content: str) -> List[str]:
        """Extract stack trace blocks from a log string."""
        traces = []
        trace_start = re.compile(r"(Traceback \(most recent call last\)|Exception in thread|at .+\(.+:\d+\))", re.IGNORECASE)
        lines = log_content.splitlines()
        i = 0
        while i < len(lines):
            if trace_start.search(lines[i]):
                block = []
                while i < len(lines) and lines[i].strip():
                    block.append(lines[i])
                    i += 1
                traces.append("\n".join(block[:30]))
            i += 1
        return traces[:5]


# ---------------------------------------------------------------------------
# PrivacyAuditor
# ---------------------------------------------------------------------------

class PrivacyAuditor:
    """Audit privacy exposure (read-only)."""

    def _find_firefox_cookies(self) -> Optional[Path]:
        for base in [
            HOME / "Library/Application Support/Firefox/Profiles",
            HOME / ".mozilla/firefox",
        ]:
            if base.exists():
                for p in base.iterdir():
                    cookies = p / "cookies.sqlite"
                    if cookies.exists():
                        return cookies
        return None

    def get_browser_cookie_stats(self) -> Dict[str, Any]:
        """Count cookies per browser (read-only DB access)."""
        paths = {
            "Chrome":  HOME / "Library/Application Support/Google/Chrome/Default/Cookies",
            "Edge":    HOME / "Library/Application Support/Microsoft Edge/Default/Cookies",
            "Brave":   HOME / "Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies",
            "Firefox": self._find_firefox_cookies(),
        }
        stats: Dict[str, Any] = {}
        for browser, db_path in paths.items():
            if not db_path or not Path(db_path).exists():
                continue
            try:
                # Copy to temp to avoid "database is locked" on running browser
                import shutil, tempfile
                tmp = tempfile.mktemp(suffix=".db")
                shutil.copy2(str(db_path), tmp)
                conn = sqlite3.connect(tmp)
                count = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
                # Top domains
                top = conn.execute(
                    "SELECT host_key, COUNT(*) as n FROM cookies GROUP BY host_key ORDER BY n DESC LIMIT 10"
                ).fetchall()
                conn.close()
                os.unlink(tmp)
                stats[browser] = {"cookie_count": count, "top_domains": [{"domain": r[0], "count": r[1]} for r in top]}
            except Exception as exc:
                stats[browser] = {"cookie_count": "unavailable", "error": str(exc)[:100]}
        return stats

    def get_app_permissions(self) -> Dict:
        """Read macOS TCC database for camera/mic/location access."""
        if PLATFORM != "Darwin":
            return {"available": False, "note": "macOS only"}
        result: Dict[str, List] = {}
        tcc_paths = [
            HOME / "Library/Application Support/com.apple.TCC/TCC.db",
            Path("/Library/Application Support/com.apple.TCC/TCC.db"),
        ]
        for tcc_path in tcc_paths:
            if not tcc_path.exists():
                continue
            try:
                import shutil, tempfile
                tmp = tempfile.mktemp(suffix=".db")
                shutil.copy2(str(tcc_path), tmp)
                conn = sqlite3.connect(tmp)
                # auth_value: 0=deny, 2=allow
                rows = conn.execute(
                    "SELECT service, client, auth_value FROM access ORDER BY service, auth_value DESC"
                ).fetchall()
                conn.close()
                os.unlink(tmp)
                for service, client, auth in rows:
                    # Map auth_value
                    status = "allowed" if auth == 2 else ("denied" if auth == 0 else "limited")
                    result.setdefault(service, []).append({"app": client, "status": status})
                return result
            except Exception as exc:
                return {"error": str(exc)[:200], "note": "May require Full Disk Access permission"}
        return {"available": False, "note": "TCC database not found"}

    def generate_cleanup_manifest(self, cookie_stats: Dict) -> str:
        """Generate a human-readable cleanup plan (no data is deleted)."""
        lines = ["# Privacy Cleanup Manifest — REVIEW BEFORE EXECUTING", ""]
        for browser, info in cookie_stats.items():
            count = info.get("cookie_count", 0)
            if isinstance(count, int) and count > 100:
                lines.append(f"## {browser}: {count:,} cookies")
                lines.append(f"Action: Clear cookies in {browser} Settings > Privacy > Clear Browsing Data")
                lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# BackupChecker
# ---------------------------------------------------------------------------

class BackupChecker:
    """Audit backup status."""

    def check_time_machine(self) -> Dict:
        if PLATFORM != "Darwin":
            return {"available": False}
        latest, ok = _run("tmutil latestbackup 2>/dev/null")
        status, _ = _run("tmutil status 2>/dev/null")
        return {
            "available": True,
            "latest_backup": latest.strip(),
            "status": status[:400],
        }

    def scan_git_repos(self, search_roots: Optional[List[str]] = None) -> List[Dict]:
        """Find git repos and check for unsaved changes."""
        roots = search_roots or [str(HOME / d) for d in ["Desktop", "Documents", "Projects", "dev", "code", "src"]]
        repos: List[Dict] = []
        for root in roots:
            if not Path(root).exists():
                continue
            try:
                for git_dir in Path(root).rglob(".git"):
                    repo = str(git_dir.parent)
                    status, _ = _run(f"git -C '{repo}' status --porcelain 2>/dev/null | head -5")
                    unpushed, _ = _run(f"git -C '{repo}' log '@{{u}}..HEAD' --oneline 2>/dev/null | wc -l")
                    repos.append({
                        "path": repo,
                        "uncommitted_changes": bool(status.strip()),
                        "changes_snippet": status.strip()[:200],
                        "unpushed_commits": unpushed.strip(),
                    })
                    if len(repos) >= 20:
                        break
            except Exception:
                pass
        return repos

    def get_risky_files(self) -> List[Dict]:
        """Files on Desktop/Documents not tracked by git or cloud."""
        risky: List[Dict] = []
        icloud_marker = ".icloud"
        for d in [HOME / "Desktop", HOME / "Documents"]:
            if not d.exists():
                continue
            try:
                for f in d.iterdir():
                    if f.is_file() and not f.name.startswith(".") and f.suffix != icloud_marker:
                        size_mb = f.stat().st_size / 1024 / 1024
                        if size_mb > 0.5:
                            risky.append({"path": str(f), "size_mb": round(size_mb, 1), "name": f.name})
            except Exception:
                pass
        risky.sort(key=lambda x: x["size_mb"], reverse=True)
        return risky[:20]

    def generate_backup_script(self, risky_files: List[Dict]) -> str:
        """Generate an rsync/cp script to back up at-risk files (DRY RUN)."""
        lines = [
            "#!/bin/bash",
            "# TIMPS Backup Sentinel — DRY RUN (remove # prefix to execute)",
            "BACKUP_DEST=~/Backups/timps-$(date +%Y%m%d)",
            "# mkdir -p $BACKUP_DEST",
            "",
        ]
        for f in risky_files:
            lines.append(f"# cp -p '{f['path']}' $BACKUP_DEST/")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# UpdateChecker
# ---------------------------------------------------------------------------

class UpdateChecker:
    """Check for available software updates across package managers."""

    def check_brew(self) -> Dict:
        if PLATFORM != "Darwin":
            return {"available": False, "note": "Homebrew is macOS/Linux only"}
        out, ok = _run("brew outdated --verbose 2>/dev/null", timeout=30)
        return {"available": ok, "packages": out[:2000]}

    def check_npm_global(self) -> Dict:
        out, ok = _run("npm outdated -g --json 2>/dev/null", timeout=20)
        if ok and out:
            try:
                return {"available": True, "packages": json.loads(out)}
            except Exception:
                pass
        return {"available": ok, "packages": out[:500]}

    def check_pip_global(self) -> Dict:
        out, ok = _run(f"{sys.executable} -m pip list --outdated --format=json 2>/dev/null", timeout=25)
        if ok and out:
            try:
                return {"available": True, "packages": json.loads(out)}
            except Exception:
                pass
        return {"available": ok, "packages": out[:500]}

    def check_os_updates(self) -> Dict:
        if PLATFORM == "Darwin":
            out, ok = _run("softwareupdate -l 2>/dev/null", timeout=30)
            return {"platform": "macOS", "available": ok, "updates": out[:1500]}
        elif PLATFORM == "Linux":
            out, ok = _run("apt list --upgradable 2>/dev/null | head -30", timeout=20)
            return {"platform": "Linux/apt", "available": ok, "updates": out[:1500]}
        return {"available": False, "note": "OS update check not supported on this platform"}

    def full_check(self) -> Dict:
        return {
            "brew": self.check_brew(),
            "npm": self.check_npm_global(),
            "pip": self.check_pip_global(),
            "os": self.check_os_updates(),
        }

    def generate_update_script(self, results: Dict, security_first: bool = True) -> str:
        """Generate an ordered update script with safety notes."""
        lines = [
            "#!/bin/bash",
            "# TIMPS Update Manager — Prioritised Update Script",
            "# Review each section before running. Security updates are listed first.",
            "",
            "set -e  # exit on first error",
            "",
        ]
        # OS first (highest security impact)
        if results.get("os", {}).get("available"):
            if PLATFORM == "Darwin":
                lines += ["echo '=== macOS System Updates ==='", "# softwareupdate -ia", ""]
            elif PLATFORM == "Linux":
                lines += ["echo '=== OS Updates ==='", "# sudo apt update && sudo apt upgrade -y", ""]
        if results.get("brew", {}).get("available"):
            lines += ["echo '=== Homebrew Packages ==='", "# brew upgrade", ""]
        if results.get("pip", {}).get("available"):
            lines += ["echo '=== Python Packages ==='", "# pip install --upgrade pip", ""]
        if results.get("npm", {}).get("available"):
            lines += ["echo '=== Global NPM Packages ==='", "# npm update -g", ""]
        lines.append("echo 'Update complete.'")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# MediaScanner
# ---------------------------------------------------------------------------

class MediaScanner:
    """Scan and organize media files."""

    PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".raw", ".dng", ".gif", ".webp"}
    VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".flv", ".webm"}
    SCREENSHOT_EXTS = {".png", ".jpg"}

    def scan_media(self, path: str) -> Dict:
        """Count and size media files in a directory."""
        stats = {"photos": {"count": 0, "size_mb": 0.0}, "videos": {"count": 0, "size_mb": 0.0}, "total_size_mb": 0.0}
        try:
            for entry in Path(path).rglob("*"):
                try:
                    if not entry.is_file():
                        continue
                    size = entry.stat().st_size / 1024 / 1024
                    ext = entry.suffix.lower()
                    if ext in self.PHOTO_EXTS:
                        stats["photos"]["count"] += 1
                        stats["photos"]["size_mb"] = round(stats["photos"]["size_mb"] + size, 1)
                    elif ext in self.VIDEO_EXTS:
                        stats["videos"]["count"] += 1
                        stats["videos"]["size_mb"] = round(stats["videos"]["size_mb"] + size, 1)
                    stats["total_size_mb"] = round(stats["total_size_mb"] + size, 1)
                except (PermissionError, OSError):
                    pass
        except Exception:
            pass
        return stats

    def find_screenshots(self, path: str) -> List[Dict]:
        """Identify screenshot files by naming pattern."""
        screenshots = []
        patterns = [
            re.compile(r"Screen.?Shot", re.IGNORECASE),
            re.compile(r"Screenshot", re.IGNORECASE),
            re.compile(r"Capture", re.IGNORECASE),
            re.compile(r"^\d{4}-\d{2}-\d{2}", re.IGNORECASE),   # date-named
        ]
        try:
            for entry in Path(path).iterdir():
                if entry.is_file() and entry.suffix.lower() in self.SCREENSHOT_EXTS:
                    if any(p.search(entry.name) for p in patterns):
                        size_mb = entry.stat().st_size / 1024 / 1024
                        screenshots.append({"name": entry.name, "path": str(entry), "size_mb": round(size_mb, 2)})
        except Exception:
            pass
        return screenshots[:50]

    def suggest_rename_plan(self, photo_paths: List[str]) -> List[Dict]:
        """
        Suggest date-based rename plan using file modification time.
        Returns [{original, suggested}] — DRY RUN.
        """
        plan = []
        for p in photo_paths[:50]:
            try:
                entry = Path(p)
                mtime = entry.stat().st_mtime
                import datetime
                dt = datetime.datetime.fromtimestamp(mtime)
                new_name = f"{dt.strftime('%Y-%m-%d_%H%M%S')}{entry.suffix.lower()}"
                if entry.name != new_name:
                    plan.append({"original": str(entry), "suggested": str(entry.parent / new_name)})
            except Exception:
                pass
        return plan

    def get_large_videos(self, path: str, min_size_mb: float = 50.0) -> List[Dict]:
        """Find large video files that could be compressed."""
        results = []
        try:
            for entry in Path(path).rglob("*"):
                if entry.is_file() and entry.suffix.lower() in self.VIDEO_EXTS:
                    size_mb = entry.stat().st_size / 1024 / 1024
                    if size_mb >= min_size_mb:
                        results.append({"path": str(entry), "size_mb": round(size_mb, 1), "name": entry.name})
        except Exception:
            pass
        results.sort(key=lambda x: x["size_mb"], reverse=True)
        return results[:20]

    def generate_compress_script(self, large_videos: List[Dict]) -> str:
        """Generate ffmpeg compression commands (DRY RUN)."""
        lines = [
            "#!/bin/bash",
            "# TIMPS Media Librarian — Video Compression Script (DRY RUN)",
            "# Requires: brew install ffmpeg",
            "# Remove # prefix from lines you want to run",
            "",
        ]
        for v in large_videos:
            src = v["path"]
            dst = src.rsplit(".", 1)[0] + "_compressed.mp4"
            lines.append(f"# ffmpeg -i '{src}' -vcodec h264 -acodec aac -crf 28 '{dst}'")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ContextAnalyzer (for Context Switcher + Context Keeper)
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """Read active window/process state for focus management."""

    def get_active_windows(self) -> List[Dict]:
        """List currently open application windows."""
        if PLATFORM == "Darwin":
            out, ok = _run(
                "osascript -e 'tell application \"System Events\" to get the name of every process whose background only is false'"
            )
            if ok and out:
                apps = [a.strip() for a in out.split(",")]
                return [{"app": a} for a in apps if a]
        elif PLATFORM == "Linux":
            out, ok = _run("wmctrl -l 2>/dev/null | awk '{print $4}' | sort -u")
            if ok:
                return [{"app": line.strip()} for line in out.splitlines() if line.strip()]
        return []

    def get_open_browser_tabs_count(self) -> Dict:
        """Estimate open tabs by reading browser's session DB."""
        counts: Dict[str, Any] = {}
        if PLATFORM == "Darwin":
            # Chrome: count tabs in Last Session
            chrome_session = HOME / "Library/Application Support/Google/Chrome/Default/Sessions/Session_*"
            import glob
            for f in glob.glob(str(chrome_session)):
                try:
                    size = Path(f).stat().st_size
                    # Rough heuristic: each tab ~2KB
                    estimated = max(1, size // 2048)
                    counts["Chrome"] = {"estimated_tabs": estimated}
                    break
                except Exception:
                    pass
        return counts

    def get_git_working_context(self, cwd: Optional[str] = None) -> Dict:
        """Return current git branch and recent commits."""
        d = cwd or os.getcwd()
        branch, ok = _run(f"git -C '{d}' rev-parse --abbrev-ref HEAD 2>/dev/null")
        if not ok:
            return {"in_git_repo": False}
        recent, _ = _run(f"git -C '{d}' log --oneline -5 2>/dev/null")
        status, _ = _run(f"git -C '{d}' status --short 2>/dev/null | head -10")
        return {
            "in_git_repo": True,
            "branch": branch.strip(),
            "recent_commits": recent.strip(),
            "staged_changes": status.strip(),
        }

    def generate_focus_script(self, apps_to_close: List[str]) -> str:
        """Generate a DND + app-quit script (DRY RUN)."""
        lines = [
            "#!/bin/bash",
            "# TIMPS Context Switcher — Focus Mode Script (DRY RUN)",
            "",
            "# Enable Do Not Disturb",
        ]
        if PLATFORM == "Darwin":
            lines.append("# shortcuts run -n 'Focus'  # or manually set Focus in Control Center")
            for app in apps_to_close:
                lines.append(f"# osascript -e 'quit app \"{app}\"'")
        elif PLATFORM == "Linux":
            lines.append("# do-not-disturb on  # depends on desktop environment")
        return "\n".join(lines)
