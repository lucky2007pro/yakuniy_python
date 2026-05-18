from datetime import timedelta

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def _populate_expires_at(apps, schema_editor):
    """Mavjud bronlar uchun expires_at = reserved_at + 3 kun."""
    Reservation = apps.get_model('api', 'Reservation')
    for r in Reservation.objects.all():
        base = r.reserved_at or timezone.now()
        r.expires_at = base + timedelta(days=3)
        r.save(update_fields=['expires_at'])


def _noop(apps, schema_editor):
    pass


def _default_expiry():
    return timezone.now() + timedelta(days=3)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_issue_is_returned'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='expires_at',
            field=models.DateTimeField(default=_default_expiry),
        ),
        migrations.RunPython(_populate_expires_at, _noop),
    ]
