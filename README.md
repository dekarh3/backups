# Backups — Система централизованного резервного копирования

Централизованная система резервного копирования на базе **restic** и **rest-server** с веб-интерфейсом управления. Предназначена для создания надежных бэкапов Windows и Linux клиентов на Linux-сервер хранения данных.

## Основные возможности

- **Автоматическое резервное копирование** по расписанию с поддержкой календаря рабочих дней
- **Веб-интерфейс администратора** для мониторинга состояния, управления бэкапами и просмотра логов
- **REST API** для программного управления системой
- **Append-only режим** хранения данных для защиты от случайного удаления
- **Политики хранения** с автоматической очисткой устаревших снапшотов
- **Мониторинг и алертинг** при ошибках и проблемах с дисковым пространством
- **Ролевая модель** с разделением прав администратора и наблюдателя
- **Аудит действий** и логирование всех операций

## Архитектура

```
┌─────────────┐      HTTPS      ┌─────────────────────────────────────┐
│   Клиент    │ ◄──────────────► │           СХД-сервер                │
│  (Windows/  │                 │  ┌─────────────┐  ┌───────────────┐ │
│   Linux)    │                 │  │ rest-server │  │   api.py      │ │
│  - cerber.py│                 │  │  (порт 8443)│  │  (порт 9443)  │ │
│  - manager.py│                │  └─────────────┘  └───────────────┘ │
│  - worker.py│                 │  ┌─────────────┐  ┌───────────────┐ │
│  - restic   │                 │  │interface.py │  │  PostgreSQL   │ │
└─────────────┘                 │  │  (веб-UI)   │  │               │ │
                                │  └─────────────┘  └───────────────┘ │
                                └─────────────────────────────────────┘
```

**Компоненты сервера:**
- `rest-server` — HTTPS-сервер для приема данных от restic (порт 8443)
- `api.py` — FastAPI сервер управления, планировщик, очередь команд (порт 9443)
- `interface.py` — Веб-интерфейс администратора (SSR на Jinja2)
- `PostgreSQL` — Хранилище оперативного состояния системы

**Компоненты клиента:**
- `cerber.py` — Сторжевой процесс
- `manager.py` — Управляющий агент
- `worker.py` — Процесс выполнения бэкапа
- `restic` — Утилита резервного копирования (0.15.2 для Windows, 0.19.1 для Linux)

---

## Установка сервера

### Системные требования

- ОС: RedOS 8 или совместимый Linux
- Python 3.8+
- PostgreSQL 12+
- Свободное дисковое пространство согласно плану бэкапов

### 1. Установка зависимостей

```bash
# Обновление системы
sudo dnf update -y

# Установка Python и зависимостей
sudo dnf install -y python3.8 python3.8-pip python3.8-devel postgresql postgresql-server git

# Установка rest-server
wget https://github.com/restic/rest-server/releases/download/v0.13.0/rest-server_0.13.0_linux_amd64
sudo mv rest-server_0.13.0_linux_amd64 /usr/local/bin/rest-server
sudo chmod +x /usr/local/bin/rest-server

# Создание директорий
sudo mkdir -p /opt/backups/{ini,secrets,keys,scripts}
sudo mkdir -p /srv/backups/restic
sudo mkdir -p /var/log/backups
sudo mkdir -p /backup_cache

# Установка прав
sudo chown -R $(whoami):$(whoami) /opt/backups
sudo chown -R $(whoami):$(whoami) /srv/backups/restic
sudo chown -R $(whoami):$(whoami) /var/log/backups
sudo chown -R $(whoami):$(whoami) /backup_cache
```

### 2. Настройка PostgreSQL

```bash
# Инициализация БД (если требуется)
sudo postgresql-setup --initdb

# Запуск PostgreSQL
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Создание пользователя и базы данных
sudo -u postgres psql <<EOF
CREATE USER backups WITH PASSWORD 'secure_password_here';
CREATE DATABASE backups OWNER backups;
GRANT ALL PRIVILEGES ON DATABASE backups TO backups;
EOF
```

### 3. Генерация ключей и секретов

```bash
# Генерация ключа подписи
mkdir -p /opt/backups/keys
openssl genrsa -out /opt/backups/keys/backups.key 2048
chmod 600 /opt/backups/keys/backups.key

# Создание директории для секретов клиентов
mkdir -p /opt/backups/secrets
chmod 700 /opt/backups/secrets
```

### 4. Конфигурация

Создайте основной файл конфигурации `/opt/backups/ini/backups.ini`:

```ini
[global]
base_url = https://localhost:8443
api_url = https://localhost:9443
restic_root = /srv/backups/restic

db_dsn = postgresql://backups:secure_password_here@127.0.0.1:5432/backups

signing_private_key = /opt/backups/keys/backups.key
secrets_dir = /opt/backups/secrets
log_dir = /var/log/backups

command_ttl_hours = 12
offline_grace_hours = 6
ack_timeout_minutes = 10
ack_retry_max = 10
run_missing_ack_retry_max = 2

long_running_threshold_hours = 3
max_run_time_hours = 12
stop_timeout_minutes = 5

script_prepare_timeout_sec = 600
restic_start_timeout_minutes = 10
api_connect_timeout_minutes = 5
progress_timeout_minutes = 2

snapshot_daily_limit = 2
snapshot_8h_limit = 1
anomaly_growth_factor = 2.0

free_space_stop_factor = 0.05
free_space_alert_factor = 0.1

contact_warning_minutes = 2
contact_error_minutes = 5

retry_intervals_minutes = 5,15,30,30,30

restic_cache_root = /backup_cache
restic_cache_max_gb = 1024
restic_allow_no_cache = true

prune_daily_required = true

smtp_enabled = false
smtp_host = mail.example.com
smtp_from = backups@example.com
smtp_to_admin = admin@example.com
```

### 5. Установка Python-зависимостей

```bash
cd /workspace/backups

# Создание виртуального окружения
python3.8 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install --upgrade pip
pip install fastapi uvicorn[standard] psycopg2-binary jinja2 python-multipart pydantic cryptography python-jose passlib htpasswd
```

### 6. Настройка SSL-сертификатов

Для работы в production необходим SSL-сертификат. Для тестирования можно создать самоподписанный:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /opt/backups/keys/server.key \
  -out /opt/backups/keys/server.crt \
  -subj "/CN=backup-srv"

chmod 600 /opt/backups/keys/server.key
chmod 644 /opt/backups/keys/server.crt
```

### 7. Запуск сервисов

#### Запуск rest-server

```bash
# Создание файла аутентификации
htpasswd -cb /opt/backups/auth/restic.htpasswd admin secure_password

# Запуск rest-server (для production используйте systemd)
rest-server --append-only --private-repos \
  --path /srv/backups/restic \
  --auth /opt/backups/auth/restic.htpasswd \
  --tls --tls-cert /opt/backups/keys/server.crt \
  --tls-key /opt/backups/keys/server.key \
  --listen :8443
```

#### Запуск api.py

```bash
cd /workspace/backups
source venv/bin/activate

# Проверка конфигурации
python api.py --check-config

# Запуск API сервера
uvicorn api:app --host 0.0.0.0 --port 9443 \
  --ssl-keyfile /opt/backups/keys/server.key \
  --ssl-certfile /opt/backups/keys/server.crt
```

#### Запуск web-интерфейса

Web-интерфейс является частью приложения FastAPI и доступен после запуска `api.py`.

По умолчанию интерфейс доступен по адресу: `https://localhost:9443/`

Первый вход требует настройки администратора через базу данных или конфигурационный файл.

---

## Установка клиента

### Системные требования

**Windows:**
- Windows 7 Pro или новее
- Python 3.8+
- restic 0.15.2

**Linux (RedOS 8):**
- Python 3.8+
- restic 0.19.1

### 1. Установка зависимостей (Windows)

```powershell
# Скачать и установить Python 3.8 с https://www.python.org/downloads/

# Скачать restic 0.15.2
wget https://github.com/restic/restic/releases/download/v0.15.2/restic_0.15.2_windows_amd64.exe
Move-Item restic_0.15.2_windows_amd64.exe C:\ProgramData\restic\restic.exe

# Добавить в PATH
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\ProgramData\restic", "Machine")
```

### 1. Установка зависимостей (Linux)

```bash
# Установка Python и restic
sudo dnf install -y python3.8 python3.8-pip

wget https://github.com/restic/restic/releases/download/v0.19.1/restic_0.19.1_linux_amd64
sudo mv restic_0.19.1_linux_amd64 /usr/local/bin/restic
sudo chmod +x /usr/local/bin/restic
```

### 2. Установка клиентских скриптов

Скопируйте клиентские скрипты из репозитория:

```bash
# Linux
sudo mkdir -p /opt/backups/client
sudo cp cerber.py manager.py worker.py /opt/backups/client/

# Windows (PowerShell от администратора)
New-Item -ItemType Directory -Force -Path "C:\ProgramData\backups\client"
Copy-Item cerber.py, manager.py, worker.py "C:\ProgramData\backups\client\"
```

### 3. Настройка клиента

Создайте файл конфигурации клиента:

**Linux:** `/opt/backups/ini/client.ini`
**Windows:** `C:\ProgramData\backups\ini\client.ini`

```ini
[client]
name = client01
enabled = true

server_api_url = https://backup-srv:9443
server_rest_url = https://backup-srv:8443

agent_token_file = /opt/backups/secrets/agent.token
ca_cert_file = /opt/backups/keys/ca.crt

timezone = Europe/Moscow
log_dir = /var/log/backups_client
```

### 4. Получение токена аутентификации

Токен аутентификации клиента генерируется на сервере и должен быть размещен в файле, указанном в конфигурации.

На сервере выполните:

```bash
# Генерация токена для клиента
python -c "import secrets; print(secrets.token_hex(32))" > /opt/backups/secrets/client01.agent.token
chmod 600 /opt/backups/secrets/client01.agent.token

# Скопируйте токен на клиент в файл, указанный в agent_token_file
```

### 5. Регистрация клиента на сервере

Добавьте конфигурацию клиента на сервере:

`/opt/backups/ini/clients/client01.ini`:

```ini
[client]
name = client01
enabled = true

rest_server_base_url = https://backup-srv:8443
rest_http_user = client01
rest_http_password_file = /opt/backups/secrets/client01.rest-http.pass

client_public_key_file = /opt/backups/keys/clients/client01.pub
client_agent_token_file = /opt/backups/secrets/client01.agent.token

timezone = Europe/Moscow
```

Сгенерируйте пароль для rest-server:

```bash
# Генерация пароля
python -c "import secrets; print(secrets.token_urlsafe(32))" > /opt/backups/secrets/client01.rest-http.pass
chmod 600 /opt/backups/secrets/client01.rest-http.pass

# Добавление пользователя в rest-server
htpasswd -b /opt/backups/auth/restic.htpasswd client01 $(cat /opt/backups/secrets/client01.rest-http.pass)
```

### 6. Запуск клиента

**Linux:**

```bash
cd /opt/backups/client
python3.8 cerber.py &

# Для автозапуска добавьте в systemd
sudo systemctl enable backups-client
sudo systemctl start backups-client
```

**Windows:**

Создайте службу Windows или используйте планировщик задач:

```powershell
# Запуск через PowerShell (тестовый режим)
cd C:\ProgramData\backups\client
python cerber.py

# Для production настройте как службу Windows NSSM или аналогичным инструментом
```

---

## Быстрый старт

### 1. Первый запуск сервера

```bash
cd /workspace/backups
source venv/bin/activate

# Инициализация базы данных
python init_db.py

# Запуск всех сервисов (разработка)
./run_server.sh
```

### 2. Добавление первого бэкапа

Создайте конфигурацию бэкапа `/opt/backups/ini/backups/client01.documents.ini`:

```ini
[backup]
client = client01
name = documents
enabled = true

repository = /client01/documents
repository_url = https://backup-srv:8443/client01/documents

schedule = 0 22 * * *

quota_gb = 500

script = /opt/backups/scripts/client01.documents.py
script_mode = file
script_version = 1

retention_days = 31
retention_monthly_months = 12

restic_extra_args = --exclude-caches --exclude-if-present=.nobackup

respect_calendar = true
```

### 3. Доступ к веб-интерфейсу

Откройте браузер и перейдите по адресу: `https://localhost:9443/`

Войдите под учетной записью администратора.

---

## Структура проекта

```
/workspace/backups/
├── api.py              # Сервер управления (FastAPI)
├── interface.py        # Веб-интерфейс
├── models.py           # Модели данных
├── database.py         # Работа с PostgreSQL
├── config.py           # Загрузка конфигурации
├── scheduler.py        # Планировщик задач
├── alerts.py           # Система уведомлений
├── cerber.py           # Клиентский сторожевой процесс
├── manager.py          # Клиентский управляющий агент
├── worker.py           # Клиентский процесс бэкапа
├── init_db.py          # Скрипт инициализации БД
├── run_server.sh       # Скрипт запуска сервера
├── TZ.md               # Техническое задание
└── README.md           # Этот файл
```

---

## Безопасность

- Все соединения используют HTTPS с проверкой сертификатов
- Пароли хранятся в хешированном виде
- Секреты защищены правами доступа 0600
- Аудит всех действий администраторов
- Двухфакторная аутентификация для веб-интерфейса
- Изоляция репозиториев клиентов

---

## Документация

- Полное техническое задание: [TZ.md](TZ.md)
- REST API документация доступна по адресу: `https://localhost:9443/docs` (Swagger UI)

---

## Лицензия

Проект распространяется под лицензией MIT. См. файл [LICENSE](LICENSE).
