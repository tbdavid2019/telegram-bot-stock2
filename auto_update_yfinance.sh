#!/bin/bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_dir"

lock_file="$repo_dir/.auto_update_yfinance.lock"
if ! mkdir "$lock_file" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$lock_file"' EXIT

package_name="yfinance"
requirements_file="$repo_dir/requirements.txt"
branch="$(git branch --show-current)"
branch="${branch:-master}"

if ! git diff --quiet -- "$requirements_file" || ! git diff --cached --quiet -- "$requirements_file"; then
  echo "requirements.txt has local changes; aborting."
  exit 1
fi

if [[ "${YFINANCE_SKIP_PULL:-0}" != "1" ]]; then
  git pull --rebase --autostash origin "$branch"
fi

fetch_latest_version() {
  if [[ -n "${YFINANCE_LATEST:-}" ]]; then
    printf '%s\n' "$YFINANCE_LATEST"
    return
  fi

  curl -fsS "https://pypi.org/pypi/${package_name}/json" | \
    python3 -c 'import json, sys; print(json.load(sys.stdin)["info"]["version"])'
}

read_current_version() {
  python3 - "$requirements_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
for line in path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line.startswith("yfinance=="):
        print(line.split("==", 1)[1])
        break
PY
}

latest_version="$(fetch_latest_version)"
current_version="$(read_current_version || true)"

if [[ -z "$current_version" ]]; then
  current_version="unversioned"
fi

echo "Current ${package_name}: ${current_version}"
echo "Latest ${package_name}: ${latest_version}"

if [[ "$current_version" == "$latest_version" ]]; then
  echo "Already up to date."
  exit 0
fi

python3 - "$requirements_file" "$latest_version" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
latest_version = sys.argv[2]
lines = path.read_text(encoding='utf-8').splitlines()
updated = []
replaced = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("yfinance"):
        updated.append(f"yfinance=={latest_version}")
        replaced = True
    else:
        updated.append(line)

if not replaced:
    updated.append(f"yfinance=={latest_version}")

path.write_text("\n".join(updated) + "\n", encoding='utf-8')
PY

git add requirements.txt
git commit -m "chore: bump yfinance to ${latest_version}"

if [[ "${YFINANCE_SKIP_PUSH:-0}" != "1" ]]; then
  if ! git push origin "$branch"; then
    echo "Warning: git push failed; kept local commit on this host."
  fi
fi

if [[ "${YFINANCE_SKIP_DEPLOY:-0}" != "1" ]]; then
  echo "Building and deploying updated image..."
  bash "$repo_dir/deploy.sh"
fi
