# MolDock Studio — Dockerfile for the scientific backend
#
# The backend needs AutoDock Vina, RDKit, gemmi and Meeko. Vina publishes
# manylinux **x86_64** wheels only, so a linux/arm64 image cannot install it.
# Two supported configurations (see docker-compose.yml):
#
#   MOLDOCK_PLATFORM=linux/amd64 MOLDOCK_INSTALL_VINA=1   -> full docking stack
#   MOLDOCK_PLATFORM=linux/arm64 MOLDOCK_INSTALL_VINA=0   -> everything except Vina
#
# The health endpoint reports exactly which scientific tools are present, so a
# missing Vina is surfaced to the user instead of failing later at runtime.

FROM python:3.12-slim

ARG INSTALL_VINA=0
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MOLDOCK_DATA_DIR=/data \
    MOLDOCK_SCIENTIFIC_BACKEND_MODE=docker

WORKDIR /app

# libgomp1: OpenMP runtime used by RDKit/NumPy wheels.
# libgl1 + libglib2.0-0: needed by RDKit's drawing backends.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the dependency manifest first for layer caching.
COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests

# Base scientific stack.
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" "pydantic>=2.9,<3" \
        "pydantic-settings>=2.5,<3" "sqlalchemy>=2.0.35,<3" "alembic>=1.13,<2" \
        "python-multipart>=0.0.12" "httpx>=0.27,<1" "numpy>=1.26,<3" \
        "scipy>=1.13,<2" "scikit-image>=0.24,<1" "gemmi>=0.6.7" \
        "rdkit>=2024.9" "biopython>=1.84" "pandas>=2.2,<3" "meeko>=0.6"

# Optional: AutoDock Vina (x86_64 wheels only).
RUN if [ "$INSTALL_VINA" = "1" ]; then \
        python -m pip install "vina>=1.2.7" && python -c "import vina; print('vina', vina.__version__ if hasattr(vina,'__version__') else 'ok')"; \
    else \
        echo "Skipping AutoDock Vina (INSTALL_VINA=$INSTALL_VINA): docking disabled for this image."; \
    fi

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/api/health', timeout=4).status_code == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
