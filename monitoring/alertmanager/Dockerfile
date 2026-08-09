FROM prom/alertmanager:v0.27.0

USER root

COPY entrypoint.sh /entrypoint.sh
COPY render-config.sh /render-config.sh
COPY channels.sh /channels.sh
RUN chmod +x /entrypoint.sh /render-config.sh

COPY alertmanager.yml.tmpl /etc/alertmanager/alertmanager.yml.tmpl

USER nobody
ENTRYPOINT ["/entrypoint.sh"]
