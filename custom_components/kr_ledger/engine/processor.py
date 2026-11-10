"""Turn raw notifications into ledger rows. Blocking (SQLite): run in an executor."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .ledger import Kind, classify, find_duplicate, merge_into
from .models import Method, ParseResult, RawNotification, Status
from .registry import parse
from .store import LedgerStore

CONTENT_DUP_MINUTES = 30
TRANSFER_PAIR_MINUTES = 10


@dataclass(slots=True)
class Outcome:
    status: Status
    reason: str | None = None
    raw_id: int | None = None
    transaction_id: int | None = None
    new_transaction: bool = False
    merged: bool = False
    schedule_id: int | None = None
    transaction: dict | None = None
    changed_ids: list[int] = field(default_factory=list)


def fingerprint(raw: RawNotification) -> str:
    key = f"{raw.package}|{int(raw.post_time.timestamp() * 1000)}|{raw.clean_title}|{raw.body}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def content_hash(raw: RawNotification) -> str:
    key = f"{raw.package}|{raw.clean_title}|{raw.body}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class LedgerProcessor:
    def __init__(
        self,
        store: LedgerStore,
        owners: Sequence[str] = (),
        extra_packages: Iterable[str] = (),
        dedupe_minutes: float = 5,
    ) -> None:
        self.store = store
        self.owners = [o.strip() for o in owners if o and o.strip()]
        self.extra_packages = frozenset(p.strip() for p in extra_packages if p and p.strip())
        self.dedupe_minutes = dedupe_minutes

    def process(self, raw: RawNotification) -> Outcome:
        result = parse(raw, self.extra_packages)
        if result.status in (Status.DROPPED, Status.IGNORED):
            # Never persist personal or irrelevant notifications.
            return Outcome(result.status, reason=result.reason)

        fp = fingerprint(raw)
        if self.store.raw_exists(fp):
            return Outcome(result.status, reason="already processed")

        chash = content_hash(raw)
        same = self.store.recent_same_content(chash, raw.post_time - timedelta(minutes=CONTENT_DUP_MINUTES))
        raw_id = self.store.insert_raw(
            fingerprint=fp,
            content_hash=chash,
            entity_id=raw.entity_id,
            package=raw.package,
            title=raw.clean_title,
            body=raw.body,
            sub_text=raw.clean_sub_text,
            post_time=raw.post_time,
            status=result.status.value if same is None else "duplicate",
            parser=result.parser,
            reason=result.reason if same is None else f"same text as raw #{same['id']}",
            transaction_id=same["transaction_id"] if same is not None else None,
        )
        if same is not None:
            # The phone re-posted an identical notification (seen with 현대카드 SMS).
            return Outcome(result.status, reason="identical notification", raw_id=raw_id, transaction_id=same["transaction_id"])

        if result.status is Status.SCHEDULE and result.schedule:
            s = result.schedule
            sid = self.store.insert_schedule(s.issuer, s.title, s.amount, s.due_date, raw_id)
            return Outcome(Status.SCHEDULE, raw_id=raw_id, schedule_id=sid)

        if result.status is Status.TRANSACTION and result.transaction:
            return self._transaction(result, raw_id)

        return Outcome(result.status, reason=result.reason, raw_id=raw_id)

    # ------------------------------------------------------------------
    def _transaction(self, result: ParseResult, raw_id: int) -> Outcome:
        tx = result.transaction
        assert tx is not None
        store = self.store

        dup_id = find_duplicate(tx, store.candidates(tx.occurred_at), self.dedupe_minutes)
        if dup_id is not None:
            existing = store.get_transaction(dup_id) or {}
            updates = {} if existing.get("edited") else merge_into(existing, existing.get("source_priority", 0), tx)
            kinds = set(existing.get("source_kinds", [])) | {tx.source_kind.value}
            raw_ids = [*existing.get("raw_ids", []), raw_id]
            store.update_transaction(dup_id, source_kinds=kinds, raw_ids=raw_ids, **updates)
            if tx.account_label and "account_label" in updates:
                store.ensure_account(tx.account_label, tx.issuer, tx.method.value)
            store.update_raw(raw_id, transaction_id=dup_id, reason="merged")
            return Outcome(Status.TRANSACTION, raw_id=raw_id, transaction_id=dup_id, merged=True,
                           transaction=store.get_transaction(dup_id), changed_ids=[dup_id])  # fmt: skip

        cls = classify(tx, self.owners)
        if cls.kind in (Kind.EXPENSE, Kind.REFUND) and (learned := store.merchant_category(tx.merchant)):
            cls.category = learned
        account_label = tx.account_label or (tx.issuer if tx.method is Method.PAY else None)
        tx_id = store.insert_transaction(
            occurred_at=tx.occurred_at,
            time_known=int(tx.time_known),
            kind=cls.kind.value,
            direction=tx.direction.value,
            amount=tx.amount,
            currency=tx.currency,
            merchant=tx.merchant,
            account_label=account_label,
            issuer=tx.issuer,
            method=tx.method.value,
            installment=tx.installment,
            category=cls.category,
            balance=tx.balance,
            cumulative=tx.cumulative,
            is_cancel=int(tx.is_cancel),
            source_priority=tx.priority,
            source_kinds=[tx.source_kind.value],
            raw_ids=[raw_id],
        )
        if account_label:
            store.ensure_account(account_label, tx.issuer, tx.method.value)
        store.update_raw(raw_id, transaction_id=tx_id)

        changed = [tx_id]
        row = store.get_transaction(tx_id)
        if row and row["method"] == "bank" and row["kind"] in (Kind.EXPENSE, Kind.INCOME):
            partner = store.bank_transfer_partner(row, TRANSFER_PAIR_MINUTES)
            if partner and not partner.get("edited"):
                # Money left one of the user's accounts and arrived in another.
                for tid in (tx_id, partner["id"]):
                    store.update_transaction(tid, kind=Kind.TRANSFER.value, category="이체")
                changed.append(partner["id"])
                row = store.get_transaction(tx_id)

        return Outcome(Status.TRANSACTION, raw_id=raw_id, transaction_id=tx_id, new_transaction=True,
                       transaction=row, changed_ids=changed)  # fmt: skip

    # ------------------------------------------------------------------
    def reprocess_unparsed(self) -> int:
        """Re-run parsing for stored 'unparsed' notifications (after a rule update)."""
        fixed = 0
        for row in self.store.list_raw("unparsed", include_dismissed=False, limit=1000):
            raw = RawNotification(
                package=row["package"],
                title=row["title"],
                text=row["body"],
                sub_text=row["sub_text"],
                post_time=datetime.fromisoformat(row["post_time"]),
                entity_id=row["entity_id"],
            )
            result = parse(raw, self.extra_packages)
            if result.status is Status.UNPARSED:
                continue
            self.store.update_raw(row["id"], status=result.status.value, parser=result.parser, reason="reprocessed")
            if result.status is Status.TRANSACTION:
                self._transaction(result, row["id"])
            elif result.status is Status.SCHEDULE and result.schedule:
                s = result.schedule
                self.store.insert_schedule(s.issuer, s.title, s.amount, s.due_date, row["id"])
            fixed += 1
        return fixed

    def edit(self, tx_id: int, fields: dict, learn: bool = True) -> dict | None:
        """User edit from the panel. Category edits are remembered per merchant."""
        from .store import EDITABLE_TX_FIELDS

        row = self.store.get_transaction(tx_id)
        if row is None:
            return None
        updates = {k: v for k, v in fields.items() if k in EDITABLE_TX_FIELDS}
        if "kind" in updates:
            updates["direction"] = "in" if updates["kind"] == Kind.INCOME else "out"
        self.store.update_transaction(tx_id, edited=1, **updates)
        merchant = updates.get("merchant", row.get("merchant"))
        if learn and "category" in updates and merchant and row["kind"] in (Kind.EXPENSE, Kind.REFUND):
            self.store.learn_category(merchant, updates["category"])
            if updates["category"]:
                self.store.apply_learned_category(merchant, updates["category"])
        return self.store.get_transaction(tx_id)

    def add_manual(self, **fields) -> int:
        fields.setdefault("direction", "in" if fields.get("kind") == Kind.INCOME else "out")
        fields.setdefault("currency", "KRW")
        fields.setdefault("method", "manual")
        tx_id = self.store.insert_transaction(manual=1, source_priority=100, **fields)
        return tx_id
