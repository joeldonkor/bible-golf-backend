from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="player",
            name="ladder_position",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
