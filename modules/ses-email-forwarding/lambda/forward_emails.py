# Copyright 2010-2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# This file is licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License. A copy of the
# License is located at
#
# http://aws.amazon.com/apache2.0/
#
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS
# OF ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import os
import boto3
import email
import re
from botocore.exceptions import ClientError

region = os.environ['Region']


def get_message_from_s3(message_id):
    incoming_email_bucket = os.environ['MailS3Bucket']
    incoming_email_prefix = os.environ['MailS3Prefix']

    if incoming_email_prefix:
        object_path = (incoming_email_prefix + "/" + message_id)
    else:
        object_path = message_id

    # Create a new S3 client.
    client_s3 = boto3.client("s3")

    # Get the email object from the S3 bucket.
    object_s3 = client_s3.get_object(
        Bucket=incoming_email_bucket,
        Key=object_path)
    # Read the content of the message.
    msg_file = object_s3['Body'].read()

    return msg_file


def rewrite_forwarder(email_from):
    if '<' in email_from:
        return re.sub(r"<[^>]*>", f"<{os.environ['MailSender']}>", email_from)
    else:
        return email_from + f" <{os.environ['MailSender']}>"


def create_message(email_info, msg_file):
    sender = os.environ['MailSender']
    recipient = os.environ['MailRecipient']

    # Parse the email body.
    mailobject = email.message_from_string(msg_file.decode('utf-8'))

    # Add subject, from and to lines.
    mailobject.replace_header('From', ";".join([
        rewrite_forwarder(from_email)
        for from_email
        in email_info['mail']['commonHeaders']['from']
    ]))

    mailobject.replace_header('Return-Path', rewrite_forwarder(email_info['mail']['commonHeaders']['returnPath']))

    if 'Reply-To' not in mailobject:
        mailobject.add_header('Reply-To', email_info['mail']['commonHeaders']['from'][0])

    return {
        "Source": sender,
        "Destinations": [recipient],
        "RawMessage": {"Data": mailobject.as_string()}
    }


def send_email(message):
    # Create a new SES client.
    client_ses = boto3.client('ses', region)

    # Send the email.
    try:
        # Provide the contents of the email.
        response = client_ses.send_raw_email(**message)

    # Display an error if something goes wrong.
    except ClientError as e:
        print(f"ERROR! {e.response['Error']['Message']}")
        raise e

    output = "Email sent! Message ID: " + response['MessageId']

    return output


def is_spam(email_info):
    receipt = email_info['receipt']

    for verdict in ('spamVerdict', 'virusVerdict'):
        if verdict in receipt and receipt[verdict]['status'] not in ["PASS", "DISABLED"]:
            print(f"Failed verdict: {verdict}")
            print(email_info)
            return True

    return False


def lambda_handler(event, context):
    # Get the unique ID of the message. This corresponds to the name of the file
    # in S3.
    email_info = event['Records'][0]['ses']
    message_id = email_info['mail']['messageId']
    print(f"Received message ID {message_id}")
    if is_spam(email_info):
        print("Rejecting identified spam/virus email.")
        return

    # Retrieve the file from the S3 bucket.
    message_file = get_message_from_s3(message_id)

    # Create the message.
    message = create_message(email_info, message_file)

    # Send the email and print the result.
    result = send_email(message)
    print(result)
