FROM python:3.11-slim
LABEL org.opencontainers.image.title="Rally"
LABEL org.opencontainers.image.description="Rally — tennis scorer. Phone-first match tracking and player rankings."
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 7860
# HF Spaces sets $PORT; default to 7860 locally.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
