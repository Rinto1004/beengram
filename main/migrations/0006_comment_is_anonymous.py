# Generated by Django 5.1.4 on 2025-01-25 10:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0005_comment'),
    ]

    operations = [
        migrations.AddField(
            model_name='comment',
            name='is_anonymous',
            field=models.BooleanField(default=False),
        ),
    ]
