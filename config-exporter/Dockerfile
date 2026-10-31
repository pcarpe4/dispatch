FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY exporter ./exporter

# OpenShift runs with a random UID in group 0; UBI images already handle this.
USER 1001
ENTRYPOINT ["python", "-m", "exporter.main"]
CMD ["--config", "/config/exporter.yaml"]
