from django.db import migrations, models
import checkpoint.models


def populate_pin_codes(apps, schema_editor):
    BusinessMembership = apps.get_model('checkpoint', 'BusinessMembership')
    used = set()
    for membership in BusinessMembership.objects.all():
        code = checkpoint.models.generate_pin()
        while code in used:
            code = checkpoint.models.generate_pin()
        used.add(code)
        membership.pin_code = code
        membership.save(update_fields=['pin_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('checkpoint', '0008_add_position_to_staff_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='businessmembership',
            name='pin_code',
            field=models.CharField(max_length=6, null=True, blank=True),
        ),
        migrations.RunPython(populate_pin_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='businessmembership',
            name='pin_code',
            field=models.CharField(default=checkpoint.models.generate_pin, max_length=6, unique=True, db_index=True),
        ),
    ]
