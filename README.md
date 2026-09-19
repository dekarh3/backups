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

```text
┌──────────────┐      HTTPS      ┌─────────────────────────────────────┐
│   Клиент     │ ◄─────────────► │           СХД-сервер                │
│  (Windows/   │                 │  ┌─────────────┐  ┌───────────────┐ │
│   Linux)     │                 │  │ rest-server │  │   api.py      │ │
│  - cerber.py │                 │  │  (порт 8444)│  │  (порт 9443)  │ │
│  - manager.py│                 │  └─────────────┘  └───────────────┘ │
│  - worker.py │                 │  ┌─────────────┐  ┌───────────────┐ │
│  - restic    │                 │  │interface.py │  │  PostgreSQL   │ │
└──────────────┘                 │  │  (веб-UI)   │  │               │ │
                                 │  └─────────────┘  └───────────────┘ │
                                 └─────────────────────────────────────┘
```

**Компоненты сервера:**
- `rest-server` — HTTPS-сервер для приема данных от restic (порт 8444)
- `api.py` — FastAPI сервер управления, планировщик, очередь команд (порт 9443)
- `interface.py` — Веб-интерфейс администратора (SSR на Jinja2)
- `PostgreSQL` — Хранилище оперативного состояния системы

**Компоненты клиента:**
- `cerber.py` — Сторожевой процесс
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

### 1. Подготовка пользователя и установка зависимостей

Все процессы сервера должны выполняться от имени выделенного системного пользователя без права интерактивного входа.

```bash
# Создание системного пользователя backup-srv (без права логина)
sudo useradd -r -s /sbin/nologin -d /opt/backups backup-srv

# Обновление системы и установка базовых зависимостей
sudo dnf update -y
sudo dnf install -y python3.8 python3.8-pip python3.8-devel postgresql postgresql-server git httpd-tools policycoreutils-python-utils

# Установка rest-server (версия 0.14.0)
cd /tmp
wget https://github.com/restic/rest-server/releases/download/v0.14.0/rest-server_0.14.0_linux_amd64.tar.gz
tar -xzf rest-server_0.14.0_linux_amd64.tar.gz --wildcards --strip-components=1 '*/rest-server'
sudo mv rest-server /usr/local/bin/rest-server
sudo chmod +x /usr/local/bin/rest-server
rm -f rest-server_0.14.0_linux_amd64.tar.gz

# Настройка SELinux для исполняемого файла rest-server
sudo semanage fcontext -a -t bin_t /usr/local/bin/rest-server
sudo restorecon -v /usr/local/bin/rest-server

# Создание директорий
sudo mkdir -p /opt/backups/{ini,secrets,keys,scripts,auth}
sudo mkdir -p /srv/backups/restic
sudo mkdir -p /var/log/backups
sudo mkdir -p /backup_cache

# Назначение прав доступа пользователю backup-srv
sudo chown -R backup-srv:backup-srv /opt/backups
sudo chown -R backup-srv:backup-srv /srv/backups/restic
sudo chown -R backup-srv:backup-srv /var/log/backups
sudo chown -R backup-srv:backup-srv /backup_cache
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
CREATE USER backups WITH PASSWORD '<ПАРОЛЬ backups>';
CREATE DATABASE backups OWNER backups;
GRANT ALL PRIVILEGES ON DATABASE backups TO backups;
EOF
```

### 3. Генерация ключей и секретов

```bash
# Генерация ключа подписи (выполняется от имени backup-srv)
sudo -u backup-srv openssl genrsa -out /opt/backups/keys/backups.key 2048
sudo chmod 600 /opt/backups/keys/backups.key

# Ограничение доступа к директории секретов
sudo chmod 700 /opt/backups/secrets
```

### 4. Развертывание кода

Скопируйте файлы проекта из репозитория в рабочую директорию:

```bash
# Создание директории для кода
sudo mkdir -p /opt/backups/code

# Копирование всех файлов из репозитория
sudo cp -r /path/to/repo/server/* /opt/backups/code/
sudo cp -r /path/to/repo/client/* /opt/backups/code/  # если нужна клиентская часть
sudo cp /path/to/repo/*.md /opt/backups/code/  # документация
sudo cp /path/to/repo/*.ini /opt/backups/code/  # шаблоны конфигов

# Назначение прав доступа
sudo chown -R backup-srv:backup-srv /opt/backups/code
sudo chmod 750 /opt/backups/code
sudo chmod 640 /opt/backups/code/*.py
sudo chmod 750 /opt/backups/code/*.sh
```

*Замените `/path/to/repo` на фактический путь к клонированному репозиторию.*

**Проверка:** Убедитесь, что в `/opt/backups/code` присутствуют необходимые файлы:
```bash
ls -la /opt/backups/code/
# Должны быть: api.py, rest_server_wrapper.py, и другие файлы проекта
```

### 5. Конфигурация

Создайте основной файл конфигурации `/opt/backups/ini/backups.ini` (владелец `backup-srv`):

```ini
[global]
base_url = https://localhost:8444
api_url = https://localhost:9443
restic_root = /srv/backups/restic

db_dsn = host=127.0.0.1 port=5432 dbname=backups user=backups password=<ПАРОЛЬ backups>

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

### 6. Установка Python-зависимостей

```bash
# Подготовка рабочей директории (предполагается, что код находится в /opt/backups/code)
sudo mkdir -p /opt/backups/code
sudo chown -R backup-srv:backup-srv /opt/backups/code
cd /opt/backups/code

# Создание виртуального окружения от имени backup-srv
sudo -u backup-srv python3.8 -m venv venv

# Установка зависимостей
sudo -u backup-srv venv/bin/pip install --upgrade pip
sudo -u backup-srv venv/bin/pip install fastapi uvicorn[standard] psycopg2-binary jinja2 python-multipart pydantic cryptography python-jose passlib htpasswd
```

### 7. Настройка SSL-сертификатов

Для работы в production необходим SSL-сертификат. Для тестирования можно создать самоподписанный:

```bash
sudo -u backup-srv openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /opt/backups/keys/server.key \
  -out /opt/backups/keys/server.crt \
  -subj "/CN=backup-srv"

sudo chmod 600 /opt/backups/keys/server.key
sudo chmod 644 /opt/backups/keys/server.crt
```

### 8. Настройка политик SELinux

Для корректной работы сервисов в среде с включенным SELinux (Enforcing) необходимо настроить контексты безопасности и разрешить использование сетевых портов.

```bash
# Назначение контекстов для директорий хранения и логов
sudo semanage fcontext -a -t var_lib_t "/srv/backups/restic(/.*)?"
sudo restorecon -Rv /srv/backups/restic

sudo semanage fcontext -a -t etc_t "/opt/backups(/.*)?"
sudo restorecon -Rv /opt/backups

sudo semanage fcontext -a -t var_log_t "/var/log/backups(/.*)?"
sudo restorecon -Rv /var/log/backups

# Регистрация нестандартных портов как HTTP-портов
sudo semanage port -a -t http_port_t -p tcp 8444
sudo semanage port -a -t http_port_t -p tcp 9443

# Разрешение сетевых подключений для веб-сервисов и БД
sudo setsebool -P httpd_can_network_connect 1
sudo setsebool -P httpd_can_network_connect_db 1
```

### 9. Запуск сервисов

#### Запуск rest-server

```bash
# Создание файла аутентификации
sudo -u backup-srv htpasswd -cb /opt/backups/auth/restic.htpasswd admin <ПАРОЛЬ admin>

# Тестовый запуск от имени backup-srv
sudo -u backup-srv /usr/local/bin/rest-server --append-only --private-repos \
  --path /srv/backups/restic \
  --htpasswd-file /opt/backups/auth/restic.htpasswd
  --tls --tls-cert /opt/backups/keys/server.crt \
  --tls-key /opt/backups/keys/server.key \
  --listen :8444
```

#### Запуск api.py

```bash
cd /opt/backups/code

# Тестовый запуск API сервера от имени backup-srv
sudo -u backup-srv venv/bin/uvicorn api:app --host 0.0.0.0 --port 9443 \
  --ssl-keyfile /opt/backups/keys/server.key \
  --ssl-certfile /opt/backups/keys/server.crt
```

*Примечание: Для production-среды настоятельно рекомендуется настроить unit-файлы `systemd` с параметрами `User=backup-srv` и `Group=backup-srv` для автоматического запуска сервисов при старте системы.*

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

### 1. Установка зависимостей

**Linux:**
```bash
# Создание изолированного пользователя для клиента
sudo useradd -r -s /sbin/nologin -d /opt/backups/client backup-cli

# Установка Python и restic
sudo dnf install -y python3.8 python3.8-pip

wget https://github.com/restic/restic/releases/download/v0.19.1/restic_0.19.1_linux_amd64
sudo mv restic_0.19.1_linux_amd64 /usr/local/bin/restic
sudo chmod +x /usr/local/bin/restic
```

**Windows:**
```powershell
# Скачать и установить Python 3.8 с https://www.python.org/downloads/

# Скачать restic 0.15.2
wget https://github.com/restic/restic/releases/download/v0.15.2/restic_0.15.2_windows_amd64.exe
Move-Item restic_0.15.2_windows_amd64.exe C:\ProgramData\restic\restic.exe

# Добавить в PATH
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\ProgramData\restic", "Machine")
```

### 2. Установка клиентских скриптов

Скопируйте клиентские скрипты из репозитория:

**Linux:**
```bash
sudo mkdir -p /opt/backups/client
sudo cp cerber.py manager.py worker.py /opt/backups/client/
sudo chown -R backup-cli:backup-cli /opt/backups/client
```

**Windows:**
```powershell
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
server_rest_url = https://backup-srv:8444

agent_token_file = /opt/backups/secrets/agent.token
ca_cert_file = /opt/backups/keys/ca.crt

timezone = Europe/Moscow
log_dir = /var/log/backups_client
```

**Важно для Linux:** Создайте директорию для логов и передайте права пользователю `backup-cli`:
```bash
sudo mkdir -p /var/log/backups_client
sudo chown -R backup-cli:backup-cli /var/log/backups_client
```

### 4. Получение токена аутентификации

Токен аутентификации клиента генерируется на сервере и должен быть размещен в файле, указанном в конфигурации.

На сервере выполните:

```bash
# Генерация токена для клиента
python3.8 -c "import secrets; print(secrets.token_hex(32))" > /opt/backups/secrets/client01.agent.token
sudo chown backup-srv:backup-srv /opt/backups/secrets/client01.agent.token
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

rest_server_base_url = https://backup-srv:8444
rest_http_user = client01
rest_http_password_file = /opt/backups/secrets/client01.rest-http.pass

client_public_key_file = /opt/backups/keys/clients/client01.pub
client_agent_token_file = /opt/backups/secrets/client01.agent.token

timezone = Europe/Moscow
```

Сгенерируйте пароль для rest-server:

```bash
# Генерация пароля
python3.8 -c "import secrets; print(secrets.token_urlsafe(32))" > /opt/backups/secrets/client01.rest-http.pass
sudo chown backup-srv:backup-srv /opt/backups/secrets/client01.rest-http.pass
chmod 600 /opt/backups/secrets/client01.rest-http.pass

# Добавление пользователя в rest-server
sudo -u backup-srv htpasswd -b /opt/backups/auth/restic.htpasswd client01 $(cat /opt/backups/secrets/client01.rest-http.pass)
```

### 6. Запуск клиента

**Linux:**

```bash
# Тестовый запуск от имени пользователя backup-cli
sudo -u backup-cli python3.8 /opt/backups/client/cerber.py &

# Для автозапуска создайте systemd unit (User=backup-cli)
sudo systemctl enable backups-client
sudo systemctl start backups-client
```

**Windows:**

Для обеспечения безопасности создайте выделенную локальную учетную запись (например, `svc_backup`), запретите ей локальный вход (Deny log on locally) и разрешите вход в качестве службы (Log on as a service).

```powershell
# Настройка службы через NSSM (Non-Sucking Service Manager)
nssm install BackupsClient "C:\Python38\python.exe" "C:\ProgramData\backups\client\cerber.py"
nssm set BackupsClient AppDirectory "C:\ProgramData\backups\client"
nssm set BackupsClient ObjectName ".\svc_backup" "Password"
nssm start BackupsClient
```

---

## Быстрый старт

### 1. Первый запуск сервера

```bash
cd /opt/backups/code

# Инициализация базы данных (от имени backup-srv)
sudo -u backup-srv venv/bin/python init_db.py

# Запуск всех сервисов (разработка)
sudo -u backup-srv ./run_server.sh
```

### 2. Добавление первого бэкапа

Создайте конфигурацию бэкапа `/opt/backups/ini/backups/client01.documents.ini` (не забудьте назначить владельца `backup-srv`):

```ini
[backup]
client = client01
name = documents
enabled = true

repository = /client01/documents
repository_url = https://backup-srv:8444/client01/documents

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

```text
/opt/backups/code/
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
- **Принцип наименьших привилегий:** процессы сервера и клиента выполняются от изолированных системных пользователей без права интерактивного входа (`/sbin/nologin`)
- **SELinux:** настроены строгие политики мандатного контроля доступа для файлов, портов и сетевых взаимодействий

---

## Документация

- Полное техническое задание: [TZ.md](TZ.md)
- REST API документация доступна по адресу: `https://localhost:9443/docs` (Swagger UI)

---

## Лицензия

Проект распространяется под лицензией GNU GPL v3. См. файл [LICENSE]
