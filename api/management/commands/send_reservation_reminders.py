"""
Bron muddati tugashiga 1 kun qolgan o'quvchilarga email yuborish.
Cron orqali har kuni soat 09:00 da chaqirib turing:

    0 9 * * * cd /var/www/tatu && /usr/bin/env python manage.py send_reservation_reminders
"""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Reservation


REMINDER_TEMPLATE = """\
Salom, {name}!

Sizning bronlangan kitobingiz haqida eslatma:

📚 Kitob: {book_title}
🏛  Kutubxona: {library_name}
⏳ Muddat tugashi: {expires_at:%Y-%m-%d %H:%M}
🕒 Qolgan vaqt: {hours_left} soat

Iltimos, kitobni o'z vaqtida olib keting yoki bronni bekor qiling.

Bron sahifasi: {site_url}/kabinet

Hurmat bilan,
TATU Kutubxona
"""


class Command(BaseCommand):
    help = "Bron muddati 24 soat ichida tugaydigan o'quvchilarga email yuboradi."

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Necha soat oldin yubord (default: 24)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Email yubormay, faqat ekranga chiqar',
        )

    def handle(self, *args, **options):
        hours = options['hours']
        dry   = options['dry_run']

        now = timezone.now()
        deadline = now + timedelta(hours=hours)

        # Yaqin orada tugaydigan bronlar (hali tugamagan)
        reservations = (
            Reservation.objects
            .filter(expires_at__gt=now, expires_at__lte=deadline)
            .select_related('reader', 'book', 'book__library')
        )

        sent = 0
        skipped = 0

        for res in reservations:
            reader = res.reader
            if not reader.email:
                skipped += 1
                continue
            if not getattr(reader, 'notify_email', True):
                skipped += 1
                continue

            # 1 sutkada bir martadan ko'p eslatma yubormaymiz
            if reader.last_reminder_sent_at and (now - reader.last_reminder_sent_at).total_seconds() < 22 * 3600:
                skipped += 1
                continue

            hours_left = max(0, int((res.expires_at - now).total_seconds() // 3600))
            body = REMINDER_TEMPLATE.format(
                name=reader.fullname,
                book_title=res.book.title if res.book else '—',
                library_name=res.book.library.name if (res.book and res.book.library) else '—',
                expires_at=res.expires_at,
                hours_left=hours_left,
                site_url=getattr(settings, 'SITE_URL', ''),
            )
            subject = f"⏳ Bron muddati yaqinlashmoqda — {res.book.title if res.book else 'kitob'}"

            if dry:
                self.stdout.write(self.style.WARNING(
                    f"[DRY] {reader.email} ← {subject}"
                ))
            else:
                try:
                    send_mail(
                        subject=subject,
                        message=body,
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                        recipient_list=[reader.email],
                        fail_silently=False,
                    )
                    reader.last_reminder_sent_at = now
                    reader.save(update_fields=['last_reminder_sent_at'])
                    sent += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ {reader.email} ← {res.book.title if res.book else ''}"
                    ))
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(self.style.ERROR(
                        f"✗ {reader.email}: {exc}"
                    ))

        self.stdout.write(self.style.SUCCESS(
            f"Tugadi: yuborilgan={sent}, o'tkazib yuborilgan={skipped}"
        ))
