#!/bin/sh

# Сертификат Let's Encrypt и HTTPS-часть конфига.
#
# Один сертификат (имя = $DOMAIN) на основной домен и поддомены мессенджера:
# files.<DOMAIN> (MinIO), rtc.<DOMAIN> (LiveKit), turn.<DOMAIN> (TURN/TLS на 443).
# Выпуск и продление — http-01 через webroot (/var/www/certbot), certbot конфиг nginx
# не трогает: 443 слушает stream-сервер с SNI-маршрутизацией (tls_stream.conf),
# поэтому установщик `certbot --nginx` здесь не подходит.
#
# STAGING на этом же сервере (MESSENGER_MIGRATION.md, раздел A) — только если задан
# STAGING_DOMAIN: серверы <STAGING_DOMAIN>, files./rtc./turn.<STAGING_DOMAIN> проксируют в
# контейнеры проекта profichat-staging (сеть profichat-edge). У staging ОТДЕЛЬНЫЙ сертификат
# (имя = $STAGING_DOMAIN), выпускается отдельным шагом после прод-сертификата, ошибка там
# только пишется в лог: проблемы DNS staging не мешают выпуску и продлению сертификата прода.
# STAGING_DOMAIN пуст — конфиг тот же, что и без staging.
#
# Запускается из /docker-entrypoint.d после envsubst шаблонов, до старта nginx.

CERT_NAME="$DOMAIN"
LIVE_DIR="/etc/letsencrypt/live/$CERT_NAME"
RENEWAL_DIR=/etc/letsencrypt/renewal
WEBROOT=/var/www/certbot
TLS_TEMPLATES=/etc/nginx/tls-templates
HTTP_TLS_CONF=/etc/nginx/conf.d/tls_http.conf
STREAM_TLS_CONF=/etc/nginx/stream-conf.d/tls_stream.conf
MAIN_HTTP_DIR=/etc/nginx/main-http.d

STAGING_TEMPLATES=/etc/nginx/staging-templates
STAGING_HTTP_CONF=/etc/nginx/conf.d/staging_http.conf
STAGING_TLS_HTTP_CONF=/etc/nginx/conf.d/staging_tls_http.conf
STAGING_TLS_STREAM_CONF=/etc/nginx/stream-conf.d/staging_tls_stream.conf
STAGING_SNI_MAP=/etc/nginx/stream-map.d/staging.map
STAGING_MAIN_HTTP_DIR=/etc/nginx/staging-main-http.d

mkdir -p "$WEBROOT" /etc/nginx/stream-conf.d /etc/nginx/stream-map.d "$MAIN_HTTP_DIR" "$STAGING_MAIN_HTTP_DIR"

# STAGING_DOMAIN: только имя хоста, и ни одно staging-имя (S, files./rtc./turn.S) не совпадает
# с именем прода (D, www./files./rtc./turn.D) — иначе staging выключен, прод работает как без него.
# Серверы staging лежат в conf.d раньше прода по алфавиту: при совпадении server_name nginx
# отдал бы прод-имя в staging. Совпадение возможно, только если S — одно из имён прода или
# D заканчивается на .S (files.S = D и т. п.); такие значения отвергаются целиком.
staging_reject() {
    echo "[staging] !!! STAGING_DOMAIN='$STAGING_DOMAIN' ОТВЕРГНУТ: $1 — staging ВЫКЛЮЧЕН, прод работает без него. Исправьте STAGING_DOMAIN в .env.prod"
    STAGING_DOMAIN=
}
STAGING_DOMAIN=$(echo "$STAGING_DOMAIN" | tr '[:upper:]' '[:lower:]')
domain_lower=$(echo "$DOMAIN" | tr '[:upper:]' '[:lower:]')
if [ -n "$STAGING_DOMAIN" ]; then
    if ! echo "$STAGING_DOMAIN" | grep -Eq '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$'; then
        staging_reject "не имя хоста"
    else
        case "$STAGING_DOMAIN" in
            "$domain_lower"|"www.$domain_lower"|"files.$domain_lower"|"rtc.$domain_lower"|"turn.$domain_lower")
                staging_reject "совпадает с именем прода ($DOMAIN, www./files./rtc./turn.)" ;;
        esac
        case "$domain_lower" in
            *".$STAGING_DOMAIN")
                [ -n "$STAGING_DOMAIN" ] && staging_reject "DOMAIN=$DOMAIN лежит внутри него (имена staging могут совпасть с прод-доменом)" ;;
        esac
    fi
fi
export STAGING_DOMAIN
STAGING_LIVE_DIR="/etc/letsencrypt/live/$STAGING_DOMAIN"

have_cert() {
    [ -f "$1/fullchain.pem" ] && [ -f "$1/privkey.pem" ]
}

# TLS-часть и поведение :80 основного домена — по наличию сертификата (собирается заново при
# каждом старте). Есть сертификат: https-серверы, 443 со SNI, а :80 отдаёт только ACME и 301
# на https. Нет: всё приложение по http :80 (первый запуск до certbot, dev).
configure_tls() {
    rm -f "$HTTP_TLS_CONF" "$STREAM_TLS_CONF" "$MAIN_HTTP_DIR"/*.conf
    if have_cert "$LIVE_DIR"; then
        envsubst '${DOMAIN}' < "$TLS_TEMPLATES/tls_http.conf" > "$HTTP_TLS_CONF"
        envsubst '${DOMAIN}' < "$TLS_TEMPLATES/tls_stream.conf" > "$STREAM_TLS_CONF"
        cp /etc/nginx/snippets/http_redirect.conf "$MAIN_HTTP_DIR/main.conf"
        return 0
    fi
    cp /etc/nginx/snippets/app_locations.conf "$MAIN_HTTP_DIR/main.conf"
    return 1
}

# Staging (только при STAGING_DOMAIN). :80 есть всегда (ACME для сертификата staging). https и
# TURN/TLS на 443 — только когда есть и сертификат staging, и прод-сертификат (443/stream и
# внутренний 127.0.0.1:8443 включаются прод-частью). Иначе staging-приложение — по http :80.
# Код возврата: 0 — staging по https, 1 — нет.
configure_staging() {
    rm -f "$STAGING_HTTP_CONF" "$STAGING_TLS_HTTP_CONF" "$STAGING_TLS_STREAM_CONF" \
        "$STAGING_SNI_MAP" "$STAGING_MAIN_HTTP_DIR"/*.conf
    [ -n "$STAGING_DOMAIN" ] || return 1
    envsubst '${STAGING_DOMAIN}' < "$STAGING_TEMPLATES/staging_http.conf" > "$STAGING_HTTP_CONF"
    if have_cert "$STAGING_LIVE_DIR" && have_cert "$LIVE_DIR"; then
        envsubst '${STAGING_DOMAIN}' < "$STAGING_TEMPLATES/staging_tls_http.conf" > "$STAGING_TLS_HTTP_CONF"
        envsubst '${STAGING_DOMAIN}' < "$STAGING_TEMPLATES/staging_tls_stream.conf" > "$STAGING_TLS_STREAM_CONF"
        printf 'turn.%s 127.0.0.1:5351;\n' "$STAGING_DOMAIN" > "$STAGING_SNI_MAP"
        cp /etc/nginx/snippets/http_redirect.conf "$STAGING_MAIN_HTTP_DIR/main.conf"
        return 0
    fi
    cp /etc/nginx/snippets/staging_app_locations.conf "$STAGING_MAIN_HTTP_DIR/main.conf"
    return 1
}

configure_tls
configure_staging

get_certs_lower=$(echo "$GET_CERTS" | tr '[:upper:]' '[:lower:]')

if [ "$get_certs_lower" = "true" ]; then
    # Временный nginx отвечает на проверку certbot из $WEBROOT (на :80 она есть в обоих вариантах).
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
    # Staging — отдельный сертификат и отдельный шаг ПОСЛЕ прода: его ошибка ничего не ломает.
    if [ -n "$STAGING_DOMAIN" ]; then
        if ! certbot certonly --webroot -w "$WEBROOT" \
            --cert-name "$STAGING_DOMAIN" \
            -d "$STAGING_DOMAIN" -d "files.$STAGING_DOMAIN" -d "rtc.$STAGING_DOMAIN" -d "turn.$STAGING_DOMAIN" \
            --email "$CERTBOT_EMAIL" --agree-tos --no-eff-email \
            --non-interactive --keep-until-expiring --expand; then
            echo "[certbot] не удалось получить сертификат staging для $STAGING_DOMAIN и поддоменов (DNS настроены?) — прод не затронут"
        fi
    fi
    nginx -s stop
    # Need time for stop
    sleep 2

    # Сертификаты, выпущенные раньше через `certbot --nginx`, помнят installer = nginx:
    # `certbot renew` переписал бы конфиг (listen 443 ssl) и сломал SNI-маршрутизацию.
    # `certbot renew` продлевает все сертификаты из $RENEWAL_DIR (прод и staging), deploy-хук
    # (autorenew_hook.sh) перечитывает конфиг nginx после любого из них.
    for conf in "$RENEWAL_DIR/$CERT_NAME.conf" "$RENEWAL_DIR/$STAGING_DOMAIN.conf"; do
        if [ -f "$conf" ]; then
            sed -i '/^installer = /d' "$conf"
        fi
    done
fi

# сертификат мог появиться только что — пересобрать
if configure_tls; then
    echo "[tls] сертификат $LIVE_DIR найден, включаю HTTPS (443: SNI → https / TURN/TLS), :80 → 301 на https"
else
    echo "[tls] сертификата $LIVE_DIR нет, работаю только по http :80"
fi

if configure_staging; then
    echo "[staging] $STAGING_DOMAIN: HTTPS включён (сертификат $STAGING_LIVE_DIR), :80 → 301 на https"
elif [ -n "$STAGING_DOMAIN" ]; then
    echo "[staging] $STAGING_DOMAIN: сертификата staging (или прода) нет — staging только по http :80"
else
    echo "[staging] STAGING_DOMAIN не задан — staging-серверов нет"
fi
