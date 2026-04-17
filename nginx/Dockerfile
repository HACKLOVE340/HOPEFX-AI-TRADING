FROM nginx:1.27-alpine

# Install envsubst (part of gettext). Pin version for reproducible builds.
# To update: docker run --rm nginx:1.27-alpine apk info gettext
RUN apk add --no-cache gettext=0.22.5-r0

# Copy template — entrypoint.sh renders it to /etc/nginx/nginx.conf at start
COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
