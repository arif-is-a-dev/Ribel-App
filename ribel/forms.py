"""Formulir Flask-WTF untuk autentikasi."""

import re

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Length, Regexp, ValidationError

# Format data lama memakai koma sebagai pemisah kolom, jadi koma tetap ditolak.
NO_COMMA = Regexp(r"^[^,]+$", message="Username/email tidak boleh mengandung koma.")
REQUIRED = DataRequired(message="Semua field wajib diisi.")


# Validator email mandiri supaya tidak bergantung pada paket opsional
# ``email_validator`` yang tidak dipakai aplikasi ini.
EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


def validate_email(form, field):
    """Tolak email dengan format yang tidak wajar."""
    if not EMAIL_RE.match((field.data or "").strip()):
        raise ValidationError("Format email tidak valid.")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[REQUIRED, NO_COMMA])
    password = PasswordField("Password", validators=[REQUIRED])


class SignupForm(FlaskForm):
    username = StringField("Username", validators=[REQUIRED, NO_COMMA])
    email = StringField(
        "Email",
        validators=[REQUIRED, validate_email],
    )
    password = PasswordField(
        "Password",
        validators=[REQUIRED, Length(min=4, message="Password minimal 4 karakter.")],
    )


def first_error(form, default):
    """Ambil pesan kesalahan pertama dari form."""
    for field in form:
        for message in field.errors:
            return message
    return default
