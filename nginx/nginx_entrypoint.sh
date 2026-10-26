#!/bin/sh

# Сертификат Let's Encrypt и HTTPS-часть конфига.
#
# Один сертификат (имя = $DOMAIN) на основной домен и поддомены мессенджера:
# files.<DOMAIN> (MinIO), rtc.<DOMAIN> (LiveKit), turn.<DOMAIN> (TURN/TLS на 443).
# Выпуск и продление — http-01 через webroot (/var/www/certbot), certbot конфиг nginx
# не трогает: 443 слушает stream-сервер с SNI-маршрутизацией (tls_stream.conf),
# поэтому установщик `certbot --nginx` здесь не подходит.
#
# Запускается из /docker-entrypoint.d после envsubst шаблонов, до старта nginx.

CERT_NAME="$DOMAIN"
LIVE_DIR="/etc/letsencrypt/live/$CERT_NAME"
RENEWAL_CONF="/etc/letsencrypt/renewal/$CERT_NAME.conf"
WEBROOT=/var/www/certbot
TLS_TEMPLATES=/etc/nginx/tls-templates
HTTP_TLS_CONF=/etc/nginx/conf.d/tls_http.conf
STREAM_TLS_CONF=/etc/nginx/stream-conf.d/tls_stream.conf

mkdir -p "$WEBROOT" /etc/nginx/stream-conf.d
# при рестарте контейнера TLS-часть собирается заново
rm -f "$HTTP_TLS_CONF" "$STREAM_TLS_CONF"

get_certs_lower=$(echo "$GET_CERTS" | tr '[:upper:]' '[:lower:]')

if [ "$get_certs_lower" = "true" ]; then
    # Временный nginx (пока только :80) отвечает на проверку certbot из $WEBROOT.
    nginx
    # --keep-until-expiring: если сертификат уже покрывает все имена и не истекает — ничего не делает.
    # Если в существующем сертификате нет поддоменов (первый деплой мессенджера) — перевыпускает
    # его с полным списком имён под тем же именем (--cert-name), путь live/$DOMAIN не меняется.
    if ! certbot certonly --webroot -w "$WEBROOT" \
        --cert-name "$CERT_NAME" \
        -d "$DOMAIN" -d "files.$DOMAIN" -d "rtc.$DOMAIN" -d "turn.$DOMAIN" \
        --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email \
        --non-interactive --keep-until-expiring --expand; then
        echo "[certbot] не удалось получить сертификат для $DOMAIN и поддоменов (DNS files./rtc./turn. настроены?)"
    fi
    nginx -s stop
    # Need time for stop
    sleep 2

    # Сертификаты, выпущенные раньше через `certbot --nginx`, помнят installer = nginx:
    # `certbot renew` переписал бы конфиг (listen 443 ssl) и сломал SNI-маршрутизацию.
    if [ -f "$RENEWAL_CONF" ]; then
        sed -i '/^installer = /d' "$RENEWAL_CONF"
    fi
fi

if [ -f "$LIVE_DIR/fullchain.pem" ] && [ -f "$LIVE_DIR/privkey.pem" ]; then
    echo "[tls] сертификат $LIVE_DIR найден, включаю HTTPS (443: SNI → https / TURN/TLS)"
    envsubst '${DOMAIN}' < "$TLS_TEMPLATES/tls_http.conf" > "$HTTP_TLS_CONF"
    envsubst '${DOMAIN}' < "$TLS_TEMPLATES/tls_stream.conf" > "$STREAM_TLS_CONF"
else
    echo "[tls] сертификата $LIVE_DIR нет, работаю только по http :80"
fi
