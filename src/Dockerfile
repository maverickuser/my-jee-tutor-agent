FROM python:3.11-slim

ARG APP_GIT_SHA=unknown
ENV PYTHONUNBUFFERED=1
ENV JEE_TUTOR_GIT_SHA=$APP_GIT_SHA
ENV OTEL_SDK_DISABLED=true
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        lmodern \
        pandoc \
        texlive-fonts-recommended \
        texlive-latex-extra \
        texlive-latex-recommended \
        texlive-science \
        texlive-xetex && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==1.8.3

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi --no-root

COPY src/ /app/

EXPOSE 8080
CMD ["python", "agentcore_app.py"]
