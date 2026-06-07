#!/usr/bin/env bash
# Auto-generated kubectl runbook for ns=default
# Review each command before executing.
set -euo pipefail

1. **Verify KUBECONFIG environment variable:** Run `echo $KUBECONFIG`. If it's set, ensure it points to a valid kubeconfig file. If not set, kubectl defaults to `~/.kube/config`.
2. **Inspect default kubeconfig:** Run `ls -l ~/.kube/config`. Ensure the file exists and has appropriate permissions.
3. **View current kubectl configuration:** Run `kubectl config view`. Look for the `server:` address under `clusters:`. This is the address kubectl is *supposed* to connect to. Compare it with `localhost:8080` from the error.
4. **Check current context:** Run `kubectl config get-contexts`. Ensure the current context is set to the intended cluster.
5. **If using a local cluster (e.g., Minikube, Docker Desktop):**
   - Ensure the cluster is running: `minikube status` or check Docker Desktop status.
   - Re-establish context: `minikube update-context` or restart Docker Desktop Kubernetes.
   - Try `minikube kubectl -- get pods` to bypass your local kubectl config.
6. **If using a remote cluster:**
   - **Obtain correct kubeconfig:** Download or generate a new kubeconfig file from your cloud provider (AWS EKS, GCP GKE, Azure AKS, etc.) or cluster administrator.
   - **Replace existing kubeconfig:** Back up your old `~/.kube/config` (e.g., `mv ~/.kube/config ~/.kube/config.bak`) and place the new, correct kubeconfig file at `~/.kube/config`.
   - **Verify connectivity:** Run `kubectl get nodes` to confirm the connection.
7. **Network connectivity check:** If the `server:` address in your kubeconfig is correct but still failing, try `ping <API_SERVER_IP_OR_HOSTNAME>` and `telnet <API_SERVER_IP_OR_HOSTNAME> <API_SERVER_PORT>` (replace with actual values from `kubectl config view`) to check network reachability from your machine to the API server.
