from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_emailverification_bugreport'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='notify_bug_fix',
            field=models.BooleanField(
                default=True,
                help_text='Send an email when a bug the user reported is fixed (GitHub issue closed).',
            ),
        ),
    ]
