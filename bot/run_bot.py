import asyncio
import logging
import os
from pathlib import Path
import sys
import threading
import time

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vogapp.settings")

import django  # noqa: E402

django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.conf import settings  # noqa: E402
from django.db.models import Count  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import UserProfile  # noqa: E402
from notifications.telegram_utils import notify_new_results  # noqa: E402
from races.models import Race, RaceSubscription  # noqa: E402
from races.scraper import RaceScraper  # noqa: E402
from races.sync import scrape_and_sync_results  # noqa: E402

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_subscribed_upcoming_races():
    today = timezone.localdate()
    return (
        Race.objects.filter(date__gte=today)
        .annotate(subscription_count=Count("subscriptions"))
        .filter(subscription_count__gt=0)
        .order_by("date", "external_id")
    )


def poll_once(scraper: RaceScraper) -> None:
    races = list(get_subscribed_upcoming_races())
    if not races:
        logger.debug("No subscribed upcoming races to poll.")
        return

    logger.info("Polling %s subscribed upcoming races.", len(races))
    for race in races:
        try:
            new_results, synced_count = scrape_and_sync_results(scraper, race)
            if new_results:
                sent_count = notify_new_results(race, new_results)
                logger.info(
                    "Race %s: synced %s results, %s new, sent %s Telegram messages.",
                    race.external_id,
                    synced_count,
                    len(new_results),
                    sent_count,
                )
            else:
                logger.debug("Race %s: synced %s results, no new results.", race.external_id, synced_count)
        except Exception:
            logger.exception("Polling failed for race %s.", race.external_id)


def run_polling_loop() -> None:
    interval = int(getattr(settings, "SCRAPER_POLL_INTERVAL", 180))
    logger.info("Starting race result polling loop every %s seconds.", interval)
    with RaceScraper() as scraper:
        while True:
            try:
                poll_once(scraper)
            except Exception:
                logger.exception("Unexpected polling cycle failure.")
            time.sleep(interval)


def _profile_for_chat(chat_id: int, username: str | None) -> UserProfile | None:
    chat_id_value = str(chat_id)
    profile = UserProfile.objects.select_related("user").filter(telegram_chat_id=chat_id_value).first()
    if profile:
        return profile

    if username:
        clean_username = username.lstrip("@")
        profile = (
            UserProfile.objects.select_related("user")
            .filter(telegram_username__iexact=clean_username)
            .first()
        )
        if profile:
            profile.telegram_chat_id = chat_id_value
            if not profile.telegram_username:
                profile.telegram_username = clean_username
            profile.save(update_fields=["telegram_chat_id", "telegram_username"])
            return profile

    return None


def _handle_start(chat_id: int, username: str | None) -> str:
    profile = _profile_for_chat(chat_id, username)
    if not profile:
        return (
            "Non riesco a collegare questo account Telegram a un utente VogApp. "
            "Chiedi a un coach di inserire il tuo username Telegram nel tuo profilo."
        )

    return (
        f"Account Telegram collegato a {profile.user.username}. "
        "Usa /status per vedere le iscrizioni, /calendar per le regate, "
        "/subscribe <reg_id> per iscriverti e /unsubscribe <reg_id> per disiscriverti."
    )


def _handle_status(chat_id: int, username: str | None) -> str:
    profile = _profile_for_chat(chat_id, username)
    if not profile:
        return "Account Telegram non collegato. Usa /start dopo aver configurato il profilo."

    subscriptions = (
        RaceSubscription.objects.filter(user=profile.user)
        .select_related("race")
        .order_by("race__date", "race__external_id")
    )
    if not subscriptions:
        return "Non hai iscrizioni attive."

    lines = ["Iscrizioni attive:"]
    for subscription in subscriptions:
        race = subscription.race
        date_label = race.date.strftime("%d/%m/%Y") if race.date else "data da definire"
        lines.append(f"- {race.external_id} - {race.name or 'Regata'} ({date_label})")
    return "\n".join(lines)


def _handle_calendar() -> str:
    today = timezone.localdate()
    races = Race.objects.filter(date__gte=today).order_by("date", "external_id")[:20]
    if not races:
        return "Nessuna regata futura nel database. Riprova dopo l'aggiornamento del calendario."

    lines = ["Prossime regate:"]
    for race in races:
        date_label = race.date.strftime("%d/%m/%Y") if race.date else "data da definire"
        lines.append(f"- {race.external_id} - {race.name or 'Regata'} ({date_label})")
    lines.append("Usa /subscribe <reg_id> per iscriverti.")
    return "\n".join(lines)


def _handle_subscribe(chat_id: int, username: str | None, reg_id: str) -> str:
    profile = _profile_for_chat(chat_id, username)
    if not profile:
        return "Account Telegram non collegato. Usa /start dopo aver configurato il profilo."
    if not reg_id:
        return "Uso: /subscribe <reg_id>"

    race = Race.objects.filter(external_id__iexact=reg_id.strip()).first()
    if not race:
        return f"Regata {reg_id} non trovata nel database."

    _subscription, created = RaceSubscription.objects.get_or_create(user=profile.user, race=race)
    if created:
        return f"Iscrizione attivata per {race.name or race.external_id}."
    return f"Eri gia iscritto a {race.name or race.external_id}."


def _handle_unsubscribe(chat_id: int, username: str | None, reg_id: str) -> str:
    profile = _profile_for_chat(chat_id, username)
    if not profile:
        return "Account Telegram non collegato. Usa /start dopo aver configurato il profilo."
    if not reg_id:
        return "Uso: /unsubscribe <reg_id>"

    race = Race.objects.filter(external_id__iexact=reg_id.strip()).first()
    if not race:
        return f"Regata {reg_id} non trovata nel database."

    deleted, _ = RaceSubscription.objects.filter(user=profile.user, race=race).delete()
    if deleted:
        return f"Iscrizione rimossa per {race.name or race.external_id}."
    return f"Non eri iscritto a {race.name or race.external_id}."


def _handle_stop(chat_id: int, username: str | None) -> str:
    profile = _profile_for_chat(chat_id, username)
    if not profile:
        return "Account Telegram non collegato."

    deleted, _ = RaceSubscription.objects.filter(user=profile.user).delete()
    if deleted:
        return f"Ho rimosso {deleted} iscrizioni."
    return "Non avevi iscrizioni attive."


async def run_aiogram_command_handlers(token: str) -> None:
    try:
        from aiogram import Bot, Dispatcher, Router
        from aiogram.filters import Command
        from aiogram.types import Message
    except ImportError:
        logger.warning("aiogram is not installed; Telegram command handlers are disabled.")
        while True:
            await asyncio.sleep(3600)

    bot = Bot(token=token)
    dispatcher = Dispatcher()
    router = Router()

    def identity(message: Message) -> tuple[int, str | None]:
        username = message.from_user.username if message.from_user else None
        return message.chat.id, username

    def command_argument(message: Message) -> str:
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        chat_id, username = identity(message)
        response = await sync_to_async(_handle_start, thread_sensitive=True)(chat_id, username)
        await message.answer(response)

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        chat_id, username = identity(message)
        response = await sync_to_async(_handle_status, thread_sensitive=True)(chat_id, username)
        await message.answer(response)

    @router.message(Command("calendar"))
    async def calendar(message: Message) -> None:
        response = await sync_to_async(_handle_calendar, thread_sensitive=True)()
        await message.answer(response)

    @router.message(Command("subscribe"))
    async def subscribe(message: Message) -> None:
        chat_id, username = identity(message)
        response = await sync_to_async(_handle_subscribe, thread_sensitive=True)(
            chat_id,
            username,
            command_argument(message),
        )
        await message.answer(response)

    @router.message(Command("unsubscribe"))
    async def unsubscribe(message: Message) -> None:
        chat_id, username = identity(message)
        response = await sync_to_async(_handle_unsubscribe, thread_sensitive=True)(
            chat_id,
            username,
            command_argument(message),
        )
        await message.answer(response)

    @router.message(Command("stop"))
    async def stop(message: Message) -> None:
        chat_id, username = identity(message)
        response = await sync_to_async(_handle_stop, thread_sensitive=True)(chat_id, username)
        await message.answer(response)

    dispatcher.include_router(router)

    try:
        logger.info("Starting aiogram command handlers.")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_TOKEN", "")
    if token:
        polling_thread = threading.Thread(target=run_polling_loop, name="race-result-poller", daemon=True)
        polling_thread.start()
        asyncio.run(run_aiogram_command_handlers(token))
    else:
        logger.info("No Telegram bot token configured; running polling loop only.")
        run_polling_loop()


if __name__ == "__main__":
    main()

