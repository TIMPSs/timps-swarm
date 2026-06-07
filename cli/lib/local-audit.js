/**
 * local-audit.js
 * ==============
 * Standalone security scanner — no backend, no API key required.
 *
 * Runs three checks:
 *   1. CVE scan  — reads manifests, queries OSV.dev (free, no auth)
 *   2. Secrets   — regex scan across source files
 *   3. SAST      — static analysis patterns for Python + JS/TS
 */

import { readFileSync, existsSync, readdirSync, statSync } from "fs";
import { join, extname, relative, resolve } from "path";

// ── Manifest Parsers ─────────────────────────────────────────────────────────

function parseRequirementsTxt(content) {
  const pkgs = [];
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || line.startsWith("-r") || line.startsWith("--")) continue;
    const stripped = line.replace(/\[.*?\]/, ""); // strip extras: pkg[extra]
    const m = stripped.match(/^([A-Za-z0-9_\-.]+)\s*(?:[=~><^!]=?\s*([\d][^\s,;#]*))?/);
    if (m) {
      pkgs.push({
        name: m[1].toLowerCase().replace(/_/g, "-"),
        version: m[2] ? m[2].split(",")[0].trim() : null,
        ecosystem: "PyPI",
      });
    }
  }
  return pkgs;
}

function parsePackageJson(content) {
  try {
    const pkg = JSON.parse(content);
    const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
    return Object.entries(deps).map(([name, ver]) => ({
      name,
      version: ver.replace(/^[^0-9]*/, "").split(/\s+/)[0] || null,
      ecosystem: "npm",
    }));
  } catch {
    return [];
  }
}

function parseGoMod(content) {
  const pkgs = [];
  for (const line of content.split("\n")) {
    const m = line.trim().match(/^([^\s/]+\/[^\s]+)\s+v([\d.][^\s]*)/);
    if (m) pkgs.push({ name: m[1], version: m[2], ecosystem: "Go" });
  }
  return pkgs;
}

function parseCargoToml(content) {
  const pkgs = [];
  for (const line of content.split("\n")) {
    const m = line.match(/^\s*([a-z0-9_-]+)\s*=\s*"([0-9][^"]+)"/);
    if (m) pkgs.push({ name: m[1], version: m[2], ecosystem: "crates.io" });
  }
  return pkgs;
}

const MANIFEST_PARSERS = {
  "requirements.txt":     parseRequirementsTxt,
  "requirements-dev.txt": parseRequirementsTxt,
  "requirements-test.txt":parseRequirementsTxt,
  "Pipfile":              parseRequirementsTxt,
  "package.json":         parsePackageJson,
  "go.mod":               parseGoMod,
  "Cargo.toml":           parseCargoToml,
};

// ── CVE Scanner via OSV.dev ──────────────────────────────────────────────────

const SUPPORTED_ECOSYSTEMS = new Set(["PyPI", "npm", "Go", "crates.io", "Hex", "Maven", "NuGet", "RubyGems"]);

export async function queryOSV(packages) {
  const versioned = packages.filter(p => p.version && SUPPORTED_ECOSYSTEMS.has(p.ecosystem));
  if (!versioned.length) return [];

  const CHUNK = 999; // OSV batch limit
  let { default: fetch } = await import("node-fetch").catch(() => ({ default: null }));
  if (!fetch) return [];

  // Step 1: querybatch → just gets vuln IDs per package
  const vulnIdsByPkg = new Map(); // pkg index → [id, ...]
  for (let i = 0; i < versioned.length; i += CHUNK) {
    const chunk = versioned.slice(i, i + CHUNK);
    try {
      const resp = await fetch("https://api.osv.dev/v1/querybatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ queries: chunk.map(p => ({ package: { name: p.name, ecosystem: p.ecosystem }, version: p.version })) }),
        signal: AbortSignal.timeout(20000),
      });
      if (!resp.ok) continue;
      const data = await resp.json();
      (data.results || []).forEach((result, idx) => {
        const ids = (result.vulns || []).map(v => v.id);
        if (ids.length > 0) vulnIdsByPkg.set(i + idx, ids);
      });
    } catch { /* network unavailable */ }
  }

  if (vulnIdsByPkg.size === 0) return [];

  // Step 2: Fetch full details for each unique vuln ID in parallel
  const uniqueIds = [...new Set([...vulnIdsByPkg.values()].flat())];
  const vulnDetails = new Map();

  await Promise.all(uniqueIds.map(async (id) => {
    try {
      const resp = await fetch(`https://api.osv.dev/v1/vulns/${id}`, {
        signal: AbortSignal.timeout(10000),
      });
      if (resp.ok) {
        const v = await resp.json();
        vulnDetails.set(id, v);
      }
    } catch { /* skip */ }
  }));

  // Step 3: Build result list, deduplicating by canonical CVE ID or GHSA ID
  const allVulns = [];
  const seenKey = new Set(); // dedup by "package@version::cve-or-id"
  for (const [pkgIdx, ids] of vulnIdsByPkg) {
    const pkg = versioned[pkgIdx];
    for (const id of ids) {
      const vuln = vulnDetails.get(id);
      const cves = vuln ? (vuln.aliases || []).filter(a => a.startsWith("CVE-")).slice(0, 3) : [];
      const dedupId = `${pkg.name}@${pkg.version}::${cves[0] || id}`;
      if (seenKey.has(dedupId)) continue;
      seenKey.add(dedupId);
      allVulns.push({
        package: pkg.name,
        version: pkg.version,
        ecosystem: pkg.ecosystem,
        id,
        summary: vuln ? (vuln.summary || "").slice(0, 140) : "",
        severity: vuln ? classifySeverity(vuln) : "UNKNOWN",
        fixed: vuln ? getFixed(vuln) : null,
        cves,
      });
    }
  }
  return allVulns;
}

function classifySeverity(vuln) {
  // 1. Try numeric CVSS score in severity array
  for (const s of vuln.severity || []) {
    const score = s.score;
    if (typeof score === "number") {
      if (score >= 9.0) return "CRITICAL";
      if (score >= 7.0) return "HIGH";
      if (score >= 4.0) return "MEDIUM";
      return "LOW";
    }
    // CVSS v3 vector string — extract base score from CVSS:3.x/...
    // e.g. "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    if (typeof score === "string" && score.startsWith("CVSS:")) {
      // Parse C/I/A impact values for a rough classification
      const crit = /[CIA]:C/.test(score);
      const high = /[CIA]:H/.test(score);
      if (crit) return "CRITICAL";
      if (high) return "HIGH";
      return "MEDIUM";
    }
  }
  // 2. GitHub Advisory database_specific.severity
  const ghSev = vuln.database_specific?.severity?.toUpperCase();
  if (["CRITICAL", "HIGH", "MEDIUM", "LOW"].includes(ghSev)) return ghSev;
  // 3. NVD ecosystem_specific
  const nvdSev = vuln.ecosystem_specific?.severity?.toUpperCase?.();
  if (["CRITICAL", "HIGH", "MEDIUM", "LOW"].includes(nvdSev)) return nvdSev;
  return "UNKNOWN";
}

function getFixed(vuln) {
  for (const affected of vuln.affected || []) {
    for (const range of affected.ranges || []) {
      for (const ev of range.events || []) {
        if (ev.fixed) return ev.fixed;
      }
    }
  }
  return null;
}

// ── Secrets Detection ────────────────────────────────────────────────────────

const SECRET_PATTERNS = [
  { name: "AWS Access Key",    re: /AKIA[0-9A-Z]{16}/ },
  { name: "AWS Secret Key",    re: /(?:aws[_-]?secret)[_-]?(?:access[_-]?)?key["'\s]*[:=]["'\s]*[A-Za-z0-9/+=]{40}/i },
  { name: "GitHub Token",      re: /gh[psoua]_[A-Za-z0-9_]{36,255}/ },
  { name: "GitLab Token",      re: /glpat-[A-Za-z0-9_-]{20,}/ },
  { name: "Stripe Secret Key", re: /sk_live_[0-9a-zA-Z]{24,}/ },
  { name: "Slack Token",       re: /xox[baprs]-(?:[0-9]{12}-)+[0-9a-zA-Z]{24,}/ },
  { name: "Google API Key",    re: /AIza[0-9A-Za-z_-]{35}/ },
  { name: "Private Key Block", re: /-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----/ },
  { name: "Bearer JWT",        re: /[Bb]earer\s+eyJ[A-Za-z0-9_-]{20,}/ },
  { name: "Generic API Key",   re: /(?:api[_-]?key|apikey)["'\s]*[:=]["'\s]*[A-Za-z0-9_\-]{20,}/i },
  { name: "Database URL",      re: /(?:mysql|postgresql|postgres|mongodb|redis):\/\/[^:\s]+:[^@\s]+@/ },
  { name: "Hardcoded Password",re: /(?:password|passwd|pwd)\s*=\s*["'][^"']{8,}["']/i },
];

const IGNORE_DIRS = new Set([
  "node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv",
  ".next", "out", "coverage", ".pytest_cache", ".mypy_cache", "target",
  "vendor", ".cargo", "pkg", ".gradle", ".idea", ".tox",
]);

const SOURCE_EXTS = new Set([
  ".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".java", ".cs",
  ".php", ".sh", ".bash", ".zsh", ".env", ".yml", ".yaml", ".json",
  ".toml", ".ini", ".cfg", ".conf", ".tf", ".hcl",
]);

function* walkFiles(dir) {
  try {
    for (const entry of readdirSync(dir)) {
      if (IGNORE_DIRS.has(entry)) continue;
      const full = join(dir, entry);
      try {
        const st = statSync(full);
        if (st.isDirectory()) yield* walkFiles(full);
        else if (SOURCE_EXTS.has(extname(entry).toLowerCase()) || entry.toLowerCase().startsWith(".env")) {
          yield full;
        }
      } catch { /* skip unreadable entries */ }
    }
  } catch { /* skip unreadable dir */ }
}

const PLACEHOLDER_RE = /(?:example|placeholder|your[_-]?key|dummy|fake|test|todo|<[A-Z_]+>|REPLACE|INSERT|FILL|CHANGE)/i;

function scanSecrets(absDir) {
  const findings = [];
  for (const filePath of walkFiles(absDir)) {
    try {
      if (statSync(filePath).size > 500_000) continue; // skip large/binary files
    } catch { continue; }

    let content;
    try { content = readFileSync(filePath, "utf8"); } catch { continue; }

    const lines = content.split("\n");
    for (const { name, re } of SECRET_PATTERNS) {
      for (let i = 0; i < lines.length; i++) {
        if (!re.test(lines[i])) continue;
        const snippet = lines[i].trim();
        if (PLACEHOLDER_RE.test(snippet)) continue; // ignore obvious placeholders
        findings.push({
          type: name,
          file: relative(absDir, filePath),
          line: i + 1,
          snippet: snippet.slice(0, 80) + (snippet.length > 80 ? "…" : ""),
        });
      }
    }
  }
  return findings;
}

// ── SAST ─────────────────────────────────────────────────────────────────────

const SAST_RULES = [
  // Python
  { id: "PY001", lang: "py", sev: "HIGH",   re: /\beval\s*\(/,                       name: "eval() usage",              desc: "eval() executes arbitrary code. Avoid passing unsanitized input." },
  { id: "PY002", lang: "py", sev: "HIGH",   re: /\bexec\s*\(/,                       name: "exec() usage",              desc: "exec() executes arbitrary code." },
  { id: "PY003", lang: "py", sev: "HIGH",   re: /\bpickle\.loads?\s*\(/,             name: "pickle deserialization",    desc: "Deserializing untrusted pickle data can lead to Remote Code Execution." },
  { id: "PY004", lang: "py", sev: "HIGH",   re: /shell\s*=\s*True/,                  name: "subprocess shell=True",     desc: "shell=True enables command injection. Pass args as a list instead." },
  { id: "PY005", lang: "py", sev: "MEDIUM", re: /\byaml\.load\s*\(/,                 name: "yaml.load() unsafe",        desc: "Use yaml.safe_load() to prevent arbitrary object instantiation." },
  { id: "PY006", lang: "py", sev: "HIGH",   re: /\.execute\s*\(\s*(?:f"|f'|"[^"]*%|'[^']*%)/, name: "SQL injection risk", desc: "Build queries with parameterized statements, not string formatting." },
  { id: "PY007", lang: "py", sev: "MEDIUM", re: /\bhashlib\.md5\s*\(/,               name: "MD5 hash",                  desc: "MD5 is cryptographically broken. Use SHA-256 or better." },
  { id: "PY008", lang: "py", sev: "MEDIUM", re: /\brandom\.(?:random|randint|choice)\s*\(/, name: "Insecure randomness", desc: "random module is not cryptographically secure. Use secrets module." },
  // JavaScript / TypeScript
  { id: "JS001", lang: "js", sev: "HIGH",   re: /\beval\s*\(/,                       name: "eval() usage",              desc: "eval() executes arbitrary code." },
  { id: "JS002", lang: "js", sev: "MEDIUM", re: /\.innerHTML\s*=/,                   name: "innerHTML assignment",      desc: "innerHTML can introduce XSS. Use textContent or a sanitizer." },
  { id: "JS003", lang: "js", sev: "MEDIUM", re: /dangerouslySetInnerHTML/,           name: "dangerouslySetInnerHTML",   desc: "Ensure HTML is sanitized (e.g. DOMPurify) before use." },
  { id: "JS004", lang: "js", sev: "HIGH",   re: /new\s+Function\s*\(/,               name: "Function constructor",      desc: "new Function() is equivalent to eval()." },
  { id: "JS005", lang: "js", sev: "LOW",    re: /Math\.random\s*\(\s*\)/,            name: "Insecure randomness",       desc: "Math.random() is not cryptographically secure. Use crypto.getRandomValues()." },
  { id: "JS006", lang: "js", sev: "MEDIUM", re: /document\.write\s*\(/,              name: "document.write()",          desc: "document.write() can overwrite the page and introduce XSS." },
];

function runSAST(absDir) {
  const findings = [];
  for (const filePath of walkFiles(absDir)) {
    const ext = extname(filePath).toLowerCase();
    const isPy = ext === ".py";
    const isJs = [".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"].includes(ext);
    if (!isPy && !isJs) continue;
    const lang = isPy ? "py" : "js";

    let content;
    try {
      if (statSync(filePath).size > 500_000) continue;
      content = readFileSync(filePath, "utf8");
    } catch { continue; }

    const lines = content.split("\n");
    for (const rule of SAST_RULES) {
      if (rule.lang !== lang) continue;
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (isPy && line.trimStart().startsWith("#")) continue;
        if (isJs && line.trimStart().startsWith("//")) continue;
        if (rule.re.test(line)) {
          findings.push({
            rule: rule.id,
            name: rule.name,
            severity: rule.sev,
            file: relative(absDir, filePath),
            line: i + 1,
            description: rule.desc,
          });
        }
      }
    }
  }
  return findings;
}

// ── Score ────────────────────────────────────────────────────────────────────

function calcScore(cves, secrets, sast) {
  let score = 100;
  for (const c of cves) {
    score -= c.severity === "CRITICAL" ? 20 : c.severity === "HIGH" ? 10 : c.severity === "MEDIUM" ? 3 : 1;
  }
  for (const _ of secrets) score -= 15;
  for (const s of sast) {
    score -= s.severity === "HIGH" ? 5 : s.severity === "MEDIUM" ? 2 : 1;
  }
  return Math.max(0, Math.min(100, Math.round(score)));
}

// ── Main Export ───────────────────────────────────────────────────────────────

export async function auditDirectory(dir) {
  const absDir = resolve(dir);
  if (!existsSync(absDir)) throw new Error(`Path not found: ${dir}`);

  // Find and parse manifest files
  const manifests = [];
  const packages = [];
  for (const [filename, parser] of Object.entries(MANIFEST_PARSERS)) {
    const full = join(absDir, filename);
    if (existsSync(full)) {
      try {
        const pkgs = parser(readFileSync(full, "utf8"));
        manifests.push(filename);
        packages.push(...pkgs);
      } catch { /* ignore parse errors */ }
    }
  }

  // Count source files
  let fileCount = 0;
  for (const _ of walkFiles(absDir)) fileCount++;

  // Run all three checks in parallel
  const [cves, secrets, sast] = await Promise.all([
    queryOSV(packages),
    Promise.resolve(scanSecrets(absDir)),
    Promise.resolve(runSAST(absDir)),
  ]);

  return {
    target: absDir,
    manifests,
    packageCount: packages.length,
    fileCount,
    cves,
    secrets,
    sast,
    score: calcScore(cves, secrets, sast),
  };
}
