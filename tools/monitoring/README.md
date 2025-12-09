# Monitoring Tools

Инструменты мониторинга для Google Search AI Mode системы.

## Структура

```
tools/monitoring/
├── monitor-workers.sh          # Основной скрипт мониторинга воркеров
├── systemd/
│   └── worker-monitor.service  # Systemd сервис для автозапуска
└── README.md                   # Эта документация
```

## Использование

### Запуск мониторинга
```bash
# Из корня проекта
./tools/monitoring/monitor-workers.sh

# С кастомными параметрами
CHECK_INTERVAL=30 ./tools/monitoring/monitor-workers.sh
```

### Установка как системный сервис
```bash
# Копировать файл сервиса
sudo cp tools/monitoring/systemd/worker-monitor.service /etc/systemd/system/

# Активировать сервис
sudo systemctl daemon-reload
sudo systemctl enable worker-monitor
sudo systemctl start worker-monitor

# Проверить статус
sudo systemctl status worker-monitor

# Просмотр логов
sudo journalctl -u worker-monitor -f
```

## Функции

- **Автоматическое обнаружение** всех запущенных браузер-воркеров
- **Health check** каждого воркера через healthcheck.py
- **Автоматический перезапуск** упавших воркеров
- **Логирование** всех операций с временными метками
- **Graceful restart** с проверкой восстановления

## Переменные окружения

- `CHECK_INTERVAL` - интервал проверки в секундах (по умолчанию: 60)
- `DOCKER_COMPOSE_FILE` - путь к docker-compose.yml (по умолчанию: docker-compose.yml)

## Интеграция с Docker Health Checks

Этот внешний мониторинг дополняет встроенные Docker health checks:
- Docker health checks: быстрые проверки каждые 30с
- External monitor: глубокие проверки каждые 60с с принудительным перезапуском