# -*- coding: utf-8 -*-
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from email.utils import make_msgid
from html2text import html2text
from plone.server import app_settings
from pserver.mailer.interfaces import IMailer
from repoze.sendmail import encoding
from zope.interface import implementer
from plone.server.async import QueueUtility

import aiosmtplib
import asyncio
import logging
import smtplib


logger = logging.getLogger(__name__)


@implementer(IMailer)
class MailerUtility(QueueUtility):

    def __init__(self, settings):
        super(MailerUtility, self).__init__(self, settings)
        self.smtp_mailer = self.get_smtp_mailer()

    @property
    def settings(self):
        return app_settings['mailer']

    async def _send(self, sender, recipients, message):
        return await self.smtp_mailer.sendmail(sender, recipients, message)

    def get_smtp_mailer(self):
        mailer_settings = self.settings
        host = mailer_settings.get('host', 'localhost')
        port = mailer_settings.get('port', 25)
        self._exceptions = False
        return aiosmtplib.SMTP(hostname=host, port=port)

    async def connect(self):
        return await self.smtp_mailer.connect()

    async def initialize(self, app):
        self.app = app
        await self.connect()
        while True:
            got_obj = False
            try:
                priority, args = await self._queue.get()
                got_obj = True
                try:
                    await self._send(*args)
                except Exception as exc:
                    logger.error('Error sending mail', exc_info=True)
            except KeyboardInterrupt or MemoryError or SystemExit or asyncio.CancelledError:
                self._exceptions = True
                raise
            except:  # noqa
                self._exceptions = True
                logger.error('Worker call failed', exc_info=True)
            finally:
                if got_obj:
                    self._queue.task_done()

    def build_message(self, message, text=None, html=None):
        if not text and html and self.settings.get('use_html2text', True):
            try:
                text = html2text(html)
            except:
                pass

        if text is not None:
            message.attach(MIMEText(text, 'plain'))
        if html is not None:
            message.attach(MIMEText(html, 'html'))

    def get_message(self, recipient, subject, sender,
                    message=None, text=None, html=None):
        if message is None:
            message = MIMEMultipart('alternative')
            self.build_message(message, text, html)

        message['Subject'] = subject
        message['From'] = sender
        message['To'] = recipient
        return message

    async def send(self, recipient=None, subject=None, message=None,
                   text=None, html=None, sender=None, priority=3):
        if sender is None:
            sender = self.settings.get('default_sender')
        message = self.get_message(recipient, subject, sender, message, text, html)
        await self._queue.put((priority, (sender, [recipient], message)))

    async def send_immediately(self, recipient=None, subject=None, message=None,
                               text=None, html=None, sender=None, fail_silently=False):
        if sender is None:
            sender = self.settings.get('default_sender')
        message = self.get_message(recipient, subject, sender, message, text, html)
        encoding.cleanup_message(message)
        messageid = message['Message-Id']
        if messageid is None:
            messageid = message['Message-Id'] = make_msgid('repoze.sendmail')
        if message['Date'] is None:
            message['Date'] = formatdate()

        try:
            return await self._send(sender, [recipient], message)
        except smtplib.socket.error:
            if not fail_silently:
                raise


@implementer(IMailer)
class PrintingMailerUtility(MailerUtility):

    def __init__(self, settings):
        self._queue = asyncio.Queue()

    async def connect(self):
        pass

    async def _send(self, sender, recipients, message):
        print('DEBUG MAILER: \n {}'.format(message.as_string()))
