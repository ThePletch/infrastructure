import os
from contextlib import contextmanager
import email
from email.parser import BytesFeedParser
import email.policy
from email.utils import parseaddr
from itertools import chain
import logging

from aws_lambda_powertools.utilities.data_classes import (
    event_source,
    SESEvent,
)
from aws_lambda_powertools.utilities.data_classes.ses_event import SESMessage
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.session import Session
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from typing import TypedDict

# from mypy_boto3_s3.client import S3Client
# from mypy_boto3_ssm.client import SSMClient
# from mypy_boto3_sesv2.client import SESV2Client
# from mypy_boto3_sesv2.type_defs import SendEmailRequestRequestTypeDef, SendEmailResponseTypeDef

logging.getLogger().setLevel(logging.INFO)

region = os.environ['Region']
sender = os.environ['MailSender']
reject_spam = os.environ['RejectSpam'] == 'true' if 'RejectSpam' in os.environ else False
incoming_email_bucket = os.environ['MailS3Bucket']
incoming_email_prefix = os.environ['MailS3Prefix']
forwarding_config_prefix = os.environ['ForwardingConfigPrefix']
sender_domain = sender.split('@')[1]

# prefixes in AWS SSM where forwarding config is recorded
explicits_prefix = forwarding_config_prefix + '/inboxes'
prefixes_prefix = forwarding_config_prefix + '/inbox-prefixes'
catch_all_path = forwarding_config_prefix + '/catch-all'

client_ssm = Session().client('ssm')
client_s3 = Session().client('s3')
client_ses = Session().client('sesv2', region)


def get_param_config(prefix: str, next_token: str | None = None) -> dict[str, list[str]]:
    if next_token:
        params = client_ssm.get_parameters_by_path(Path=prefix, NextToken=next_token)
    else:
        params = client_ssm.get_parameters_by_path(Path=prefix)

    params_from_this_run = {
        param['Name'].removeprefix(prefix).lstrip('/'): param['Value'].split(',')
        for param
        in params['Parameters']
    }

    if 'NextToken' in params:
        return {
            **get_param_config(prefix, params['NextToken']),
            **params_from_this_run
        }
    return params_from_this_run


class DestinationFinder:
    prefixes: dict[str, list[str]]
    inboxes: dict[str, list[str]]
    catch_all: list[str]

    def __init__(self):
        catch_all = client_ssm.get_parameter(Name=catch_all_path)
        self.catch_all = catch_all['Parameter']['Value'].split(',')

        self.prefixes = get_param_config(prefixes_prefix)
        self.inboxes = get_param_config(explicits_prefix)
        logging.info("Exact matches loaded: " + repr(self.inboxes))
        logging.info("Prefixes loaded: " + repr(self.prefixes))

    def _get_individual_destination(self, inbox: str):
        exact_match = self.inboxes.get(inbox, [])

        prefix_matches = [
            prefix_inboxes
            for prefix, prefix_inboxes
            in self.prefixes.items()
            if inbox.startswith(prefix)
        ]

        destinations = list(chain(exact_match, *prefix_matches))

        logging.info(f"Destinations for {inbox}: " + ", ".join(destinations))

        return destinations

    def get_destinations(self, recipients: list[str]):
        destination_sets = [
            self._get_individual_destination(recipient.removesuffix('@' + sender_domain))
            for recipient in recipients
            if DestinationFinder.email_is_for_target_domain(recipient)
        ]

        destinations = set(list(chain(*destination_sets)))

        return self.catch_all if len(destinations) == 0 else list(destinations)

    @staticmethod
    def email_is_for_target_domain(email: str) -> bool:
        return email.endswith(sender_domain)


S3PathTypedDict = TypedDict('S3PathTypedDict', {
    'Bucket': str,
    'Key': str,
})


def get_message_s3_path(message_id: str) -> S3PathTypedDict:
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
def with_message_from_s3(message_id: str):
    # Read the content of the message to a temp file, return file pointer
    yield client_s3.get_object(**get_message_s3_path(message_id))['Body']


def rewrite_forwarder(email_from: str) -> str:
    alias, address = parseaddr(email_from)
    if alias.strip() != '':
        quote_escaped_alias = alias.replace("\"", "\\\"")
        result = f"\"{quote_escaped_alias}\" <{sender}>"
    elif address.strip() != '':
        result = f"{address} <{sender}>"
    else:
        result = sender

    return result


def create_message(
    email_info: SESMessage,
    msg_stream: StreamingBody,
    destination_finder: DestinationFinder,
):
    # Parse the email body. We unfortunately can't identify/eliminate defects during parsing,
    # e.g. header limits specified in the policy will be ignored.
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
        in email_info.mail.common_headers.get_from
    ]))

    """
    MIME-Version: 1.0; is the only currently valid MIME-Version header.
    Many, many email clients will automatically append this header for standards compliance,
    but unfortunately many of them don't check if it's already there.
    Several SMTP servers (including AWS SES!) will reject emails with multiple MIME-Version headers,
    so we take care of normalizing this to exactly one copy ourselves.
    """
    del mail_object['MIME-Version']
    mail_object.add_header('MIME-Version', '1.0')

    base_from = rewrite_forwarder(email_info.mail.common_headers.get_from[0])

    if email_info.mail.common_headers.sender is not None:
        if len(email_info.mail.common_headers.sender) > 0:
            mail_object.replace_header('Sender', rewrite_forwarder(email_info.mail.common_headers.sender[0]))
        else:
            mail_object.add_header('Sender', rewrite_forwarder('someBODY'))

    if 'Return-Path' in mail_object:
        print(mail_object['Return-Path'])
        if mail_object['Return-Path'] == '<>':
            # handler for bogus return path that failed to parse in SES
            del mail_object['Return-Path']
            mail_object.add_header('Return-Path', sender)
        else:
            mail_object.replace_header('Return-Path', rewrite_forwarder(email_info.mail.common_headers.return_path))
    else:
        mail_object.add_header('Return-Path', sender)

    del mail_object['DKIM-Signature']

    if 'Reply-To' in mail_object and mail_object['Reply-To'].count('@') != 1:
        logging.warning("Replacing invalid Reply-To email address with original sender email.")
        # as always, this is a handler for a nonsense email i received with an invalid reply-to address
        mail_object.replace_header('Reply-To', email_info.mail.common_headers.get_from[0])
    elif 'Reply-To' not in mail_object:
        mail_object.add_header('Reply-To', email_info.mail.common_headers.get_from[0])

    logging.info("Finding destinations for original target(s): " + ", ".join(email_info.mail.common_headers.to))
    recipients = destination_finder.get_destinations(email_info.mail.common_headers.to)

    logging.info("Sending email to addresses: " + ", ".join(recipients))
    return {
        "FromEmailAddress": base_from,
        "Destination": {
            'ToAddresses': recipients,
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
        if 'Error' in e.response and 'Message' in e.response['Error']:
            logging.error(f"Failed to send email: {e.response['Error']['Message']}")
        else:
            logging.error("Failed to send email, but no error message provided.")
        logging.warning(e.response)
        logging.warning(message)

        raise e

    return "Email sent! Message ID: " + response['MessageId']


def is_spam(email_info: SESMessage) -> bool:
    receipt = email_info.receipt

    for verdict_name, verdict in {
        'spam_verdict': receipt.spam_verdict,
        'virus_verdict': receipt.virus_verdict,
    }.items():
        if verdict.status not in ["PASS", "DISABLED"] and reject_spam:
            logging.info(f"Failed verdict: {verdict_name}")
            logging.debug(email_info)
            return True

    return False


# Send a bare-bones email in the event that we either cannot or will not forward the triggering
# email, e.g. it was identified as spam or we encountered an error
def send_fallback_email(
    message_id: str,
    original_sender: str,
    recipients: list[str],
    reason: str,
    original_subject: str,
):
    return client_ses.send_email(
        FromEmailAddress=sender,
        Destination={
            'ToAddresses': recipients,
        },
        Content={
            'Simple': {
                'Subject': {
                    'Data': f"Rejected email from {original_sender} ({reason})",
                },
                'Body': {
                    'Text': {
                        'Data': f"Rejected subject: {original_subject}\nID: {message_id}"
                    }
                }
            }
        }
    )


@event_source(data_class=SESEvent)
def lambda_handler(event: SESEvent, context: LambdaContext):
    # Get the unique ID of the message. This corresponds to the name of the file
    # in S3.
    email_info = next(event.records).ses
    try:
        # configure destination finder separately from our main email setup logic so that it's guaranteed
        # to be in scope if there's errors down the line.
        destination_finder = DestinationFinder()
    except Exception:
        logging.error("Exception configuring destination finder.")
        raise

    message_id = email_info.mail.message_id
    try:
        logging.info(f"Received message ID {message_id}")
        if is_spam(email_info):
            logging.info("Rejecting identified spam/virus email.")
            _ = send_fallback_email(
                message_id,
                email_info.mail.common_headers.get_from[0],
                destination_finder.catch_all,
                'spam/virus',
                email_info.mail.common_headers.subject
            )
            _ = client_ses.send_email(
                FromEmailAddress=sender,
                Destination={
                    'ToAddresses': destination_finder.catch_all,
                },
                Content={
                    'Simple': {
                        'Subject': {
                            'Data': f"Rejected spam/virus email from {email_info.mail.common_headers.get_from}",
                        },
                        'Body': {
                            'Text': {
                                'Data': f"Rejected subject: {email_info.mail.common_headers.subject}\nID: {message_id}"
                            }
                        }
                    }
                }
            )
            return

        # Retrieve the file from the S3 bucket.
        with with_message_from_s3(message_id) as message_stream:
            # Create the message.
            message = create_message(email_info, message_stream, destination_finder)

        # Send the email and print the result.
        result = send_email(message)

        # if we get here, the email was sent successfully, so we'll blow away the raw email from S3.
        _ = client_s3.delete_object(**get_message_s3_path(message_id))

        logging.debug(result)
    except Exception:
        logging.debug("Logging complete incoming event for debugging:")
        logging.error(event)
        _ = send_fallback_email(
            message_id,
            email_info.mail.common_headers.get_from[0],
            destination_finder.catch_all,
            'forward error',
            email_info.mail.common_headers.subject
        )
        raise
