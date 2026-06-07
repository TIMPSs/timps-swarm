#!/usr/bin/env bash
# Auto-generated kubectl runbook for ns=default
# Review each command before executing.
set -euo pipefail

1. **Check KUBECONFIG environment variable:**
   `echo $KUBECONFIG`
   If this is empty or points to a non-existent file, set it to the correct path of your kubeconfig file (e.g., `export KUBECONFIG=~/.kube/config`).

2. **Inspect your kubeconfig file:**
   `cat ~/.kube/config` (or the path from step 1)
   Look for the `clusters` section and verify the `server` address. It should typically be an IP address or hostname, not `localhost:8080` unless you are running a local development cluster like Minikube or Kind.

3. **Test the current context:**
   `kubectl config current-context`
   `kubectl config get-contexts`
   Ensure you are using the correct context for your cluster.

4. **Try resetting the context (if unsure):**
   `kubectl config use-context <your-cluster-context-name>`
   (Replace `<your-cluster-context-name>` with the correct context from `kubectl config get-contexts`)

5. **Verify network reachability to the API server:**
   From the output of `kubectl config view --minify`, identify the `server` address (e.g., `https://192.168.1.100:6443`).
   Try to ping or curl this address (adjust port if necessary):
   `ping <api-server-ip-or-hostname>`
   `curl -k <api-server-url>` (e.g., `curl -k https://192.168.1.100:6443/version`)
   If ping fails, it's a network issue. If curl fails, it could be a firewall blocking the port or the API server is not running.

6. **If using a managed Kubernetes service (EKS, GKE, AKS):**
   Check the cloud provider's health dashboard for your cluster. Ensure the control plane is healthy and reachable. You may need to re-authenticate your `kubectl` client using the cloud provider's CLI tools (e.g., `aws eks update-kubeconfig`, `gcloud container clusters get-credentials`, `az aks get-credentials`).

7. **If direct access to control plane node is available:**
   SSH into a control plane node and check the status of the `kube-apiserver` process. For example:
   `sudo systemctl status kube-apiserver` (for systemd)
   `sudo docker ps | grep kube-apiserver` (if running as a container)
   Review the logs for the API server for any errors: `sudo journalctl -u kube-apiserver` or check container logs.
