# syntax=docker/dockerfile:1.7
# Image icemaint : Python 3.14 slim (épinglée) + JRE 17 + PySpark 4.1 + Iceberg 1.12
# Construction : ./scripts/build-image.sh (dépôts Nexus CNAV par défaut)

ARG PYTHON_IMAGE=python:3.14-slim-bookworm@sha256:adb6bdfbcc7c744c3b1a05976136555e2d82b7df01ac3efe71737d7f95ef0f2d
ARG JRE_IMAGE=eclipse-temurin:17-jre

# ---------------------------------------------------------------- JRE 17 (copié tel quel, sans apt)
FROM ${JRE_IMAGE} AS jre

# ---------------------------------------------------------------- environnement Python (résolu via le Nexus PyPI)
FROM ${PYTHON_IMAGE} AS build
ARG PIP_INDEX_URL=https://python.artifact.ul.cnavts.fr/repository/pypi-group-repository/simple
ARG PIP_TRUSTED_HOST=python.artifact.ul.cnavts.fr
ARG UV_VERSION=0.13.9
ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_DEFAULT_INDEX=${PIP_INDEX_URL} \
    UV_INSECURE_HOST=${PIP_TRUSTED_HOST}
RUN pip install --no-cache-dir --trusted-host "${PIP_TRUSTED_HOST}" --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"
WORKDIR /opt/icemaint
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project
COPY src ./src
RUN uv sync --no-dev --no-editable

# ---------------------------------------------------------------- image finale
FROM ${PYTHON_IMAGE}
ARG MAVEN_REPO=https://maven.artifact.ul.cnavts.fr/repository/group
ARG ICEBERG_VERSION=1.12.0
ARG SPARK_JARS=/opt/icemaint/.venv/lib/python3.14/site-packages/pyspark/jars

ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/icemaint/.venv/bin:/opt/java/openjdk/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    AWS_REGION=us-east-1

COPY --from=jre /opt/java/openjdk /opt/java/openjdk
COPY --from=build /opt/icemaint/.venv /opt/icemaint/.venv

# Jars Iceberg déposés à côté des jars Spark : chargés d'office au démarrage
ADD --chmod=644 ${MAVEN_REPO}/org/apache/iceberg/iceberg-spark-runtime-4.1_2.13/${ICEBERG_VERSION}/iceberg-spark-runtime-4.1_2.13-${ICEBERG_VERSION}.jar ${SPARK_JARS}/
ADD --chmod=644 ${MAVEN_REPO}/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar ${SPARK_JARS}/

RUN useradd --uid 10001 --create-home icemaint \
 && mkdir -p /opt/icemaint/tls \
 && java -version \
 && ls "${SPARK_JARS}"/iceberg-spark-runtime-*.jar "${SPARK_JARS}"/iceberg-aws-bundle-*.jar \
 && icemaint --version

USER icemaint
WORKDIR /home/icemaint
CMD ["icemaint", "--help"]
