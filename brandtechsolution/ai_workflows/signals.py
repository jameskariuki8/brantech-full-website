"""Keep the site's corpus current as its content changes.

`harness/indexing.py` was written in step 2 with the save hook it describes
and never connected to one, so `BlogPost` and `Project` were indexed only by
whoever remembered to run a management command. This is the connection.

Two rules that the old path got for free and this one has to state:

**Drafts stay out.** The legacy retriever embedded every post and filtered
`status='published'` at query time. `MemoryDocument` has no status column, so
that filter cannot live at query time any more -- and pushing it to write time
is the safer half of the trade anyway, because an unpublished draft is then
not in the corpus at all rather than one forgotten filter away from being
quoted back to a visitor.

**Withdrawal is a write.** A deleted or unpublished row has to be actively
removed. `MemoryDocument` addresses its object through a content type and an
id rather than a foreign key, so nothing cascades: without this the assistant
would go on answering from content that was taken down.
"""
import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ai_workflows.harness.indexing import forget, index_on_save

logger = logging.getLogger(__name__)


def _publishable(instance):
    """Whether this row is something a visitor is allowed to be told about.

    Models without a `status` are publishable by definition -- `Project` has
    no draft state, and inventing one here would be a policy this module is
    not entitled to set.
    """
    status = getattr(instance, "status", None)
    return status is None or status == "published"


@receiver(post_save, sender="brand.BlogPost", dispatch_uid="index_blog_post")
def index_blog_post(sender, instance, **kwargs):
    if _publishable(instance):
        index_on_save(instance, kind="blog_post", text_field="content")
    else:
        # Unpublishing has to remove it, not merely stop refreshing it.
        forget(instance)


@receiver(post_save, sender="brand.Project", dispatch_uid="index_project")
def index_project(sender, instance, **kwargs):
    index_on_save(instance, kind="project", text_field="description")


@receiver(post_delete, sender="brand.BlogPost", dispatch_uid="forget_blog_post")
@receiver(post_delete, sender="brand.Project", dispatch_uid="forget_project")
def forget_deleted(sender, instance, **kwargs):
    forget(instance)
