FROM python:3.12-slim
WORKDIR /app
COPY app ./app
COPY data/sample_cache ./data/sample_cache
COPY run.py ./
ENV SAMPLE_MODE=true PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "run.py", "--serve"]
