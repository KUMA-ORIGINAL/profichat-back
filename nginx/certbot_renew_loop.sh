#!/bin/sh

# Автопродление сертификатов Let's Encrypt.
# Запускается из /docker-entrypoint.d до старта nginx, поэтому цикл уходит в
# фон: сначала ждёт, потом дёргает `certbot renew`. certbot продлевает только
# сертификаты, у которых осталось меньше 30 дней, так что частый запуск безопасен.
# После успешного продления сработает deploy-хук (autorenew_hook.sh) и nginx
# перечитает сертификат без рестарта.

get_certs_lower=$(echo "$GET_CERTS" | tr '[:upper:]' '[:lower:]')

if [ "$get_certs_lower" = "true" ]; then
    (
        while true; do
            # Первую проверку делаем не сразу: к этому моменту nginx уже запущен,
            # а свежевыпущенный сертификат точно не нуждается в продлении.
            sleep 12h
            echo "[certbot-renew] $(date -u '+%Y-%m-%d %H:%M:%S') checking certificates"
            certbot renew --quiet || echo "[certbot-renew] renew failed, will retry in 12h"
        done
    ) &
fi
