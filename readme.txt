# Job Monitor 🚀

Автоматический мониторинг вакансий с отправкой уведомлений в Telegram.

## Возможности

- 📥 Парсинг вакансий из RSS-лент и HTML-страниц
- 🔍 Фильтрация по ключевым словам
- 🗄️ Сохранение в SQLite с дедупликацией
- 📱 Дайджест вакансий в одном сообщении Telegram
- ⏰ Планирование задач (каждый час + ежедневный отчет)
- ⚙️ Настраиваемый формат дайджеста
- 🚀 Готов к деплою на Railway

## Формат дайджеста

Теперь приложение отправляет **один дайджест** вместо множества отдельных сообщений:

```
📊 Дайджест вакансий за 11.07.2025

🔍 Просмотрено: 145 вакансий
➕ Найдено новых: 12
📤 В дайджесте: 12
⏰ Время: 09:00:15

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📂 HackerNews Jobs (5 вакансий)
1. [Senior Python Developer](https://example.com/job1) 🌍 Remote 🏢 Tech Corp
2. [Backend Engineer](https://example.com/job2) 🌍 Berlin 🏢 Startup Inc
3. [Full Stack Developer](https://example.com/job3) 🌍 New York
...

📂 RemoteOK (7 вакансий)
1. [Python Developer](https://example.com/job4) 🌍 Remote 🏢 Remote Co
2. [Django Developer](https://example.com/job5) 🌍 Remote
...
```

## Установка

1. Клонируйте репозиторий
2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Настройте переменные окружения:
```bash
cp .env.example .env
# Отредактируйте .env файл
```

4. Получите токен Telegram Bot:
   - Напишите @BotFather в Telegram
   - Создайте нового бота командой `/newbot`
   - Получите токен и добавьте в `.env`

5. Получите Chat ID:
   - Добавьте бота в чат/группу
   - Отправьте сообщение боту
   - Перейдите по ссылке: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Найдите `chat.id` в ответе

## Использование

### Ручной запуск
```bash
# Сканирование и отправка отчета
python main.py

# Только сканирование
python main.py --scan

# Только отправка отчета
python main.py --report

# Запуск в режиме демона
python main.py --daemon
```

### Автоматический режим
```bash
# Запуск планировщика
python main.py --daemon
```

## Конфигурация

### resources.json
Список источников вакансий:
```json
[
  {
    "name": "HackerNews Jobs",
    "type": "rss",
    "url": "https://hnrss.org/jobs"
  },
  {
    "name": "Custom Site",
    "type": "html",
    "url": "https://example.com/jobs",
    "selectors": {
      "container": ".job-item",
      "title": ".job-title",
      "link": ".job-link",
      "company": ".company-name",
      "location": ".job-location"
    }
  }
]
```

### keywords.json
Список ключевых слов для фильтрации:
```json
[
  "python",
  "django",
  "remote",
  "junior",
  "senior"
]
```

### config.json
Настройки приложения:
```json
{
  "telegram": {
    "digest_format": "grouped",
    "max_jobs_per_source": 10,
    "show_stats": true,
    "show_company": true,
    "show_location": true,
    "include_description": false
  },
  "scheduler": {
    "scan_interval_hours": 1,
    "report_time": "09:00",
    "timezone": "UTC"
  },
  "database": {
    "cleanup_days": 30,
    "max_jobs_per_source": 1000
  }
}
```

#### Параметры конфигурации:

**telegram:**
- `digest_format`: формат дайджеста ("grouped" - по источникам)
- `max_jobs_per_source`: максимум вакансий на источник в дайджесте
- `show_stats`: показывать статистику в дайджесте
- `show_company`: показывать название компании
- `show_location`: показывать местоположение
- `include_description`: включать краткое описание

**scheduler:**
- `scan_interval_hours`: интервал сканирования в часах
- `report_time`: время отправки ежедневного отчета
- `timezone`: часовой пояс

**database:**
- `cleanup_days`: удалять записи старше N дней
- `max_jobs_per_source`: максимум записей на источник
[
  "python",
  "django",
  "remote",
  "junior",
  "senior"
]
```

## Деплой на Railway

1. Создайте проект на Railway
2. Подключите GitHub репозиторий
3. Добавьте переменные окружения:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Railway автоматически запустит приложение

## Логирование

Логи сохраняются в:
- `job_monitor.log` - файл логов
- `stdout` - консольный вывод

## Структура проекта

```
job-monitor/
├── main.py              # Основное приложение
├── requirements.txt     # Зависимости Python
├── resources.json       # Конфигурация источников
├── keywords.json        # Ключевые слова
├── .env.example        # Пример переменных окружения
├── Procfile            # Конфигурация для Railway
├── README.md           # Документация
└── jobs.db             # SQLite база данных (создается автоматически)
```

## Функции

### DatabaseManager
- Создание и управление SQLite базой данных
- Дедупликация по хешу `title|link|source`
- Отслеживание отправленных сообщений

### JobParser
- Парсинг RSS-лент
- Парсинг HTML с настраиваемыми селекторами
- Асинхронная обработка

### JobFilter
- Фильтрация по ключевым словам
- Поиск без учета регистра
- Проверка в title, description, tags

### TelegramBot
- Отправка сообщений в Markdown формате
- Ограничение длины сообщений (4096 символов)
- Защита от дублирования отправок

### JobMonitor
- Координация всех компонентов
- Планирование задач
- Сбор статистики

## Примеры использования

### Добавление нового RSS источника
```json
{
  "name": "My RSS Feed",
  "type": "rss",
  "url": "https://example.com/jobs.rss"
}
```

### Добавление HTML источника
```json
{
  "name": "Custom Jobs Site",
  "type": "html",
  "url": "https://jobs.example.com",
  "selectors": {
    "container": ".vacancy-card",
    "title": ".vacancy-title",
    "link": ".vacancy-link",
    "company": ".company-name",
    "location": ".job-location"
  }
}
```

## Troubleshooting

### Проблема: Не приходят уведомления
- Проверьте правильность `TELEGRAM_BOT_TOKEN` и `