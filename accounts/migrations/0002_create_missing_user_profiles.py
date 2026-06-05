from django.db import migrations


def create_missing_user_profiles(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')

    existing_user_ids = set(UserProfile.objects.values_list('user_id', flat=True))
    missing_profiles = [
        UserProfile(user_id=user_id)
        for user_id in User.objects.values_list('id', flat=True)
        if user_id not in existing_user_ids
    ]
    UserProfile.objects.bulk_create(missing_profiles, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_missing_user_profiles, noop_reverse),
    ]
