#!/usr/bin/env bash
# Install the tracker as a user service. Run this only on the target Linux PC.
set -euo pipefail

project_root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
python_bin="${2:-$project_root/.venv/bin/python}"
template="$project_root/deploy/systemd/personal-os-tracker.service.template"
target_dir="$HOME/.config/systemd/user"
target="$target_dir/personal-os-tracker.service"

if [[ ! -x "$python_bin" ]]; then
  echo "Python executable not found: $python_bin" >&2
  exit 1
fi

mkdir -p "$target_dir"
sed "s|{{PROJECT_ROOT}}|$project_root|g; s|{{PYTHON}}|$python_bin|g" "$template" > "$target"
systemctl --user daemon-reload
systemctl --user enable --now personal-os-tracker.service
echo "Installed and started personal-os-tracker.service"
