FROM nginx:1.26.0

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY ./nginx_entrypoint.sh /docker-entrypoint.d/.
COPY ./autorenew_hook.sh /etc/letsencrypt/renewal-hooks/deploy/.
COPY ./certbot_renew_loop.sh /docker-entrypoint.d/.
RUN chmod +x /docker-entrypoint.d/nginx_entrypoint.sh /docker-entrypoint.d/certbot_renew_loop.sh
RUN apt update
RUN apt install certbot python3-certbot-nginx -y
