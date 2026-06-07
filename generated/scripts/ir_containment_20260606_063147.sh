#!/usr/bin/env bash
# IR containment script — generated 20260606_063147
# Classification: unknown  Severity: sev3
# *** REVIEW EVERY LINE BEFORE EXECUTING — DRY-RUN BY DEFAULT ***
set -euo pipefail
DRY_RUN=${DRY_RUN:-1}
run() { if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else eval "$@"; fi; }

# Get detailed network connection information including process IDs (PIDs). (risk=low, reversible=True)
run "sudo netstat -tunap"

# List open files and network connections by processes to identify which process owns a suspicious connection. (risk=low, reversible=True)
run "sudo lsof -i -P"

# Capture a limited number of network packets for forensic analysis (replace 'eth0' with actual interface if known). (risk=low, reversible=True)
run "sudo tcpdump -i any -s 0 -w /tmp/suspicious_traffic.pcap -c 10000"

# Temporarily block outbound traffic to a specific suspicious IP address using iptables. (Requires root). (risk=medium, reversible=True)
run "sudo iptables -A OUTPUT -d <SUSPICIOUS_IP_ADDRESS> -j DROP"

# Revert the iptables block for a specific IP address. (Requires root). (risk=low, reversible=True)
run "sudo iptables -D OUTPUT -d <SUSPICIOUS_IP_ADDRESS> -j DROP"

# Stop a specific service if it's identified as malicious or compromised. (Requires root). (risk=high, reversible=True)
run "sudo systemctl stop <SERVICE_NAME>"

# Start a previously stopped service. (Requires root). (risk=low, reversible=True)
run "sudo systemctl start <SERVICE_NAME>"
