from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import get_settings


@dataclass(frozen=True)
class ResolvedAsset:
    symbol: str
    asset_id: str
    is_open: bool = True
    payout_percent: float | None = None
    is_otc: bool | None = None


class AssetCatalog:
    """
    Minimal asset mapping layer.

    Configure via PO_ASSET_MAP_JSON, for example:

    {
      "eurusd_otc": {"id": "123", "open": true, "payout": 92, "otc": true},
      "btcusd": {"id": "999", "otc": false}
    }

    When trade_otc_only is true (see TRADE_OTC_ONLY), only assets with "otc": true are tradable.
    Bare ids have unknown OTC / payout and are blocked under OTC-only and min-payout rules.

    Value can also be a bare id:

    { "eurusd": "123" }
    """

    def _load_map(self) -> dict[str, Any]:
        raw = get_settings().optional_po_asset_map_json()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def resolve(self, symbol: str) -> tuple[ResolvedAsset | None, str | None]:
        sym = (symbol or "").strip().lower()
        if not sym:
            return None, "empty_symbol"

        m = self._load_map()
        if not m:
            return None, "asset_map_not_configured"

        entry = m.get(sym)
        if entry is None:
            return None, "asset_not_mapped"

        if isinstance(entry, (str, int, float)):
            return ResolvedAsset(symbol=sym, asset_id=str(entry), is_otc=None), None

        if not isinstance(entry, dict):
            return None, "invalid_asset_map_entry"

        asset_id = entry.get("id")
        if asset_id is None or str(asset_id).strip() == "":
            return None, "asset_id_missing"

        is_open = entry.get("open", True)
        payout = entry.get("payout", None)
        try:
            is_open_b = bool(is_open)
        except Exception:
            is_open_b = True
        payout_f = None
        if payout is not None:
            try:
                payout_f = float(payout)
            except Exception:
                payout_f = None

        otc_raw = entry.get("otc", None)
        is_otc: bool | None = None
        if otc_raw is not None:
            if isinstance(otc_raw, bool):
                is_otc = otc_raw
            else:
                s = str(otc_raw).strip().lower()
                if s in ("1", "true", "yes", "otc"):
                    is_otc = True
                elif s in ("0", "false", "no"):
                    is_otc = False

        return (
            ResolvedAsset(
                symbol=sym,
                asset_id=str(asset_id).strip(),
                is_open=is_open_b,
                payout_percent=payout_f,
                is_otc=is_otc,
            ),
            None,
        )

    def is_tradable(
        self,
        symbol: str,
        *,
        min_payout_percent: float | None = None,
        require_otc: bool | None = None,
    ) -> tuple[bool, str | None]:
        """
        require_otc: when True, only assets explicitly marked otc=true in the map are tradable.
        Defaults to Settings.trade_otc_only.
        """
        asset, err = self.resolve(symbol)
        if asset is None:
            return False, err
        if not asset.is_open:
            return False, "market_closed"

        if require_otc is None:
            require_otc = bool(get_settings().trade_otc_only)
        if require_otc:
            if asset.is_otc is not True:
                if asset.is_otc is False:
                    return False, "not_otc"
                return False, "otc_unknown"

        if min_payout_percent is not None and float(min_payout_percent) > 0:
            if asset.payout_percent is None:
                return False, "payout_unknown"
            if asset.payout_percent < float(min_payout_percent):
                return False, "payout_below_threshold"
        return True, None


assets = AssetCatalog()

