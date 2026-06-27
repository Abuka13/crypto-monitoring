"""Модели поверх СУЩЕСТВУЮЩЕЙ схемы (db/schema.sql).

Все модели — managed = False: источник истины это db/schema.sql со всеми
CHECK-ограничениями и типами NUMERIC(40,0) для wei. Django НЕ создаёт и не
меняет эти 7 таблиц (makemigrations их игнорирует, migrate не трогает).
По сути это очищенный результат `python manage.py inspectdb`.

Денежные поля — DecimalField(max_digits=40, decimal_places=0): соответствуют
NUMERIC(40,0) и хранят wei без потери точности. В JSON они отдаются строками
(см. settings.COERCE_DECIMAL_TO_STRING и сериализаторы).
"""
from django.db import models


class BlockchainNetwork(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10)
    is_active = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "blockchain_network"


class Wallet(models.Model):
    id = models.BigAutoField(primary_key=True)
    address = models.CharField(max_length=128)
    network = models.ForeignKey(
        BlockchainNetwork, models.DO_NOTHING, db_column="network_id"
    )
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    transaction_count = models.IntegerField()
    total_received = models.DecimalField(max_digits=40, decimal_places=0)  # wei
    total_sent = models.DecimalField(max_digits=40, decimal_places=0)      # wei
    risk_score = models.DecimalField(max_digits=6, decimal_places=2)
    is_flagged = models.BooleanField()
    label = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "wallet"


class Tx(models.Model):
    id = models.BigAutoField(primary_key=True)
    tx_hash = models.CharField(max_length=80)
    network = models.ForeignKey(
        BlockchainNetwork, models.DO_NOTHING, db_column="network_id"
    )
    sender_wallet = models.ForeignKey(
        Wallet, models.DO_NOTHING, db_column="sender_wallet_id",
        related_name="sent_transactions",
    )
    receiver_wallet = models.ForeignKey(
        Wallet, models.DO_NOTHING, db_column="receiver_wallet_id",
        related_name="received_transactions",
    )
    amount = models.DecimalField(max_digits=40, decimal_places=0)    # wei
    currency = models.CharField(max_length=10)
    gas_fee = models.DecimalField(max_digits=40, decimal_places=0)   # wei
    block_number = models.BigIntegerField()
    transaction_timestamp = models.DateTimeField()
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "tx"


class Rule(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)
    score = models.DecimalField(max_digits=6, decimal_places=2)
    is_active = models.BooleanField()
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "rule"


class TransactionRisk(models.Model):
    id = models.BigAutoField(primary_key=True)
    transaction = models.ForeignKey(
        Tx, models.DO_NOTHING, db_column="transaction_id"
    )
    rule_score = models.DecimalField(max_digits=6, decimal_places=2)
    ml_score = models.DecimalField(max_digits=6, decimal_places=2)
    final_score = models.DecimalField(max_digits=6, decimal_places=2)
    risk_level = models.CharField(max_length=10)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "transaction_risk"


class WalletRisk(models.Model):
    id = models.BigAutoField(primary_key=True)
    wallet = models.ForeignKey(Wallet, models.DO_NOTHING, db_column="wallet_id")
    rule_score = models.DecimalField(max_digits=6, decimal_places=2)
    ml_score = models.DecimalField(max_digits=6, decimal_places=2)
    final_score = models.DecimalField(max_digits=6, decimal_places=2)
    risk_level = models.CharField(max_length=10)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "wallet_risk"


class Alert(models.Model):
    id = models.BigAutoField(primary_key=True)
    transaction_risk = models.ForeignKey(
        TransactionRisk, models.DO_NOTHING,
        db_column="transaction_risk_id", null=True, blank=True,
    )
    wallet_risk = models.ForeignKey(
        WalletRisk, models.DO_NOTHING,
        db_column="wallet_risk_id", null=True, blank=True,
    )
    target_type = models.CharField(max_length=15)   # 'transaction' / 'wallet'
    title = models.CharField(max_length=200)
    description = models.TextField(null=True, blank=True)
    level = models.CharField(max_length=10)         # 'low' / 'medium' / 'high'
    status = models.CharField(max_length=20)         # open/in_progress/closed/false_positive
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "alert"
