# Remna Routing Updater

Микросервис для автоматического обновления кастомного заголовка ответа `routing` в Remna панели при появлении новых данных в GitHub-репозитории [roscomvpn-happ-routing](https://github.com/hydraponique/roscomvpn-happ-routing).

## Как работает

1. При запуске получает заголовок `routing` из настроек подписки и из настроек каждого настроенного внешнего сквада
2. Проверяет файлы с роутингом на GitHub — по интервалу (`CHECK_INTERVAL`) или по расписанию (`CRON_SCHEDULE`)
3. Если содержимое изменилось — отправляет новое содержимое заголовка `routing` в Remna
4. Если изменений нет — ничего не делает

Настройки подписки и каждый внешний сквад отслеживаются **независимо**: у каждого свой GitHub URL и свой кеш текущего роутинга. Изменение в одном не затрагивает остальные.

## Быстрый старт

```bash
mkdir remna-routing-updater && cd remna-routing-updater
```

### Внешняя панель (HTTPS)

Создайте файл `.env`:

```env
REMNA_BASE_URL=https://your-host/api
REMNA_TOKEN=your_bearer_token
# GITHUB_RAW_URL=https://raw.githubusercontent.com/hydraponique/roscomvpn-happ-routing/refs/heads/main/HAPP/DEFAULT.DEEPLINK
# CHECK_INTERVAL=300
```

Создайте файл `docker-compose.yml`:

```yaml
services:
  routing-updater:
    image: ghcr.io/lifeindarkside/remnawave-routing-update:latest
    container_name: remna-routing-updater
    restart: unless-stopped
    env_file:
      - .env
```

### Локальная панель (Docker)

Если RemnaWave панель запущена локально в Docker (образ `remnawave/backend:latest`), контейнер updater нужно подключить к той же сети `remnawave-network` и обращаться к панели по имени контейнера.

Создайте файл `.env`:

```env
REMNA_BASE_URL=http://remnawave:3000/api
REMNA_TOKEN=your_bearer_token
# GITHUB_RAW_URL=https://raw.githubusercontent.com/hydraponique/roscomvpn-happ-routing/refs/heads/main/HAPP/DEFAULT.DEEPLINK
# CHECK_INTERVAL=300
```

> `remnawave` — имя контейнера панели, `3000` — порт по умолчанию. Измените при необходимости.

Создайте файл `docker-compose.yml`:

```yaml
services:
  routing-updater:
    image: ghcr.io/lifeindarkside/remnawave-routing-update:latest
    container_name: remna-routing-updater
    restart: unless-stopped
    env_file:
      - .env
    networks:
      - remnawave-network

networks:
  remnawave-network:
    name: remnawave-network
    external: true
```

> Сеть `remnawave-network` должна уже существовать (создаётся docker-compose панели RemnaWave).

Запуск:

```bash
docker compose up -d
```

### Сборка из исходников

Если хотите собрать образ самостоятельно:

```bash
git clone https://github.com/lifeindarkside/Remnawave-Routing-update.git
cd Remnawave-Routing-update
cp .env.example .env
# отредактируйте .env
docker build -t remna-routing-updater .
docker compose up -d
```

## Переменные окружения

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `REMNA_BASE_URL` | да | — | Базовый URL API Remna (например `https://host/api` или `http://remnawave:3000/api`) |
| `REMNA_TOKEN` | да | — | Bearer-токен для авторизации в Remna API |
| `GITHUB_RAW_URL` | нет | [DEFAULT.DEEPLINK](https://raw.githubusercontent.com/hydraponique/roscomvpn-happ-routing/refs/heads/main/HAPP/DEFAULT.DEEPLINK) | URL файла с роутингом для настроек подписки |
| `CHECK_INTERVAL` | нет | `300` | Интервал проверки обновлений (в секундах), общий для всех |
| `CRON_SCHEDULE` | нет | — | Запуск проверки по расписанию (cron-выражение, напр. `0 9 * * *`). Если задано — заменяет `CHECK_INTERVAL`. Время в часовом поясе контейнера (по умолчанию UTC) |
| `SQUAD_N_UUID` | нет | — | UUID внешнего сквада (N = 1, 2, 3, ...) |
| `SQUAD_N_URL` | нет | — | GitHub URL файла с роутингом для этого сквада |

### Режим запуска: интервал или расписание

Сервис поддерживает два взаимоисключающих режима проверки:

- **Интервал** (по умолчанию) — проверка каждые `CHECK_INTERVAL` секунд.
- **Расписание** — если задан `CRON_SCHEDULE` (cron-выражение), проверка идёт по расписанию, а `CHECK_INTERVAL` игнорируется. Дополнительно одна проверка выполняется сразу при старте, чтобы не ждать первого срабатывания после рестарта или деплоя.

**Зачем расписание.** Списки роутинга в [roscomvpn-happ-routing](https://github.com/hydraponique/roscomvpn-happ-routing) пересобираются примерно раз в сутки (автосборкой по утрам UTC). При интервале в 5 минут это ≈ 288 запросов к GitHub в сутки ради одного реального изменения. `CRON_SCHEDULE` позволяет синхронизироваться один раз — например, утром после пересборки — и сократить число запросов в сотни раз:

```env
# каждый день в 09:00 (часовой пояс контейнера, по умолчанию UTC)
CRON_SCHEDULE=0 9 * * *
```

> Часовой пояс берётся из контейнера (по умолчанию UTC). Для другого пояса задайте переменную `TZ`, например `TZ=Europe/Moscow`.

### Внешние сквады

Для каждого сквада задаётся пара переменных с порядковым номером:

```env
SQUAD_1_UUID=your-first-squad-uuid-here
SQUAD_1_URL=https://raw.githubusercontent.com/.../SQUAD1.DEEPLINK

SQUAD_2_UUID=your-second-squad-uuid-here
SQUAD_2_URL=https://raw.githubusercontent.com/.../SQUAD2.DEEPLINK
```

Количество сквадов не ограничено. Если переменные не заданы — синхронизируются только настройки подписки.

## Логи

```bash
docker compose logs -f
```

## Лицензия

MIT
