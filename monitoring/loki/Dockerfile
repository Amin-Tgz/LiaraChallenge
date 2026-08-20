FROM busybox:1.37.0-musl AS tools

FROM grafana/loki:3.7.4

COPY loki-config.yml /etc/loki/loki-config.yml
COPY --from=tools /bin/wget /bin/wget

# Liara mounts this app's persistent disk root-owned. The upstream UID 10001
# cannot initialize or reopen the filesystem TSDB on that mount. Keep this
# exception scoped to the private single-purpose Loki container.
USER 0:0

ENTRYPOINT ["/usr/bin/loki"]
CMD ["-config.file=/etc/loki/loki-config.yml"]

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=10 \
  CMD ["/bin/wget", "-q", "-O", "/dev/null", "http://127.0.0.1:3100/ready"]
