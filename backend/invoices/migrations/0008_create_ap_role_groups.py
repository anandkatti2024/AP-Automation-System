from django.db import migrations


ROLE_GROUPS = ["AP Clerk", "Approver", "Payment Clerk", "Administrator"]


def create_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    database = schema_editor.connection.alias
    for role_name in ROLE_GROUPS:
        Group.objects.using(database).get_or_create(name=role_name)


def remove_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    database = schema_editor.connection.alias
    Group.objects.using(database).filter(name__in=ROLE_GROUPS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0007_invoicepayment"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_role_groups, remove_role_groups),
    ]
