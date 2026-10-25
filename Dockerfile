FROM python:3.12-slim
COPY --from=node:24-slim /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY app ./app
COPY config ./config
COPY data/sample_cache ./data/sample_cache
COPY memory ./memory
COPY vendor ./vendor
COPY run.py ./
ENV SAMPLE_MODE=true PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "run.py", "--serve"]
