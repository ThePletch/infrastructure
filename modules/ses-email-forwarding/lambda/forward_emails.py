import os
from contextlib import contextmanager
import email
from email.parser import BytesFeedParser
import email.policy
from email.utils import parseaddr
import logging

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.DEBUG)

region = os.environ['Region']
sender = os.environ['MailSender']
recipient = os.environ['MailRecipient']

client_s3 = boto3.client('s3')
client_ses = boto3.client('sesv2', region)


class NonsenseEmailException(Exception):
    pass


def get_message_s3_path(message_id):
    incoming_email_bucket = os.environ['MailS3Bucket']
    incoming_email_prefix = os.environ['MailS3Prefix']

    if incoming_email_prefix:
        object_path = (incoming_email_prefix + "/" + message_id)
    else:
        object_path = message_id

    # Get the email object from the S3 bucket.
    return {
        'Bucket': incoming_email_bucket,
        'Key': object_path,
    }


@contextmanager
def with_message_from_s3(message_id):
    # Read the content of the message to a temp file, return file pointer
    yield client_s3.get_object(**get_message_s3_path(message_id))['Body']


def rewrite_forwarder(email_from):
    alias, address = parseaddr(email_from)
    if alias.strip() != '':
        quote_escaped_alias = alias.replace("\"", "\\\"")
        result = f"\"{quote_escaped_alias}\" <{sender}>"
    elif address.strip() != '':
        result = f"{address} <{sender}>"
    else:
        result = sender

    return result


def create_message(email_info, msg_stream):
    # Parse the email body.
    parser = BytesFeedParser(policy=email.policy.SMTPUTF8.clone(refold_source='none'))
    try:
        while chunk := msg_stream.next():
            parser.feed(chunk)
    except StopIteration:
        pass
    mail_object = parser.close()
    # Add subject, from and to lines.
    mail_object.replace_header('From', ";".join([
        rewrite_forwarder(from_email)
        for from_email
        in email_info['mail']['commonHeaders']['from']
    ]))

    base_from = rewrite_forwarder(email_info['mail']['commonHeaders']['from'][0])

    if 'sender' in email_info['mail']['commonHeaders']:
        mail_object.replace_header('Sender', rewrite_forwarder(email_info['mail']['commonHeaders']['sender']))

    if 'returnPath' in email_info['mail']['commonHeaders']:
        mail_object.replace_header('Return-Path', rewrite_forwarder(email_info['mail']['commonHeaders']['returnPath']))
    elif 'Return-Path' in mail_object and mail_object['Return-Path'] == '<>':
        # handler for bogus return path that failed to parse in SES
        del mail_object['Return-Path']

    del mail_object['DKIM-Signature']

    if 'Reply-To' not in mail_object:
        mail_object.add_header('Reply-To', email_info['mail']['commonHeaders']['from'][0])

    return {
        "FromEmailAddress": base_from,
        "Destination": {
            'ToAddresses': [recipient],
        },
        "Content": {
            'Raw': {"Data": mail_object.as_string()}
        },
    }


def send_email(message):
    # Send the email.
    try:
        # Provide the contents of the email.
        response = client_ses.send_email(**message)

    # Display an error if something goes wrong.
    except ClientError as e:
        logging.error(f"Failed to send email: {e.response['Error']['Message']}")
        logging.warning(e.response)
        logging.warning(message)

        raise e

    return "Email sent! Message ID: " + response['MessageId']


def is_spam(email_info):
    receipt = email_info['receipt']

    for verdict in ('spamVerdict', 'virusVerdict'):
        if verdict in receipt and receipt[verdict]['status'] not in ["PASS", "DISABLED"]:
            logging.info(f"Failed verdict: {verdict}")
            logging.debug(email_info)
            return True

    return False


def lambda_handler(event, context):
    try:
        # Get the unique ID of the message. This corresponds to the name of the file
        # in S3.
        email_info = event['Records'][0]['ses']
        message_id = email_info['mail']['messageId']
        logging.info(f"Received message ID {message_id}")
        if is_spam(email_info):
            logging.info("Rejecting identified spam/virus email.")
            client_ses.send_email(
                FromEmailAddress=sender,
                Destination={
                    'ToAddresses': [recipient],
                },
                Content={
                    'Simple': {
                        'Subject': {
                            'Data': f"Rejected spam/virus email from {email_info['mail']['commonHeaders']['from'][0]}",
                        },
                        'Body': {
                            'Text': {
                                'Data': f"Rejected subject: {email_info['mail']['commonHeaders']['subject']}\nID: {message_id}"
                            }
                        }
                    }
                }
            )
            return

        # Retrieve the file from the S3 bucket.
        with with_message_from_s3(message_id) as message_stream:
            # Create the message.
            message = create_message(email_info, message_stream)

        # Send the email and print the result.
        result = send_email(message)

        # if we get here, the email was sent successfully, so we'll blow away the raw email from S3.
        client_s3.delete_object(**get_message_s3_path(message_id))

        logging.debug(result)
    except Exception:
        logging.debug("Logging complete incoming event for debugging:")
        logging.error(event)
        raise
