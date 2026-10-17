"""invoice-mailer: emails each new invoice to its customer.

billing-job announces `invoice.created`; this function fetches the PDF from company files and sends it through
the mail provider. It only ever reads invoices.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

INVOICES_BUCKET = os.environ["INVOICES_BUCKET"]
SMTP_SECRET = os.environ["SMTP_SECRET"]

_s3 = boto3.client("s3")
_sm = boto3.client("secretsmanager")


def _smtp() -> dict[str, str]:
    return json.loads(_sm.get_secret_value(SecretId=SMTP_SECRET)["SecretString"])


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    sent = 0
    settings = _smtp()
    for record in event.get("Records", []):
        invoice = json.loads(record["Sns"]["Message"])
        pdf = _s3.get_object(Bucket=INVOICES_BUCKET, Key=f"invoices/{invoice['order_id']}.pdf")["Body"].read()
        message = EmailMessage()
        message["To"] = invoice["email"]
        message["Subject"] = f"Your invoice for order {invoice['order_id']}"
        name = f"{invoice['order_id']}.pdf"
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=name)
        with smtplib.SMTP_SSL(settings["host"]) as server:
            server.login(settings["user"], settings["password"])
            server.send_message(message)
        sent += 1
    log.info("sent %d invoice(s)", sent)
    return {"sent": sent}
