# Деплой links-dashboard на ноутбуке (winbox)

Приложение крутится контейнером `links-dashboard` на ноутбуке (WSL2 Ubuntu, Docker). С Мака открывается как
`http://links.test`: Мак :80 -> Mutagen -> edge-proxy ноутбука :10080 -> приложение `127.0.0.1:8099`.

## Что где лежит на ноутбуке

| Путь | Что это |
| --- | --- |
| `/home/ivan/.config/links-dashboard/` | каталог данных, в контейнере `/data` (права 700) |
| `.../mac_key`, `.../mac_key.pub` | ssh-ключ для чтения данных с Мака (ed25519, без пароля) |
| `.../kubeconfig` | kubeconfig кластера kind `rosfines-dev` (права 600, содержит клиентские секреты) |
| `.../state.json` | состояние приложения (единственный файл, который оно пишет) |
| `.../known_hosts` | отпечаток Мака, добавляется при первом подключении (`accept-new`) |
| `/home/ivan/build/edge-proxy/nginx.conf` | конфиг edge-proxy; в контейнер монтируется только на чтение как `/config/edge-nginx.conf` |
| `/home/ivan/build/edge-proxy/nginx.conf.bak-links` | копия конфига до добавления `links.test` |

Контейнер работает с `network_mode: host`, слушает только `127.0.0.1:8099`, монтирует `/var/run/docker.sock`.
Флаг `:ro` у сокета не делает Docker API доступным только на чтение: через сокет можно делать с Docker что угодно, то есть
контейнер фактически имеет root на ноутбуке. Только чтение обеспечивает код приложения, а не монтирование.
Процесс внутри контейнера идет от root: `ssh` требует, чтобы у uid была запись в `/etc/passwd`, а у root она есть; к тому же сокет Docker и ключ в `/data`
доступны ему без смены прав. Приложение ничего не меняет ни на Маке, ни на ноутбуке, кроме `state.json`.

## Обновить после изменений в коде

С Мака, контекст Docker `winbox` (`docker context show` должен печатать `winbox`; Docker Desktop не нужен):

```bash
cd /Users/i.senishin/project/home/links-dashboard
docker compose -f deploy/compose.yml up -d --build
ssh winbox 'curl -s -H "Host: links.test" http://127.0.0.1:8099/api/snapshot' | head -c 300
```

Контекст сборки уходит с Мака (исключения в `.dockerignore`), пути в `volumes` - пути ноутбука.

## Правка конфига edge-proxy

`nginx.conf` смонтирован в `edge-proxy` и в `links-dashboard` как отдельный файл, поэтому его нельзя заменять новым файлом
(`sed -i`, `mv`, редакторы с переименованием): контейнеры продолжат видеть старый inode. Правьте на месте, например
`python3` с `open(p, "r+")`, `seek(0)`, `write`, `truncate`, либо `cat новый > nginx.conf`. После правки:

```bash
ssh winbox 'docker exec edge-proxy nginx -t && docker exec edge-proxy nginx -s reload'
```

Если inode все же сменился - пересоздайте оба контейнера (`docker compose ... up -d --force-recreate` для приложения
и `docker compose up -d --force-recreate` в `~/build/edge-proxy`).

## Обновить kubeconfig (кластер пересоздан)

Порт API-сервера kind меняется при пересоздании кластера. С Мака:

```bash
kubectl config view --minify --flatten --context kind-rosfines-dev \
  | ssh winbox 'umask 077; cat > /home/ivan/.config/links-dashboard/kubeconfig; chmod 600 /home/ivan/.config/links-dashboard/kubeconfig'
```

Перезапуск контейнера не нужен: файл читается при каждом обновлении. Не печатайте kubeconfig в чат и логи.

## Подключить Мак позже

Пока на Маке не включен удаленный вход, плитки «Синхронизация» и «Пробросы» показывают «Мак недоступен», в `failed_sources` -
`mac`, остальное работает. Ключ на ноутбуке уже создан. Шаги ниже делает владелец; приложение само ничего на Маке не ставит.

1. На Маке включить Remote Login: Системные настройки -> Основные -> Общий доступ -> Удаленный вход, разрешить только
   пользователю `i.senishin`. В роутере закрепить за Маком адрес `10.0.100.243`.
2. Установить команду, которую будет вызывать ключ (из каталога проекта на Маке):

   ```bash
   mkdir -p /Users/i.senishin/bin
   install -m 755 mac/links-dashboard-mac-info /Users/i.senishin/bin/links-dashboard-mac-info
   ```

3. Добавить ключ ноутбука в `~/.ssh/authorized_keys` на Маке одной строкой. Формат:

   ```
   command="/Users/i.senishin/bin/links-dashboard-mac-info",restrict <содержимое mac_key.pub>
   ```

   Публичный ключ взять так, строку собрать и дописать (перевод строки в начале нужен, чтобы новая строка не склеилась
   с последней, если в файле нет завершающего `\n`; пустая строка в `authorized_keys` допустима):

   ```bash
   PUB="$(ssh winbox cat /home/ivan/.config/links-dashboard/mac_key.pub)"
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   printf '\ncommand="/Users/i.senishin/bin/links-dashboard-mac-info",restrict %s\n' "$PUB" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

   `restrict` отключает shell, pty и проброс портов, `command=` фиксирует единственную команду: какую бы команду ни
   запросил клиент, выполнится только `links-dashboard-mac-info`.
4. Проверить с ноутбука (`ssh winbox`):

   ```bash
   ssh -i ~/.config/links-dashboard/mac_key i.senishin@10.0.100.243 \
     | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d))'
   ```

   Ожидается `['branches', 'errors', 'forward', 'generated_at', 'hosts', 'sync']`. Первое подключение спросит отпечаток -
   для проверки подтвердите его вручную (`yes`), приложение дальше использует `StrictHostKeyChecking=accept-new` и
   `/data/known_hosts`. Затем убедиться, что запрошенная команда игнорируется:

   ```bash
   ssh -i ~/.config/links-dashboard/mac_key i.senishin@10.0.100.243 whoami
   ```

   Должен снова напечататься JSON, а не имя пользователя.
5. На Маке добавить `links.test` в строку `/etc/hosts` с `beszel.test netdata.test` (нужен `sudo`), если еще не добавлен.
6. Открыть `http://links.test`, нажать «Обновить»: плитки синхронизации и пробросов должны заполниться, `failed_sources` - опустеть.

## Заменить команду на Маке

После изменений в `mac/links-dashboard-mac-info` повторить шаг 2 и проверку из шага 4 (`sorted(d)`).

## Диагностика

```bash
docker logs links-dashboard --tail 50
ssh winbox 'curl -s -H "Host: links.test" http://127.0.0.1:8099/api/snapshot' | python3 -m json.tool | tail -20
```

`failed_sources` в ответе называет источник, который не ответил: `mac`, `docker`, `cluster`, `edge` или `laptop`.
