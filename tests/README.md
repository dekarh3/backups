# Тестирование

## Запуск тестов

### Unit-тесты
```bash
# Запустить все тесты
python -m pytest tests/ -v

# Запустить только unit-тесты API
python -m pytest tests/test_api.py -v

# Запустить только unit-тесты Worker
python -m pytest tests/test_worker.py -v

# Запустить integration-тесты
python -m pytest tests/test_integration.py -v
```

### Параметры запуска
```bash
# Запуск с покрытием кода
python -m pytest tests/ --cov=server --cov=client --cov-report=html

# Запуск быстрых тестов (исключая медленные)
python -m pytest tests/ -v -m "not slow"

# Запуск тестов с выводом логов
python -m pytest tests/ -v -s

# Запуск конкретного теста
python -m pytest tests/test_api.py::TestConfig::test_config_get_existing -v
```

## Структура тестов

- `tests/test_api.py` - Unit-тесты для API сервера (FastAPI)
  - Тесты конфигурации
  - Тесты Pydantic моделей (Command, BackupStatus, ClientStatus)
  - Тесты endpoints (root, health, clients)
  - Тесты ротации секретов

- `tests/test_worker.py` - Unit-тесты для Backup Worker
  - Тесты инициализации worker
  - Тесты загрузки конфигурации
  - Тесты обработки путей
  - Тесты работы с учётными данными
  - Тесты отправки прогресса и результатов
  - Тесты остановки backup процесса

- `tests/test_integration.py` - Integration-тесты
  - Тесты потока команд API
  - Тесты ротации секретов
  - Тесты конфигурации бэкапов
  - Тесты статусов клиентов
  - Тесты health check endpoints
  - Тесты очереди команд
  - End-to-end сценарии бэкапа

- `tests/conftest.py` - Общие фикстуры и конфигурация pytest
  - Фикстуры для временных директорий
  - Фикстуры для тестовых конфигураций
  - Маркеры для категоризации тестов

## Требования для тестирования

```bash
pip install pytest pytest-asyncio fastapi httpx uvicorn
```

## Статус тестов

Все тесты проходят успешно:
- ✅ 16 unit-тестов API
- ✅ 14 unit-тестов Worker  
- ✅ 9 integration-тестов
- 📊 Всего: 39 тестов
