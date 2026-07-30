import os
from flask import Flask, jsonify
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)

# --- APP-LEVEL METRICS (PRD §10.4) ---
# Exposes /metrics in Prometheus text format — request rate, error rate, and
# latency, bucketed by method/path/status. This is what makes the dashboard's
# HTTP panels work; nothing about them is Nexus-specific, they're standard
# prometheus-flask-exporter output. Metric names are genuinely
# library-specific (flask_http_request_total, not the generic
# http_requests_total some other libraries use) — verified against a running
# instance before the Grafana panels were written to match, not assumed.
metrics = PrometheusMetrics(app)

# --- THE "12-FACTOR" PATTERN ---
# We read configuration from the Environment.
# If K8s doesn't provide these variables, we use defaults ('v1', 'blue').
# This lets us change the color just by editing a YAML file later.
APP_VERSION = os.getenv("VERSION", "v1")
BG_COLOR = os.getenv("BG_COLOR", "green")

@app.route("/")
def home():
    # --- VISUAL FEEDBACK FOR GITOPS ---
    # We return a simple HTML page with a colored background.
    # When we demonstrate GitOps, we will change 'BG_COLOR' to 'green' in GitHub.
    # If the screen turns green automatically, we know the pipeline works.
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nexus App</title>
        <style>
            body {{
                background-color: {BG_COLOR};
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                font-family: Arial, sans-serif;
                margin: 0;
            }}
            .container {{ text-align: center; }}
            .version {{ font-size: 2em; font-weight: bold; }}
            .status {{ margin-top: 10px; opacity: 0.8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="version">Nexus App: {APP_VERSION}</div>
            <div class="status">Running on Kubernetes</div>
        </div>
    </body>
    </html>
    """

@app.route("/healthz")
def health():
    # --- THE SELF-HEALING HOOK ---
    # Kubernetes will ping this URL (e.g., every 10 seconds).
    # If we return 200, K8s assumes we are alive.
    # If we return 500 or don't answer, K8s KILLS this pod and starts a new one.
    return jsonify({"status": "healthy"}), 200

@app.route("/version")
def version():
    # --- CANARY DEPLOYMENT HOOK ---
    # Automated tools (like Argo Rollouts) check this endpoint
    # to see if the new version is actually live yet.
    return jsonify({"version": APP_VERSION}), 200

@app.route("/boom")
def boom():
    # --- DEMO/TESTING HELPER, NOT A REAL FEATURE ---
    # Deliberately returns a 500 so there's something for the dashboard's
    # HTTP Error Rate panel (PRD §10.4) to actually show. Real apps wouldn't
    # ship an endpoint whose whole job is to fail.
    return jsonify({"error": "deliberate failure for the error-rate panel"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)