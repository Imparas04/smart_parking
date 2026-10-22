from django.conf import settings
from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Profile = apps.get_model('accounts', 'Profile')
    for user in User.objects.filter(profile__isnull=True):
        Profile.objects.create(user=user, role='admin' if user.is_superuser else 'user')


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
