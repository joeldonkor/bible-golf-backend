from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("decks", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="card",
            name="card_tone",
            field=models.CharField(
                choices=[("positive", "Positive"), ("negative", "Negative")],
                default="positive",
                max_length=10,
            ),
        ),
    ]
