# coding: utf-8
"""Shared secret handling for the website Git manager."""

import os
import secrets
import public


GIT_TOKEN_KEY_FILE = "/www/server/panel/data/git_token_aes.key"


def _get_git_token_key():
    key = str(public.readFile(GIT_TOKEN_KEY_FILE) or "").strip()
    if key:
        os.chmod(GIT_TOKEN_KEY_FILE, 0o600)
        return key
    os.makedirs(os.path.dirname(GIT_TOKEN_KEY_FILE), mode=0o700, exist_ok=True)
    generated = secrets.token_hex(16)
    try:
        descriptor = os.open(
            GIT_TOKEN_KEY_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(generated)
        return generated
    except FileExistsError:
        key = str(public.readFile(GIT_TOKEN_KEY_FILE) or "").strip()
        if not key:
            raise ValueError("Failed to initialize the Git token encryption key")
        return key


def encrypt_git_token(token):
    token = str(token or "")
    if not token:
        return ""
    return public.aes_encrypt(token, _get_git_token_key())


def decrypt_git_token(ciphertext):
    ciphertext = str(ciphertext or "")
    if not ciphertext:
        return ""
    return public.aes_decrypt(ciphertext, _get_git_token_key())
