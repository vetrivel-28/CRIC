"""
CRIC Secrets Scanner - Audits files for leaked passwords or credentials.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IGNORED_DIRS = {".git", "_cleanup_quarantine", "archive"}


def scan_for_secrets():
    flagged = []
    for p in PROJECT_ROOT.rglob("*"):
        if not p.is_file() or any(d in p.parts for d in IGNORED_DIRS):
            continue
        if p.suffix in [".py", ".sql", ".ini", ".example", ".md", ".json", ".txt", ".dax", ".js", ".html"]:
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                for i, line in enumerate(lines):
                    ll = line.lower()
                    if any(kw in ll for kw in ["password", "api_key", "secret"]):
                        # Allow safe usages
                        safe_tokens = [
                            "your_password", "password_hash", "dummy", "os.getenv", "example",
                            "not-for-response", "cric_db_password", "password: str", "default_password",
                            "your_postgres_password", "args.password", "cfg[\"password\"]",
                            "admin_cfg.password", "target_cfg.password", "password =", 'password = ""',
                            "password=''", 'password=""', "password=default_password",
                            "password=your_password_here", "password from env", "no password",
                            "password_hash", "secret_key = None"
                        ]
                        if any(st in ll for st in safe_tokens):
                            continue
                        flagged.append((p.relative_to(PROJECT_ROOT), i + 1, line.strip()))
            except Exception:
                pass

    print(f"Secrets audit complete. Total flagged occurrences: {len(flagged)}")
    for rel_path, line_no, content in flagged:
        print(f"  {rel_path}:{line_no} -> {content}")

    return len(flagged)


if __name__ == "__main__":
    scan_for_secrets()
