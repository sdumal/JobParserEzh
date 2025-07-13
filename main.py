#!/usr/bin/env python3
"""
Job Monitor - Мониторинг вакансий с отправкой в Telegram
Автор: Assistant
"""

import os
import json
import sqlite3
import logging
import asyncio
import argparse
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import schedule
import time
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('job_monitor.log')
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class Job:
    """Структура данных для вакансии"""
    title: str
    description: str
    link: str
    source: str
    location: str = ""
    company: str = ""
    tags: str = ""
    published: Optional[datetime] = None
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь для сохранения в БД"""
        data = asdict(self)
        if self.published:
            data['published'] = self.published.isoformat()
        if self.created_at:
            data['created_at'] = self.created_at.isoformat()
        return data
    
    def get_hash(self) -> str:
        """Получение уникального хеша для дедупликации"""
        unique_string = f"{self.title}|{self.link}|{self.source}"
        return hashlib.md5(unique_string.encode()).hexdigest()

class JobLocationFilter:
    """Фильтр вакансий по местоположению"""

    def __init__(self, allowed_locations: List[str]):
        # Приводим все разрешенные локации к нижнему регистру для удобства сравнения
        self.allowed_locations = [loc.lower() for loc in allowed_locations]

    def is_location_allowed(self, job: Job) -> bool:
        location = (job.location or '').lower()
        return any(allowed in location for allowed in self.allowed_locations)

class DatabaseManager:
    """Менеджер базы данных SQLite"""
    
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    link TEXT NOT NULL,
                    source TEXT NOT NULL,
                    location TEXT,
                    company TEXT,
                    tags TEXT,
                    published TEXT,
                    created_at TEXT NOT NULL,
                    hash TEXT UNIQUE NOT NULL,
                    sent_to_telegram BOOLEAN DEFAULT FALSE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON jobs(hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON jobs(created_at)")
            conn.commit()
    
    def add_job(self, job: Job) -> bool:
        """Добавление вакансии в БД. Возвращает True если добавлена, False если дубликат"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                job_data = job.to_dict()
                job_data['hash'] = job.get_hash()
                
                conn.execute("""
                    INSERT INTO jobs (title, description, link, source, location, 
                                    company, tags, published, created_at, hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_data['title'], job_data['description'], job_data['link'],
                    job_data['source'], job_data['location'], job_data['company'],
                    job_data['tags'], job_data['published'], job_data['created_at'],
                    job_data['hash']
                ))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # Дубликат - уже существует
            return False
    
    def get_new_jobs(self, hours: int = 24) -> List[Job]:
        """Получение новых вакансий за последние N часов"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM jobs 
                WHERE created_at > ? AND sent_to_telegram = FALSE
                ORDER BY created_at DESC
            """, (cutoff_time.isoformat(),))
            
            jobs = []
            for row in cursor.fetchall():
                job = Job(
                    title=row['title'],
                    description=row['description'],
                    link=row['link'],
                    source=row['source'],
                    location=row['location'],
                    company=row['company'],
                    tags=row['tags'],
                    published=datetime.fromisoformat(row['published']) if row['published'] else None,
                    created_at=datetime.fromisoformat(row['created_at'])
                )
                jobs.append(job)
            
            return jobs
    
    def mark_as_sent(self, job_hashes: List[str]):
        """Отметить вакансии как отправленные в Telegram"""
        with sqlite3.connect(self.db_path) as conn:
            for job_hash in job_hashes:
                conn.execute("UPDATE jobs SET sent_to_telegram = TRUE WHERE hash = ?", (job_hash,))
            conn.commit()

class JobParser:
    """Парсер вакансий из различных источников"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def parse_rss(self, url: str, source_name: str) -> List[Job]:
        """Парсинг RSS-ленты"""
        try:
            async with self.session.get(url) as response:
                content = await response.text()
                
            feed = feedparser.parse(content)
            jobs = []
            
            for entry in feed.entries:
                job = Job(
                    title=entry.get('title', ''),
                    description=entry.get('description', ''),
                    link=entry.get('link', ''),
                    source=source_name,
                    published=datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') and entry.published_parsed else None
                )
                jobs.append(job)
            
            return jobs
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS {url}: {e}")
            return []
    
    async def parse_html(self, url: str, source_name: str, selectors: Dict[str, str]) -> List[Job]: 
    #"""Парсинг HTML-страницы с кастомными селекторами (адаптировано под DOU)"""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"}
            async with self.session.get(url, headers=headers) as response:
                content = await response.text()

            soup = BeautifulSoup(content, 'html.parser')
            jobs = []

            # Поиск контейнеров с вакансиями
            job_containers = soup.select(selectors.get('container', '.vacancy'))

            for container in job_containers:
                title_elem = container.select_one(selectors.get('title', 'div.title a.vt'))
                link_elem = title_elem  # В DOU ссылка в том же элементе, что и заголовок
                desc_elem = container.select_one(selectors.get('description', 'div.sh-info'))
                company_elem = desc_elem  # В DOU описание содержит и компанию
                location_elem = container.select_one(selectors.get('location', 'span.cities'))

                if title_elem and link_elem:
                    job = Job(
                        title=title_elem.get_text(strip=True),
                        description=desc_elem.get_text(strip=True) if desc_elem else '',
                        link=urljoin(url, link_elem.get('href', '')),
                        source=source_name,
                        company=company_elem.get_text(strip=True).split('—')[0] if company_elem else '',
                        location=location_elem.get_text(strip=True) if location_elem else ''
                    )
                    jobs.append(job)

            logger.info(f"{len(jobs)} вакансий найдено на {source_name}")
            return jobs

        except Exception as e:
            logger.error(f"Ошибка парсинга HTML {url}: {e}")
            return []


class JobFilter:
    """Фильтр вакансий по ключевым словам"""
    
    def __init__(self, keywords: List[str]):
        self.keywords = [kw.lower() for kw in keywords]
    
    def matches(self, job: Job) -> bool:
        """Проверка соответствия вакансии ключевым словам"""
        text_to_check = f"{job.title} {job.description} {job.tags}".lower()
        return any(keyword in text_to_check for keyword in self.keywords)

class TelegramBot:
    """Клиент для отправки сообщений в Telegram"""
    
    def __init__(self, token: str, chat_id: str, config: Dict = None):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.max_message_length = 4096
        self.config = config or {}
    
    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Отправка сообщения в Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        return True
                    else:
                        logger.error(f"Ошибка отправки в Telegram: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения в Telegram: {e}")
            return False
    
    def format_job_message(self, job: Job) -> str:
        """Форматирование сообщения о вакансии"""
        location = f" 🌍 {job.location}" if job.location else ""
        company = f" 🏢 {job.company}" if job.company else ""
        
        message = f"💼 *{job.title}*{location}{company}\n🔗 [Открыть вакансию]({job.link})"
        
        # Ограничение длины сообщения
        if len(message) > 4000:
            message = message[:4000] + "..."
        
        return message
    
    def create_digest(self, jobs: List[Job], stats: Dict) -> str:
        """Создание дайджеста с вакансиями"""
        if not jobs:
            return "📋 Новых вакансий за последние 24 часа не найдено."
        
        # Заголовок дайджеста
        header = f"""📊 *Дайджест вакансий за {datetime.now().strftime('%d.%m.%Y')}*

"""
        
        # Статистика (если включена в конфигурации)
        if self.config.get('show_stats', True):
            header += f"""🔍 Просмотрено: {stats['total_viewed']} вакансий
➕ Найдено новых: {stats['total_added']}
📤 В дайджесте: {len(jobs)}
⏰ Время: {stats['start_time'].strftime('%H:%M:%S')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
        
        # Группировка вакансий по источникам
        jobs_by_source = {}
        for job in jobs:
            if job.source not in jobs_by_source:
                jobs_by_source[job.source] = []
            jobs_by_source[job.source].append(job)
        
        # Формирование дайджеста
        digest_parts = [header]
        max_jobs_per_source = self.config.get('max_jobs_per_source', 10)
        
        for source, source_jobs in jobs_by_source.items():
            source_section = f"📂 *{source}* ({len(source_jobs)} вакансий)\n"
            
            # Ограничиваем количество вакансий на источник
            displayed_jobs = source_jobs[:max_jobs_per_source]
            
            for i, job in enumerate(displayed_jobs, 1):
                location = ""
                company = ""
                
                if self.config.get('show_location', True) and job.location:
                    location = f" 🌍 {job.location}"
                
                if self.config.get('show_company', True) and job.company:
                    company = f" 🏢 {job.company}"
                
                job_line = f"{i}. [{job.title}]({job.link}){location}{company}\n"
                
                # Добавляем описание если включено
                if self.config.get('include_description', False) and job.description:
                    desc_preview = job.description[:100] + "..." if len(job.description) > 100 else job.description
                    job_line += f"   _{desc_preview}_\n"
                
                # Проверяем, не превысит ли добавление этой вакансии лимит
                test_digest = "".join(digest_parts) + source_section + job_line
                if len(test_digest) > self.max_message_length - 200:  # Оставляем запас
                    if len(source_jobs) > len(displayed_jobs):
                        source_section += f"   ... и еще {len(source_jobs) - i + 1} вакансий\n"
                    break
                else:
                    source_section += job_line
            
            # Показываем сколько вакансий скрыто
            if len(source_jobs) > max_jobs_per_source:
                hidden_count = len(source_jobs) - max_jobs_per_source
                source_section += f"   ... и еще {hidden_count} вакансий\n"
            
            source_section += "\n"
            digest_parts.append(source_section)
            
            # Проверяем общий размер
            if len("".join(digest_parts)) > self.max_message_length - 200:
                digest_parts.append("📝 *Дайджест сокращен из-за ограничений Telegram*")
                break
        
        return "".join(digest_parts)
    
    async def send_digest(self, digest: str) -> bool:
        """Отправка дайджеста, разбивая на части если необходимо"""
        if len(digest) <= self.max_message_length:
            return await self.send_message(digest)
        
        # Если дайджест слишком длинный, разбиваем на части
        success_count = 0
        parts = self.split_digest(digest)
        
        for i, part in enumerate(parts):
            part_header = f"📋 *Дайджест ({i+1}/{len(parts)})*\n\n" if len(parts) > 1 else ""
            message = part_header + part
            
            if await self.send_message(message):
                success_count += 1
            
            await asyncio.sleep(1)  # Задержка между сообщениями
        
        return success_count == len(parts)
    
    def split_digest(self, digest: str) -> List[str]:
        """Разбиение дайджеста на части по источникам"""
        parts = []
        current_part = ""
        
        lines = digest.split('\n')
        
        for line in lines:
            test_part = current_part + line + '\n'
            
            if len(test_part) > self.max_message_length - 200:
                if current_part:
                    parts.append(current_part.strip())
                    current_part = line + '\n'
                else:
                    # Если даже одна строка слишком длинная
                    parts.append(line[:self.max_message_length - 200] + "...")
                    current_part = ""
            else:
                current_part = test_part
        
        if current_part:
            parts.append(current_part.strip())
        
        return parts

class JobMonitor:
    """Основной класс мониторинга вакансий"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.load_config()
        self.telegram_bot = TelegramBot(
            token=os.getenv('TELEGRAM_BOT_TOKEN'),
            chat_id=os.getenv('TELEGRAM_CHAT_ID'),
            config=self.config.get('telegram', {})
        )
        self.job_filter = JobFilter(self.keywords)
        self.location_filter = JobLocationFilter(["gdansk", "remote", "poland"])
        self.stats = {
            'total_viewed': 0,
            'total_added': 0,
            'start_time': datetime.now()
        }
    
    def load_config(self):
        """Загрузка конфигурации из файлов"""
        try:
            with open('resources.json', 'r', encoding='utf-8') as f:
                self.resources = json.load(f)
        except FileNotFoundError:
            logger.warning("Файл resources.json не найден. Используется пустой список.")
            self.resources = []
        
        try:
            with open('keywords.json', 'r', encoding='utf-8') as f:
                self.keywords = json.load(f)
        except FileNotFoundError:
            logger.warning("Файл keywords.json не найден. Используется пустой список.")
            self.keywords = []
        
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            logger.warning("Файл config.json не найден. Используется конфигурация по умолчанию.")
            self.config = {
                "telegram": {
                    "digest_format": "grouped",
                    "max_jobs_per_source": 10,
                    "show_stats": True,
                    "show_company": True,
                    "show_location": True,
                    "include_description": False
                },
                "scheduler": {
                    "scan_interval_hours": 1,
                    "report_time": "09:00"
                }
            }
    
    async def scan_all_sources(self):
        """Сканирование всех источников вакансий"""
        logger.info("Начинаю сканирование источников...")
        
        async with aiohttp.ClientSession() as session:
            parser = JobParser(session)
            
            for resource in self.resources:
                try:
                    jobs = []
                    
                    if resource['type'] == 'rss':
                        jobs = await parser.parse_rss(resource['url'], resource['name'])
                    elif resource['type'] == 'html':
                        jobs = await parser.parse_html(
                            resource['url'], 
                            resource['name'], 
                            resource.get('selectors', {})
                        )
                    
                    # Фильтрация и добавление в БД
                    for job in jobs:
                        self.stats['total_viewed'] += 1
                        
                        if self.job_filter.matches(job) and self.location_filter.is_location_allowed(job):
                            if self.db.add_job(job):
                                self.stats['total_added'] += 1
                                logger.info(f"Добавлена вакансия: {job.title}")
                    
                    logger.info(f"Обработан источник {resource['name']}: {len(jobs)} вакансий")
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки источника {resource['name']}: {e}")
        
        logger.info(f"Сканирование завершено. Просмотрено: {self.stats['total_viewed']}, добавлено: {self.stats['total_added']}")
    
    async def send_daily_report(self):
        """Отправка ежедневного отчета в Telegram"""
        logger.info("Отправляю ежедневный отчет...")
        
        new_jobs = self.db.get_new_jobs(24)
        
        if not new_jobs:
            await self.telegram_bot.send_message("📋 Новых вакансий за последние 24 часа не найдено.")
            return
        
        # Создание единого дайджеста
        digest = self.telegram_bot.create_digest(new_jobs, self.stats)
        
        # Отправка дайджеста (может быть разбит на несколько сообщений если слишком длинный)
        sent_successfully = await self.telegram_bot.send_digest(digest)
        
        # Отметить как отправленные если успешно отправлено
        if sent_successfully:
            sent_hashes = [job.get_hash() for job in new_jobs]
            self.db.mark_as_sent(sent_hashes)
            logger.info(f"Дайджест отправлен. Вакансий: {len(new_jobs)}")
        else:
            logger.error("Ошибка отправки дайджеста")

def create_example_configs():
    """Создание примеров конфигурационных файлов"""
    
    # Пример resources.json
    resources_example = [
        {
            "name": "HackerNews Jobs",
            "type": "rss",
            "url": "https://hnrss.org/jobs"
        },
        {
            "name": "Indeed Jobs",
            "type": "html",
            "url": "https://indeed.com/jobs?q=python+developer",
            "selectors": {
                "container": ".job_seen_beacon",
                "title": ".jobTitle a span",
                "link": ".jobTitle a",
                "company": ".companyName",
                "location": ".companyLocation"
            }
        }
    ]
    
    keywords_example = [
        "python", "django", "flask", "remote", "junior", "senior",
        "backend", "fullstack", "developer", "engineer"
    ]
    
    if not os.path.exists('resources.json'):
        with open('resources.json', 'w', encoding='utf-8') as f:
            json.dump(resources_example, f, ensure_ascii=False, indent=2)
        logger.info("Создан файл resources.json")
    
    if not os.path.exists('keywords.json'):
        with open('keywords.json', 'w', encoding='utf-8') as f:
            json.dump(keywords_example, f, ensure_ascii=False, indent=2)
        logger.info("Создан файл keywords.json")
    
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("TELEGRAM_BOT_TOKEN=your_bot_token_here\n")
            f.write("TELEGRAM_CHAT_ID=your_chat_id_here\n")
        logger.info("Создан файл .env")

async def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description='Job Monitor')
    parser.add_argument('--report', action='store_true', help='Отправить ежедневный отчет')
    parser.add_argument('--scan', action='store_true', help='Выполнить сканирование')
    parser.add_argument('--daemon', action='store_true', help='Запустить в режиме демона')
    args = parser.parse_args()
    
    # Создание примеров конфигурации
    create_example_configs()
    
    # Проверка переменных окружения
    if not os.getenv('TELEGRAM_BOT_TOKEN') or not os.getenv('TELEGRAM_CHAT_ID'):
        logger.error("Не настроены переменные окружения TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")
        return
    
    monitor = JobMonitor()
    
    if args.report:
        await monitor.send_daily_report()
    elif args.scan:
        await monitor.scan_all_sources()
    elif args.daemon:
        logger.info("Запуск в режиме демона...")
        
        # Планирование задач
        schedule.every().hour.do(lambda: asyncio.run(monitor.scan_all_sources()))
        schedule.every().day.at("09:00").do(lambda: asyncio.run(monitor.send_daily_report()))
        
        logger.info("Демон запущен. Сканирование каждый час, отчет в 9:00")
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        # Разовое выполнение
        await monitor.scan_all_sources()
        await monitor.send_daily_report()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        import sys
        if str(e).startswith("Event loop is closed") and sys.platform.startswith("win"):
            logger.warning("RuntimeError suppressed: Event loop is closed (Windows quirk)")
        else:
            raise
