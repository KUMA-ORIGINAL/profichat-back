# account/migrations/0029_make_username_unique.py

import django.contrib.auth.validators
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('account', '0028_populate_username_field'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(
                max_length=150,
                unique=True,
                null=False,
                blank=False,
                verbose_name='username',
                help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.',
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                error_messages={'unique': 'A user with that username already exists.'},
            ),
        ),
    ]
