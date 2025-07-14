# account/migrations/0028_populate_username_field.py

import uuid

from django.db import migrations

def gen_username():
    return f"user_{uuid.uuid4().hex[:10]}"

def populate_usernames(apps, schema_editor):
    User = apps.get_model('account', 'User')
    for user in User.objects.all():
        user.username = gen_username()
        user.save(update_fields=['username'])

class Migration(migrations.Migration):

    dependencies = [
        ('account', '0027_user_username_alter_user_phone_number'),
    ]

    operations = [
        migrations.RunPython(populate_usernames, reverse_code=migrations.RunPython.noop),
    ]
