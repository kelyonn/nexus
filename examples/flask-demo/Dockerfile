FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# CHANGED: Expose port 5050
EXPOSE 5050

# Not applied to the actual example: ../nexus.yaml pins the pre-built
# kelyonnnn17/nexus-app:v1 on Docker Hub, which predates this Dockerfile
# change and still runs as root. That's also why nexus.yaml leaves
# app.security.runAsNonRoot at its schema default (false) rather than
# opting in — see SecurityConfig's docstring in nexus_cli/core/config.py.
# `nexus init` sets runAsNonRoot: true for every newly generated config;
# this line documents what a real non-root build for this app looks like,
# for anyone who builds their own image from this Dockerfile instead of
# using :v1 as-is.
USER 10001

CMD ["python", "app.py"]