from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_reader_auth_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReaderLibraryCard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('card_image', models.ImageField(upload_to='reader_library_cards/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('library', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reader_cards', to='api.library')),
                ('reader', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='library_cards', to='api.reader')),
            ],
        ),
        migrations.AddConstraint(
            model_name='readerlibrarycard',
            constraint=models.UniqueConstraint(fields=('reader', 'library'), name='unique_reader_library_card'),
        ),
    ]
