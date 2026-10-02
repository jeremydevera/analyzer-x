#!/usr/bin/env bash
# One-shot setup for the auto-trader on a fresh Ubuntu 24.04 VPS.
# Run as root (or with sudo) from inside the uploaded repo directory:
#
#   bash deploy/setup_vps.sh
#
# What it does: installs Python, builds the venv, installs the runner's
# systemd unit, and starts it. (The Streamlit dashboard unit went with app.py
# on Oct 02, 2026; the web UI is webapp/ behind tradingagents.api.) DRY RUN by default — arming
# requires editing the environment line in the runner unit, on purpose.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"

echo "== installing system packages =="
apt-get update -qq
apt-get install -y -qq python3.12-venv python3-pip > /dev/null

echo "== building the virtualenv =="
cd "$REPO_DIR"
if [ ! -d .venv ]; then
    python3.12 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "== installing systemd unit =="
sed -e "s|__REPO__|$REPO_DIR|g" -e "s|__USER__|$RUN_USER|g" \
    deploy/autotrader.service > /etc/systemd/system/autotrader.service
systemctl daemon-reload
systemctl enable --now autotrader.service

echo
echo "Done. Check:"
echo "  systemctl status autotrader     # the trading loop"
echo "  journalctl -u autotrader -f     # live logs"
echo
echo "MEXC keys: run this once as $RUN_USER, then restart the runner —"
echo "  .venv/bin/python -c 'from tradingagents.dataflows import mexc_credentials as c; import getpass; c.save(getpass.getpass(\"key: \"), getpass.getpass(\"secret: \"))'"
echo
echo "Live/dry follows the saved Auto Trade / Dry run settings."
