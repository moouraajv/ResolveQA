# syntax=docker/dockerfile:1
# ResolveQA Ephemeral Demo Backend
# Intermediate runtime packaging for Intake & Simulated Chat HTTP surface.
# Note: In-memory ephemeral storage only; no durable persistence.
# Full hackathon agent reproduction / fix / PR pipeline is planned for future stages.

FROM python:3.11-slim

# Prevent python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    RESOLVEQA_HOST=0.0.0.0 \
    RESOLVEQA_PORT=8080

# Create non-privileged user and application directory
RUN groupadd -g 10001 resolveqa && \
    useradd -u 10001 -g resolveqa -s /sbin/nologin -d /app resolveqa

WORKDIR /app

# Copy application source code and entrypoint scripts
COPY --chown=resolveqa:resolveqa src/ /app/src/
COPY --chown=resolveqa:resolveqa scripts/ /app/scripts/

# Switch to non-root user
USER resolveqa

EXPOSE 8080

# Health check using python standard library (zero external curl/wget dependencies)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').getcode() == 200 else 1)"

ENTRYPOINT ["python", "scripts/run_server.py"]
