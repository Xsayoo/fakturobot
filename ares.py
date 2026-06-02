import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"


@dataclass
class AresData:
    ico: str
    name: str
    address: Optional[str] = None
    dic: Optional[str] = None


async def lookup_ico(ico: str) -> Optional[AresData]:
    url = _ARES_URL.format(ico=ico.strip())
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()

        name = data.get("obchodniJmeno") or data.get("jmeno") or ""
        sidlo = data.get("sidlo") or {}
        address = sidlo.get("textovaAdresa")
        dic = data.get("dic")

        return AresData(ico=ico, name=name, address=address, dic=dic)

    except httpx.TimeoutException:
        logger.warning("ARES timeout for ICO %s", ico)
        return None
    except Exception as exc:
        logger.warning("ARES lookup failed for ICO %s: %s", ico, exc)
        return None
