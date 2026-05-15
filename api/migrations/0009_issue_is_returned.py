from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0008_readerlibrarycard_is_approved'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='is_returned',
            field=models.BooleanField(default=False),
        ),
    ]
