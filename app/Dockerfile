FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# CHANGED: Expose port 5050
EXPOSE 5050

CMD ["python", "app.py"]