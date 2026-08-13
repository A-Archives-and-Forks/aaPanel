# coding: utf-8

import base64
import binascii
import io

from .api_utils import bool_value
from .exceptions import ProjectImportError


def strict_host_key_checking(config):
    '''Return whether SSH must reject hosts missing from known_hosts.'''
    if 'strict_host_key' in config:
        return bool_value(config.get('strict_host_key'))
    if 'accept_new_host_key' in config:
        return not bool_value(config.get('accept_new_host_key'))
    return False


def configure_host_key_policy(client, paramiko, config):
    client.load_system_host_keys()
    if strict_host_key_checking(config):
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


def private_key_content(config):
    content = str(config.get('private_key', '') or '')
    if content:
        return content

    encoded = str(config.get('private_key_base64', '') or '').strip()
    if not encoded:
        return ''
    try:
        decoded = base64.b64decode(''.join(encoded.split()), validate=True)
        return decoded.decode('utf-8')
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ProjectImportError(
            'SSH private key Base64 content is invalid',
            'SSH_PRIVATE_KEY_BASE64_INVALID',
        )


def load_private_key(paramiko, content, passphrase=None):
    content = str(content or '')
    if '\\n' in content and '\n' not in content:
        content = content.replace('\\r\\n', '\n').replace('\\n', '\n')
    content = content.replace('\r\n', '\n').strip()
    if not content:
        raise ProjectImportError('SSH private key content is required', 'SSH_PRIVATE_KEY_REQUIRED')
    content += '\n'

    password = None if passphrase in (None, '') else str(passphrase)
    password_required = getattr(paramiko, 'PasswordRequiredException', None)
    key_classes = []
    for name in ('Ed25519Key', 'RSAKey', 'ECDSAKey', 'DSSKey'):
        key_class = getattr(paramiko, name, None)
        if key_class is not None and key_class not in key_classes:
            key_classes.append(key_class)

    needs_passphrase = False
    for key_class in key_classes:
        try:
            return key_class.from_private_key(io.StringIO(content), password=password)
        except Exception as exc:
            if password_required is not None and isinstance(exc, password_required):
                needs_passphrase = True

    if needs_passphrase and password is None:
        raise ProjectImportError(
            'SSH private key passphrase is required',
            'SSH_KEY_PASSPHRASE_REQUIRED',
        )
    raise ProjectImportError('SSH private key content is invalid', 'SSH_PRIVATE_KEY_INVALID')
