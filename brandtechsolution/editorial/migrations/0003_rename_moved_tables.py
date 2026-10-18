"""Drop the ``db_table`` overrides of the models folded into ``editorial``.

The tables become ``editorial_<model>``. ALTER TABLE ... RENAME is a metadata
operation on PostgreSQL, so no data is copied. The two TrendTopic indexes keep
the names they were created with in the ``trends`` app and are renamed here to
what the model now generates.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("editorial", "0002_relabel_moved_content_types"),
    ]

    operations = [
        migrations.AlterModelTable(name="trendtopic", table=None),
        migrations.AlterModelTable(name="competitorsource", table=None),
        migrations.AlterModelTable(name="competitorarticle", table=None),
        migrations.AlterModelTable(name="trendprediction", table=None),
        migrations.AlterModelTable(name="researchdossier", table=None),
        migrations.AlterModelTable(name="verifiedfactreport", table=None),
        migrations.AlterModelTable(name="mediaasset", table=None),
        migrations.AlterModelTable(name="contentanalytics", table=None),
        migrations.AlterModelTable(name="feedbacklooprecord", table=None),
        migrations.AlterModelTable(name="approvalnotification", table=None),
        migrations.AlterModelTable(name="publishinglog", table=None),
        migrations.RenameIndex(
            model_name="trendtopic",
            new_name="editorial_t_status_834c4e_idx",
            old_name="trends_tren_status_a3f9d9_idx",
        ),
        migrations.RenameIndex(
            model_name="trendtopic",
            new_name="editorial_t_categor_eab232_idx",
            old_name="trends_tren_categor_c01b0f_idx",
        ),
    ]
