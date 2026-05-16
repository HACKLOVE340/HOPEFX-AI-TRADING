FROM prom/alertmanager:v0.27.0

USER root

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY alertmanager.yml.tmpl /etc/alertmanager/alertmanager.yml.tmpl

USER nobody
ENTRYPOINT ["/entrypoint.sh"]
