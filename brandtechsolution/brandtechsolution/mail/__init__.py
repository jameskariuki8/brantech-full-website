"""Themed transactional mail.

Deliberately not inside `messaging/`. That app is the bulk campaign system --
an outbox drained on a Beat interval, suppression lists, unsubscribe tokens --
and none of that belongs on an alert. An alert must never acquire an
unsubscribe link or be dropped by a suppression list, and it must not queue
behind a send to four thousand recipients.

It borrows two functions from there rather than reimplementing them:
`inline_email_css`, because Outlook and Gmail ignore <style> blocks, and
`html_to_text` for the plain-text alternative.
"""
from brandtechsolution.mail.shell import render_mail, send_mail_html

__all__ = ["render_mail", "send_mail_html"]
