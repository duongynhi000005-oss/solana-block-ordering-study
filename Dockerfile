FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODE=dry-run \
    MAX_SPEND_LAMPORTS=50000000 \
    SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/ /app/src/
COPY data/ /app/data/
COPY tests/ /app/tests/
COPY REPORT.md /app/REPORT.md
COPY README.md /app/README.md

ENTRYPOINT ["python", "-m", "src.cli"]
CMD ["--mode", "dry-run", "--verify-raw-data"]
