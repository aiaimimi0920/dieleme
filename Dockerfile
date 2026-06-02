ARG PYTHON_BASE_IMAGE=python:3.10-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FAPAI_RUN_MODE=seed-collector \
    FAPAI_OUTPUT_DIR=/data/output/seed_collector \
    FAPAI_CDP_ENDPOINT=http://host.docker.internal:9223

WORKDIR /app

COPY requirements.txt ./
COPY vendor/wheels/ /tmp/wheels/
RUN if [ -d /tmp/wheels ] && [ "$(find /tmp/wheels -type f -name '*.whl' | head -n 1)" ]; then \
        pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

RUN mkdir -p /data/output /data/datas /data/jobs \
    && mkdir -p /app/output /app/jobs \
    && if [ ! -e /app/datas ]; then ln -s /data/datas /app/datas; fi

EXPOSE 8001

CMD ["python", "tools/docker_entrypoint.py"]
