from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0002_player_ladder_position"),
    ]

    operations = [
        migrations.AddField(
            model_name="player",
            name="skip_next_obstacle",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
