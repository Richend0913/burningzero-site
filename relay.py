"""BURNING ZERO — Signal relay engine.

Reads signal.json from master bot, executes on subscriber MT5 accounts.
MT5 execution is currently stubbed — logs what would happen.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import db

logger = logging.getLogger("relay")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [RELAY] %(message)s"))
    logger.addHandler(handler)

SIGNAL_FILE = Path(__file__).parent / "signal.json"


class SignalRelay:
    def __init__(self):
        self.last_signal_ts: str | None = None
        self.last_exit_ts: str | None = None

    def read_signal(self) -> dict | None:
        """Read signal.json if it exists."""
        if not SIGNAL_FILE.exists():
            return None
        try:
            with open(SIGNAL_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read signal.json: {e}")
            return None

    def check_and_execute(self):
        """Main loop tick: check for new signals and execute."""
        signal = self.read_signal()
        if not signal:
            return

        sig_type = signal.get("type", "entry")
        sig_ts = signal.get("timestamp", "")

        if sig_type == "entry":
            if sig_ts == self.last_signal_ts:
                return  # Already processed
            self.last_signal_ts = sig_ts
            self._execute_entry(signal)

        elif sig_type == "exit":
            if sig_ts == self.last_exit_ts:
                return
            self.last_exit_ts = sig_ts
            self._execute_exit(signal)

    def _execute_entry(self, signal: dict):
        """Execute entry signal for all eligible users."""
        direction = signal.get("direction", "BUY")
        conf = signal.get("conf", 0.0)
        strategies = signal.get("strategies", [])
        symbol = signal.get("symbol", "XAUUSD")
        price = signal.get("price", 0.0)

        users = db.get_approved_active_users()
        logger.info(
            f"New entry signal: {direction} {symbol} conf={conf:.2f} "
            f"strategies={strategies} — {len(users)} eligible users"
        )

        for user in users:
            for strat in strategies:
                if not self._user_wants_strategy(user, strat):
                    continue
                if conf < user["conf_threshold"]:
                    logger.info(
                        f"  User {user['id']} ({user['name']}): skipped {strat} "
                        f"(conf {conf:.2f} < threshold {user['conf_threshold']:.2f})"
                    )
                    continue

                lot = self._calc_lot(user)
                ticket = self._execute_order_stub(user, direction, symbol, lot, price)

                # Record position
                db.add_position(
                    user_id=user["id"],
                    strategy=strat,
                    direction=direction,
                    symbol=symbol,
                    entry_price=price,
                    lot=lot,
                    ticket=ticket,
                    conf=conf,
                )
                logger.info(
                    f"  User {user['id']} ({user['name']}): {direction} {lot} lot "
                    f"{symbol} @ {price} [strat={strat}, ticket={ticket}]"
                )

    def _execute_exit(self, signal: dict):
        """Execute exit signal — close positions for matching strategy."""
        strategy = signal.get("strategy", "")
        reason = signal.get("reason", "signal")

        users = db.get_approved_active_users()
        logger.info(f"Exit signal: strategy={strategy} reason={reason}")

        for user in users:
            positions = db.get_positions(user["id"])
            for pos in positions:
                if pos["strategy"] != strategy:
                    continue

                exit_price = self._get_current_price_stub(pos["symbol"])
                profit = self._calc_profit_stub(pos, exit_price)

                # Close position stub
                self._close_order_stub(user, pos["ticket"])

                # Move position to trade history
                db.add_trade(
                    user_id=user["id"],
                    strategy=pos["strategy"],
                    direction=pos["direction"],
                    symbol=pos["symbol"],
                    entry_price=pos["entry_price"],
                    exit_price=exit_price,
                    lot=pos["lot"],
                    profit=profit,
                    conf=pos["conf"],
                    ticket=pos["ticket"],
                    opened_at=pos["opened_at"],
                    closed_at=datetime.utcnow().isoformat(),
                )
                db.remove_position(pos["id"])

                logger.info(
                    f"  User {user['id']}: closed ticket {pos['ticket']} "
                    f"profit={profit:.2f} ({reason})"
                )

    def _user_wants_strategy(self, user: dict, strategy: str) -> bool:
        mapping = {"A": "strategies_a", "B": "strategies_b", "D": "strategies_d"}
        key = mapping.get(strategy.upper())
        if not key:
            return False
        return bool(user.get(key, 0))

    def _calc_lot(self, user: dict) -> float:
        if user["lot_mode"] == "fixed":
            return user["lot_size"]
        # Dynamic mode — stub: would query MT5 account balance
        # For now return risk_pct * 0.01 as placeholder
        return round(user["risk_pct"] * 0.01, 2)

    def _execute_order_stub(self, user: dict, direction: str, symbol: str,
                            lot: float, price: float) -> int:
        """STUB: Would connect to user's MT5 and place order.
        Returns a mock ticket number."""
        logger.info(
            f"  [STUB] MT5 order: login={user['mt5_login']} server={user['mt5_server']} "
            f"{direction} {lot} {symbol} @ {price}"
        )
        # Generate pseudo-ticket from timestamp
        return int(time.time() * 1000) % 999999999

    def _close_order_stub(self, user: dict, ticket: int):
        """STUB: Would connect to user's MT5 and close position by ticket."""
        logger.info(
            f"  [STUB] MT5 close: login={user['mt5_login']} ticket={ticket}"
        )

    def _get_current_price_stub(self, symbol: str) -> float:
        """STUB: Would get current price from MT5."""
        return 0.0

    def _calc_profit_stub(self, position: dict, exit_price: float) -> float:
        """STUB: Would calculate actual profit."""
        return 0.0


# Singleton
relay = SignalRelay()
