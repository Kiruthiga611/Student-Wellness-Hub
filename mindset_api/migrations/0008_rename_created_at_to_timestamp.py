# Generated migration to fix the timestamp column issue

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mindset_api', '0007_academicevent'),
    ]

    operations = [
        migrations.RenameField(
            model_name='moodentry',
            old_name='created_at',
            new_name='timestamp',
        ),
    ]
