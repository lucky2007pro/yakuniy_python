from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0013_bookfavourite'),
    ]

    operations = [
        migrations.AddField(
            model_name='reader',
            name='email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='reader',
            name='notify_email',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='reader',
            name='last_reminder_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
