-- Миграция 001: метки адресов (address labeling).
-- 1) wallet: источник метки и время простановки.
-- 2) Новое правило «Санкционный адрес» (+50).
-- Идемпотентно: можно выполнять повторно.

ALTER TABLE wallet ADD COLUMN IF NOT EXISTS label_source VARCHAR(50);
ALTER TABLE wallet ADD COLUMN IF NOT EXISTS labeled_at   TIMESTAMPTZ;

COMMENT ON COLUMN wallet.label        IS 'Код метки: mixer / exchange / sanctioned / fraud';
COMMENT ON COLUMN wallet.label_source IS 'Откуда метка: ofac_sdn / public_known / etherscan_tag / manual';

INSERT INTO rule (name, description, score, is_active)
VALUES ('Санкционный адрес',
        'Отправитель или получатель находится в санкционном списке (OFAC SDN)',
        50.00, TRUE)
ON CONFLICT (name) DO NOTHING;
