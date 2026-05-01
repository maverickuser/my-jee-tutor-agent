FROM public.ecr.aws/lambda/python:3.11

# Install Poetry only for build-time dependency resolution, then install directly
# into the Lambda task root so the runtime image stays simple.
RUN pip install --no-cache-dir poetry==1.8.3

COPY pyproject.toml ./
RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi --no-root --directory /var/task

COPY src/ "${LAMBDA_TASK_ROOT}/"

CMD ["main.lambda_handler"]
