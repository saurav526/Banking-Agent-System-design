"""Mock core-banking system of record (SQLite) behind the MCP servers."""
from __future__ import annotations

import random
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta

from ..config import settings


class CoreBanking:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY, name TEXT, address TEXT, email TEXT,
                    kyc_status TEXT, kyc_updated TEXT);
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY, customer_id TEXT, type TEXT, currency TEXT,
                    balance REAL, available REAL, status TEXT);
                CREATE TABLE IF NOT EXISTS transactions (
                    txn_id TEXT PRIMARY KEY, account_id TEXT, ts TEXT, description TEXT,
                    amount REAL, balance_after REAL, category TEXT);
                CREATE TABLE IF NOT EXISTS service_requests (
                    reference TEXT PRIMARY KEY, customer_id TEXT, type TEXT, payload TEXT,
                    status TEXT, created TEXT, idempotency_key TEXT UNIQUE);
                """
            )
        if self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            self._seed()

    def _seed(self) -> None:
        rnd = random.Random(42)
        customers = [
            ("CUST001", "Alice Sharma", "12 MG Road, Bengaluru 560001", "alice@example.com", "VERIFIED", "2024-03-01"),
            ("CUST002", "Bob Mehta", "7 Marine Drive, Mumbai 400002", "bob@example.com", "PENDING_RENEWAL", "2021-06-11"),
        ]
        accounts = [
            ("100000000001", "CUST001", "SAVINGS", "INR", 0, 0, "ACTIVE"),
            ("100000000002", "CUST001", "CURRENT", "INR", 0, 0, "ACTIVE"),
            ("200000000001", "CUST002", "SAVINGS", "INR", 0, 0, "ACTIVE"),
        ]
        merchants = [("Amazon", "shopping"), ("Swiggy", "food"), ("Uber", "transport"), ("Electricity Board", "utilities"),
                     ("Netflix", "entertainment"), ("Salary - ACME Corp", "income"), ("ATM Withdrawal", "cash"),
                     ("UPI Transfer", "transfer")]
        with self.conn:
            self.conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
            self.conn.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?)", accounts)
            for n, acc in enumerate(accounts, start=1):
                bal = 50_000.0
                start = datetime(2026, 8, 1)
                for i in range(40):
                    name, cat = rnd.choice(merchants)
                    amt = round(rnd.uniform(1000, 85000), 2) if cat == "income" else -round(rnd.uniform(100, 6000), 2)
                    bal = round(bal + amt, 2)
                    ts = (start + timedelta(days=i * 2, hours=rnd.randint(0, 23))).isoformat(timespec="minutes")
                    self.conn.execute(
                        "INSERT INTO transactions VALUES (?,?,?,?,?,?,?)",
                        (f"TXN{n}{i:04d}", acc[0], ts, name, amt, bal, cat),
                    )
                self.conn.execute("UPDATE accounts SET balance=?, available=? WHERE account_id=?", (bal, bal - 500, acc[0]))

    # --------- queries ---------
    def accounts_for(self, customer_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM accounts WHERE customer_id=?", (customer_id,)).fetchall()
        return [dict(r) for r in rows]

    def account(self, account_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        return dict(r) if r else None

    def customer(self, customer_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
        return dict(r) if r else None

    def transactions(self, account_id: str, limit: int = 5, txn_id: str | None = None,
                     from_date: str | None = None, to_date: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM transactions WHERE account_id=?", [account_id]
        if txn_id:
            q += " AND txn_id=?"
            args.append(txn_id)
        if from_date:
            q += " AND ts>=?"
            args.append(from_date)
        if to_date:
            q += " AND ts<=?"
            args.append(to_date + "T23:59")
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def create_request(self, customer_id: str, rtype: str, payload: str, idem_key: str | None = None) -> dict:
        with self._lock, self.conn:
            if idem_key:
                r = self.conn.execute("SELECT * FROM service_requests WHERE idempotency_key=?", (idem_key,)).fetchone()
                if r:
                    return {**dict(r), "duplicate": True}
            ref = f"SR{time.strftime('%y%m%d')}{uuid.uuid4().hex[:6].upper()}"
            row = (ref, customer_id, rtype, payload, "SUBMITTED", datetime.now().isoformat(timespec="seconds"), idem_key)
            self.conn.execute("INSERT INTO service_requests VALUES (?,?,?,?,?,?,?)", row)
            return dict(zip(["reference", "customer_id", "type", "payload", "status", "created", "idempotency_key"], row))

    def update_customer(self, customer_id: str, **fields) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self.conn:
            self.conn.execute(f"UPDATE customers SET {sets} WHERE customer_id=?", (*fields.values(), customer_id))


core = CoreBanking(settings.core_banking_db)
