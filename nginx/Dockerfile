FROM nginx:1.26.0

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY app_locations.conf http_redirect.conf /etc/nginx/snippets/
# HTTPS-часть: шаблоны подключает nginx_entrypoint.sh, когда сертификат уже есть
COPY tls_http.conf tls_stream.conf /etc/nginx/tls-templates/
COPY ./nginx_entrypoint.sh /docker-entrypoint.d/.
COPY ./autorenew_hook.sh /etc/letsencrypt/renewal-hooks/deploy/.
COPY ./certbot_renew_loop.sh /docker-entrypoint.d/.
RUN chmod +x /docker-entrypoint.d/nginx_entrypoint.sh /docker-entrypoint.d/certbot_renew_loop.sh
# stream-блок (443 с SNI-маршрутизацией) — вне http {}, поэтому отдельный include в nginx.conf
RUN mkdir -p /etc/nginx/stream-conf.d /var/www/certbot \
    && printf '\nstream {\n    include /etc/nginx/stream-conf.d/*.conf;\n}\n' >> /etc/nginx/nginx.conf
RUN apt update
# выпуск — certbot certonly --webroot; плагин nginx оставлен для продления старых сертификатов,
# выпущенных через `certbot --nginx` (authenticator = nginx в их renewal-конфиге)
RUN apt install certbot python3-certbot-nginx -y
