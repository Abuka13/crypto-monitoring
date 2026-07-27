"""Модели поверх существующей схемы (db/schema.sql), managed=False — Django их
не создаёт и не меняет. wei -> DecimalField(40,0) (в JSON строкой)."""
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
    label = models.CharField(max_length=50, null=True, blank=True)          # mixer/exchange/sanctioned/fraud
    label_source = models.CharField(max_length=50, null=True, blank=True)   # ofac_sdn/public_known/etherscan_tag/manual
    labeled_at = models.DateTimeField(null=True, blank=True)
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
    graph_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    final_score = models.DecimalField(max_digits=6, decimal_places=2)
    risk_level = models.CharField(max_length=10)
    decision = models.JSONField(null=True, blank=True)
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
    graph_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    risk_level = models.CharField(max_length=10)
    ml_explanation = models.TextField(null=True, blank=True)
    decision = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "wallet_risk"


class WalletFeatures(models.Model):
    """Числовые признаки кошелька для ML (одна строка на кошелёк)."""
    wallet = models.OneToOneField(
        "Wallet", models.DO_NOTHING, db_column="wallet_id",
        primary_key=True, related_name="features",
    )
    tx_total = models.IntegerField()
    tx_in = models.IntegerField()
    tx_out = models.IntegerField()
    total_received = models.DecimalField(max_digits=40, decimal_places=0)
    total_sent = models.DecimalField(max_digits=40, decimal_places=0)
    avg_amount = models.DecimalField(max_digits=40, decimal_places=0)
    max_amount = models.DecimalField(max_digits=40, decimal_places=0)
    in_out_count_ratio = models.FloatField()
    in_out_value_ratio = models.FloatField()
    unique_counterparties = models.IntegerField()
    unique_senders = models.IntegerField()
    unique_receivers = models.IntegerField()
    counterparty_spread = models.FloatField()
    active_period_days = models.FloatField()
    avg_tx_per_day = models.FloatField()
    max_tx_24h = models.IntegerField()
    small_tx_ratio = models.FloatField()
    zero_tx_ratio = models.FloatField()
    transit_ratio = models.FloatField()
    computed_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "wallet_features"


class WalletGraphFeatures(models.Model):
    """Граф-признаки кошелька (положение в сети переводов). Одна строка на кошелёк."""
    wallet = models.OneToOneField(
        "Wallet", models.DO_NOTHING, db_column="wallet_id",
        primary_key=True, related_name="graph_features",
    )
    in_degree = models.IntegerField()
    out_degree = models.IntegerField()
    degree_centrality = models.FloatField()
    risky_neighbors = models.IntegerField()
    risky_neighbor_ratio = models.FloatField()
    transit_ratio = models.FloatField()
    fan_in_ratio = models.FloatField()
    fan_out_ratio = models.FloatField()
    graph_score = models.DecimalField(max_digits=6, decimal_places=2)
    graph_explanation = models.TextField(null=True, blank=True)
    computed_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "wallet_graph_features"


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
