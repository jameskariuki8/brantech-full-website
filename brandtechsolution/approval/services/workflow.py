"""
Module 10: Human Approval Workflow

Prepares articles in HTML, Markdown, DOCX, and PDF export formats.
Notifies editors via Email, Telegram, and WhatsApp webhooks.
Enables editor actions: Approve, Reject, Edit, Request Rewrite, Generate New Version.
Only approved content proceeds to publication.
"""
import logging
import io
import docx
from typing import Dict, Any
from django.core.mail import send_mail
from django.conf import settings
from editorial.models import EditorialArticle
from approval.models import ApprovalNotification
from staff.emails import capability_holder_emails
from brandtechsolution.config import config

logger = logging.getLogger(__name__)


class HumanApprovalWorkflow:
    """Manages editorial review, multi-format export, and notification dispatch."""

    def notify_editors(self, article: EditorialArticle) -> bool:
        """Notifies editors via configured channels that a draft is ready for review."""
        logger.info(f"[HumanApprovalWorkflow] Dispatching editor review notifications for '{article.title}'...")

        article.status = 'review_pending'
        article.save()

        preview_summary = (
            f"📰 NEW DRAFT FOR REVIEW: {article.title}\n"
            f"Category: {article.topic.category if article.topic else 'General'}\n"
            f"Readability Score: {article.estimated_reading_difficulty} | Est. Time: {article.reading_time_minutes} mins\n"
            f"Summary: {article.executive_summary[:200]}...\n\n"
            f"Review & Approve on Dashboard: {config.site_base_url}/editorial/dashboard/"
        )

        # Email Notification
        try:
            # Addressed to whoever currently holds publish_blog -- the people
            # who can actually approve this draft -- rather than a configured
            # inbox. Granting or revoking the capability in the panel changes
            # who gets told, with nothing to keep in step by hand.
            #
            # It was previously gated on config.email_host_user, which is empty
            # on a Mailgun deployment: the notification would have stopped
            # going out with no error.
            recipients = capability_holder_emails('publish_blog')
            if not recipients and settings.EDITORIAL_REVIEW_EMAIL:
                # Nobody holds it yet (a fresh deployment). Fall back so the
                # first drafts are not reviewed by nobody.
                recipients = [settings.EDITORIAL_REVIEW_EMAIL]

            if recipients:
                send_mail(
                    subject=f"[Teklora Editorial Review] {article.title}",
                    message=preview_summary,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipients,
                    fail_silently=True
                )
            else:
                logger.warning(
                    "[HumanApprovalWorkflow] No publish_blog holder has an "
                    "email address; article #%s is awaiting review with "
                    "nobody notified.",
                    article.id,
                )
        except Exception as e:
            logger.warning(f"Email dispatch warning: {e}")

        # Log Notification Record
        ApprovalNotification.objects.create(
            article=article,
            channel='dashboard',
            payload={"summary": preview_summary, "status": "review_pending"},
            is_sent=True
        )

        logger.info(f"[HumanApprovalWorkflow] Notifications dispatched for Article #{article.id}")
        return True

    def export_as_docx(self, article: EditorialArticle) -> bytes:
        """Exports article as Microsoft Word DOCX document."""
        doc = docx.Document()
        doc.add_heading(article.title, 0)
        doc.add_paragraph(f"Subtitle: {article.subtitle}")
        doc.add_paragraph(f"Target Audience: {article.get_target_audience_display()} | Reading Time: {article.reading_time_minutes} mins")
        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(article.executive_summary)

        doc.add_heading("Introduction", level=1)
        doc.add_paragraph(article.introduction)

        doc.add_heading("Technical Deep Dive", level=1)
        doc.add_paragraph(article.technical_explanation)

        doc.add_heading("African Ecosystem Perspective", level=1)
        doc.add_paragraph(article.african_perspective)

        doc.add_heading("Conclusion", level=1)
        doc.add_paragraph(article.conclusion)

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    def export_as_html(self, article: EditorialArticle) -> str:
        """Formats article into styled HTML preview."""
        return f"""
        <article class="teklora-preview">
            <h1>{article.title}</h1>
            <p class="subtitle"><em>{article.subtitle}</em></p>
            <div class="exec-summary"><strong>Executive Summary:</strong> {article.executive_summary}</div>
            <hr/>
            <section><h2>Introduction</h2><p>{article.introduction}</p></section>
            <section><h2>Problem Statement</h2><p>{article.problem_statement}</p></section>
            <section><h2>Technical Deep Dive</h2><p>{article.technical_explanation}</p></section>
            <section><h2>African Perspective</h2><p>{article.african_perspective}</p></section>
            <section><h2>Strategic Outlook</h2><p>{article.future_predictions}</p></section>
            <section><h2>Conclusion</h2><p>{article.conclusion}</p></section>
        </article>
        """

    def approve_article(self, article: EditorialArticle, editor_notes: str = "") -> EditorialArticle:
        """Approves draft article for automatic publishing."""
        article.status = 'approved'
        if editor_notes:
            article.editor_notes = editor_notes
        article.save()
        logger.info(f"[HumanApprovalWorkflow] APPROVED Article #{article.id}: '{article.title}'")
        return article

    def reject_article(self, article: EditorialArticle, reason: str = "") -> EditorialArticle:
        """Rejects draft article."""
        article.status = 'rejected'
        if reason:
            article.editor_notes = f"Rejected: {reason}"
        article.save()
        logger.info(f"[HumanApprovalWorkflow] REJECTED Article #{article.id}")
        return article
