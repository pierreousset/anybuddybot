"""Notifications : Telegram (recommandé) et/ou e-mail SMTP."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

import requests


class Notifier:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def send(self, subject: str, body: str) -> None:
        tg = self.cfg.get("telegram") or {}
        if tg.get("bot_token") and tg.get("chat_id"):
            self._telegram(tg, f"*{subject}*\n{body}")
        mail = self.cfg.get("email") or {}
        if mail.get("smtp_host") and mail.get("to"):
            self._email(mail, subject, body)
        if not tg.get("bot_token") and not mail.get("smtp_host"):
            print(f"[NOTIF] {subject}\n{body}")

    @staticmethod
    def _telegram(tg: dict, text: str) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                json={
                    "chat_id": tg["chat_id"],
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[NOTIF] échec Telegram: {e}")

    @staticmethod
    def _email(mail: dict, subject: str, body: str) -> None:
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = mail.get("from", mail["to"])
            msg["To"] = mail["to"]
            with smtplib.SMTP(mail["smtp_host"], mail.get("smtp_port", 587)) as s:
                s.starttls()
                if mail.get("username"):
                    s.login(mail["username"], mail["password"])
                s.send_message(msg)
        except Exception as e:  # noqa: BLE001
            print(f"[NOTIF] échec e-mail: {e}")
