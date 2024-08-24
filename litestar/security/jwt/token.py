from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence

import jwt
import msgspec

from litestar.exceptions import ImproperlyConfiguredException, NotAuthorizedException

if TYPE_CHECKING:
    from typing_extensions import Self


__all__ = ("Token",)


def _normalize_datetime(value: datetime) -> datetime:
    """Convert the given value into UTC and strip microseconds.

    Args:
        value: A datetime instance

    Returns:
        A datetime instance
    """
    if value.tzinfo is not None:
        value.astimezone(timezone.utc)

    return value.replace(microsecond=0)


@dataclass
class Token:
    """JWT Token DTO."""

    exp: datetime
    """Expiration - datetime for token expiration."""
    sub: str
    """Subject - usually a unique identifier of the user or equivalent entity."""
    iat: datetime = field(default_factory=lambda: _normalize_datetime(datetime.now(timezone.utc)))
    """Issued at - should always be current now."""
    iss: Optional[str] = field(default=None)  # noqa: UP007
    """Issuer - optional unique identifier for the issuer."""
    aud: Optional[str] = field(default=None)  # noqa: UP007
    """Audience - intended audience."""
    jti: Optional[str] = field(default=None)  # noqa: UP007
    """JWT ID - a unique identifier of the JWT between different issuers."""
    extras: Dict[str, Any] = field(default_factory=dict)  # noqa: UP006
    """Extra fields that were found on the JWT token."""

    def __post_init__(self) -> None:
        if len(self.sub) < 1:
            raise ImproperlyConfiguredException("sub must be a string with a length greater than 0")

        if isinstance(self.exp, datetime) and (
            (exp := _normalize_datetime(self.exp)).timestamp()
            >= _normalize_datetime(datetime.now(timezone.utc)).timestamp()
        ):
            self.exp = exp
        else:
            raise ImproperlyConfiguredException("exp value must be a datetime in the future")

        if isinstance(self.iat, datetime) and (
            (iat := _normalize_datetime(self.iat)).timestamp()
            <= _normalize_datetime(datetime.now(timezone.utc)).timestamp()
        ):
            self.iat = iat
        else:
            raise ImproperlyConfiguredException("iat must be a current or past time")

    @classmethod
    def decode(
        cls,
        encoded_token: str,
        secret: str,
        algorithm: str,
        audience: Sequence[str] | None = None,
        issuer: Sequence[str] | None = None,
    ) -> Self:
        """Decode a passed in token string and returns a Token instance.

        Args:
            encoded_token: A base64 string containing an encoded JWT.
            secret: The secret with which the JWT is encoded. It may optionally be an individual JWK or JWS set dict
            algorithm: The algorithm used to encode the JWT.
            audience: Verify the audience when decoding the token. If the audience in
                the token does not match any audience given, raise a
                :exc:`NotAuthorizedException`
            issuer: Verify the issuer when decoding the token. If the issuer in the
                token does not match any issuer given, raise a
                :exc:`NotAuthorizedException`

        Returns:
            A decoded Token instance.

        Raises:
            NotAuthorizedException: If the token is invalid.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                jwt=encoded_token,
                key=secret,
                algorithms=[algorithm],
                issuer=list(issuer) if issuer else None,
                audience=audience,
                options={"verify_aud": bool(audience)},
            )
            # msgspec can do these conversions as well, but to keep backwards
            # compatibility, we do it ourselves, since the datetime parsing works a
            # little bit different there
            payload["exp"] = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            payload["iat"] = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
            extra_fields = payload.keys() - {f.name for f in dataclasses.fields(cls)}
            extras = payload.setdefault("extras", {})
            for key in extra_fields:
                extras[key] = payload.pop(key)
            return msgspec.convert(payload, cls, strict=False)
        except (
            KeyError,
            jwt.DecodeError,
            jwt.exceptions.InvalidTokenError,
            ImproperlyConfiguredException,
        ) as e:
            raise NotAuthorizedException("Invalid token") from e

    def encode(self, secret: str, algorithm: str) -> str:
        """Encode the token instance into a string.

        Args:
            secret: The secret with which the JWT is encoded.
            algorithm: The algorithm used to encode the JWT.

        Returns:
            An encoded token string.

        Raises:
            ImproperlyConfiguredException: If encoding fails.
        """
        try:
            return jwt.encode(
                payload={k: v for k, v in asdict(self).items() if v is not None},
                key=secret,
                algorithm=algorithm,
            )
        except (jwt.DecodeError, NotImplementedError) as e:
            raise ImproperlyConfiguredException("Failed to encode token") from e
