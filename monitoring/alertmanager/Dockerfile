FROM alpine:3.20 AS gettext-builder

RUN apk add --no-cache gettext

FROM prom/alertmanager:v0.27.0

USER root
COPY --from=gettext-builder /usr/bin/envsubst /usr/local/bin/envsubst

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY alertmanager.yml.tmpl /etc/alertmanager/alertmanager.yml.tmpl

USER nobody
ENTRYPOINT ["/entrypoint.sh"]
