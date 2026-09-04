"""Cache table logic for normalization results (raw name -> canonical item)."""


def get(raw_name: str) -> dict | None:
    raise NotImplementedError


def put(raw_name: str, canonical: dict) -> None:
    raise NotImplementedError
